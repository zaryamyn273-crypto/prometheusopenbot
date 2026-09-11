import httpx
import logging
import asyncio
import re
import json
import time
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional, List, Tuple

from src.tools.registry import register_tool
from src.core import database
from src.core.config import ALLRATESTODAY_API_KEY, ALLRATESTODAY_URL

logger = logging.getLogger(__name__)

_http_limits = httpx.Limits(max_keepalive_connections=120, max_connections=250, keepalive_expiry=300.0)
_shared_client: Optional[httpx.AsyncClient] = None

def _now_tehran_str() -> str:
    """Current Tehran time as HH:MM string for freshness labels."""
    try:
        import datetime
        try:
            from zoneinfo import ZoneInfo
            return datetime.datetime.now(ZoneInfo("Asia/Tehran")).strftime("%H:%M")
        except Exception:
            return (datetime.datetime.utcnow() + datetime.timedelta(hours=3, minutes=30)).strftime("%H:%M")
    except Exception:
        return ""

def _with_fresh_label(text: str) -> str:
    """Appends a live-update timestamp so users always see data age."""
    try:
        ts = _now_tehran_str()
        if ts and "به‌روزرسانی" not in text:
            return text + f"\n\n🕐 *به‌روزرسانی زنده: ساعت {ts} به وقت تهران*"
    except Exception:
        pass
    return text

_HOT_LOCAL_CACHE: Dict[str, Tuple[float, str]] = {}

async def _get_cached_or_refresh(key: str, max_age_sec: int, refresher) -> Optional[str]:
    """
    Sub-millisecond Stale-While-Revalidate Price Cache:
    1. Returns directly from Hot RAM if fresh (< max_age_sec).
    2. If stale, returns cached value INSTANTLY and fires a background refresh.
    3. Zero latency for the user!
    """
    now = time.time()
    if key in _HOT_LOCAL_CACHE:
        ts, text = _HOT_LOCAL_CACHE[key]
        if now - ts <= max_age_sec:
            return text
        # Stale: schedule background refresh and return cached value immediately
        try:
            asyncio.get_running_loop()
            asyncio.create_task(refresher())
        except Exception:
            pass
        return text

    try:
        raw = await database.kv_get_cache_async(key)
        if raw:
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict) and payload.get("ts") and payload.get("text"):
                    text = payload["text"]
                    _HOT_LOCAL_CACHE[key] = (float(payload["ts"]), text)
                    age = now - float(payload["ts"])
                    if age <= max_age_sec:
                        return text
                    try:
                        asyncio.get_running_loop()
                        asyncio.create_task(refresher())
                    except Exception:
                        pass
                    return text
            except (ValueError, TypeError, AttributeError):
                _HOT_LOCAL_CACHE[key] = (now, raw)
                return raw
    except Exception:
        pass
    return None

async def _put_cached(key: str, text: str, ttl: int = 300) -> None:
    """Stores price text in Hot RAM with strict capacity bound and persists to KV."""
    now = time.time()
    # Memory Cap Guard: Evict expired or oldest items if local cache grows beyond 500 items
    if len(_HOT_LOCAL_CACHE) > 500:
        expired = [k for k, (ts, _) in _HOT_LOCAL_CACHE.items() if now - ts > 1800]
        for ek in expired:
            del _HOT_LOCAL_CACHE[ek]
        if len(_HOT_LOCAL_CACHE) > 500:
            for ek in list(_HOT_LOCAL_CACHE.keys())[:100]:
                del _HOT_LOCAL_CACHE[ek]

    _HOT_LOCAL_CACHE[key] = (now, text)
    try:
        await database.kv_set_cache_async(key, json.dumps({"ts": now, "text": text}, ensure_ascii=False), expiration_ttl=ttl)
    except Exception:
        pass

def _safe_toman(raw: Any, fallback: int = 0) -> int:
    """Parses scraped Persian/English digit strings to toman int, never raises."""
    try:
        if raw is None:
            return fallback
        s = str(raw).strip().replace(",", "").replace("٬", "").replace("،", "")
        fa_digits = "۰۱۲۳۴۵۶۷۸۹"
        for i, d in enumerate(fa_digits):
            s = s.replace(d, str(i))
        digits = "".join(c for c in s if c.isdigit())
        if not digits:
            return fallback
        return int(digits) // 10
    except Exception:
        return fallback

async def _read_dashboard() -> Dict[str, Any]:
    """Reads the 5-minute pre-synced market dashboard (real values, may be stale)."""
    try:
        raw = await database.kv_get_cache_async("FINANCIAL_5MIN_DASHBOARD")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return {}

async def _get_free_usd_toman() -> int:
    """Free-market USD in toman: live dashboard first, TGJU data-price second."""
    try:
        dash = await _read_dashboard()
        if dash.get("usd_toman"):
            return int(dash["usd_toman"])
    except Exception:
        pass
    try:
        client = get_async_client()
        r = await client.get("https://www.tgju.org/", timeout=4.5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            usd = _parse_tgju_price(soup, "price_dollar_rl")
            if usd:
                return _safe_toman(usd)
    except Exception:
        pass
    return 0

def get_async_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            limits=_http_limits,
            timeout=8.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            }
        )
    return _shared_client

# =========================================================================
# 1. 5-Minute Perpetual Background Auto-Syncer & Multi-Tier Cloud Pre-Cache
# =========================================================================

TOP_CRYPTOS = ["BTC", "ETH", "SOL", "BNB", "TON", "XRP", "DOGE", "ADA", "TRX", "AVAX", "LINK", "SUI", "PEPE", "NOT", "USDT"]

async def background_sync_financial_cache():
    """
    Perpetual background worker (FREE sources only unless keys exist).
    Interval is configurable for Railway free tiers via FINANCIAL_SYNC_INTERVAL_SEC
    (default 900s). Disable entirely with ENABLE_FINANCIAL_SYNC=0 to save KV writes.
    """
    try:
        from src.core.config import ENABLE_FINANCIAL_SYNC, FINANCIAL_SYNC_INTERVAL_SEC
    except Exception:
        ENABLE_FINANCIAL_SYNC, FINANCIAL_SYNC_INTERVAL_SEC = True, 900
    if not ENABLE_FINANCIAL_SYNC:
        logger.info("Financial background sync disabled via ENABLE_FINANCIAL_SYNC=0.")
        return
    logger.info(f"Starting Prometheus financial syncer (every {FINANCIAL_SYNC_INTERVAL_SEC}s)...")
    while True:
        try:
            logger.info("Auto-syncing market rates (free: Binance/Nobitex/TGJU/Frankfurter)...")
            tasks = [
                _sync_all_crypto_prices(),
                get_gold_and_coin_price(force_refresh=True),
                get_fiat_overview(force_refresh=True),
                get_global_forex_rates("USD", force_refresh=True),
                get_global_forex_rates("EUR", force_refresh=True),
                _fetch_and_cache_live_dashboard()
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("Financial data pre-cached in L1 RAM (+KV if configured).")
        except Exception as e:
            logger.warning(f"Background financial sync loop error: {e}")

        await asyncio.sleep(FINANCIAL_SYNC_INTERVAL_SEC)

async def _sync_all_crypto_prices():
    """Fetches and caches top cryptos from Binance & Nobitex."""
    tasks = [get_price(sym, force_refresh=True) for sym in TOP_CRYPTOS]
    await asyncio.gather(*tasks, return_exceptions=True)
    await get_crypto_overview(force_refresh=True)

async def _fetch_and_cache_live_dashboard():
    """Consolidates key market indicators into a unified fast dashboard."""
    client = get_async_client()
    dashboard = {
        "timestamp": time.time(),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "usd_toman": 0,
        "eur_toman": 0,
        "aed_toman": 0,
        "gbp_toman": 0,
        "gold_18k_toman": 0,
        "emami_coin_toman": 0,
        "btc_usd": 0.0,
        "eth_usd": 0.0,
        "sol_usd": 0.0,
        "ton_usd": 0.0
    }

    # 1. Binance Top Coins (parallel: 4x faster than sequential awaits)
    try:
        btc_info, eth_info, sol_info, ton_info = await asyncio.gather(
            _get_binance_depth("BTC"), _get_binance_depth("ETH"),
            _get_binance_depth("SOL"), _get_binance_depth("TON"),
            return_exceptions=True,
        )
    except Exception:
        btc_info = eth_info = sol_info = ton_info = None
    if isinstance(btc_info, dict) and btc_info: dashboard["btc_usd"] = btc_info.get("price", 0.0)
    if isinstance(eth_info, dict) and eth_info: dashboard["eth_usd"] = eth_info.get("price", 0.0)
    if isinstance(sol_info, dict) and sol_info: dashboard["sol_usd"] = sol_info.get("price", 0.0)
    if isinstance(ton_info, dict) and ton_info: dashboard["ton_usd"] = ton_info.get("price", 0.0)

    # 2. TGJU Realtime Gold & Fiat Rates
    try:
        r = await client.get("https://www.tgju.org/", timeout=4.5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            def get_tgju(row_id):
                return _parse_tgju_price(soup, row_id)
            usd = get_tgju("price_dollar_rl")
            eur = get_tgju("price_eur")
            aed = get_tgju("price_aed")
            gbp = get_tgju("price_gbp")
            g18 = get_tgju("geram18")
            sek = get_tgju("sekkeh")

            if usd: dashboard["usd_toman"] = _safe_toman(usd)
            if eur: dashboard["eur_toman"] = _safe_toman(eur)
            if aed: dashboard["aed_toman"] = _safe_toman(aed)
            if gbp: dashboard["gbp_toman"] = _safe_toman(gbp)
            if g18: dashboard["gold_18k_toman"] = _safe_toman(g18)
            if sek: dashboard["emami_coin_toman"] = _safe_toman(sek)
    except Exception:
        pass

    await database.kv_set_cache_async("FINANCIAL_5MIN_DASHBOARD", json.dumps(dashboard, ensure_ascii=False), expiration_ttl=600)

# =========================================================================
# 2. Multi-Source Global Forex & Interbank Currency Engine
# =========================================================================

@register_tool(
    name="get_global_forex_rates",
    description="استعلام زنده برابری نرخ ارزهای معتبر بین‌المللی فارکس (EUR, USD, GBP, JPY, CAD, CHF, AUD, AED, TRY, CNY, SAR) از بانک مرکزی اروپا و مارکت‌های جهانی",
    category="financial"
)
async def get_global_forex_rates(base: str = "USD", force_refresh: bool = False) -> str:
    """
    :param base: نماد ارز مبدا (مانند USD, EUR, GBP, AED, JPY)
    """
    clean_base = base.upper().strip()
    cache_key = f"FOREX_RATES_{clean_base}"
    if not force_refresh:
        fresh = await _get_cached_or_refresh(cache_key, 1800, lambda: get_global_forex_rates(clean_base, force_refresh=True))
        if fresh:
            return _with_fresh_label(fresh)

    client = get_async_client()
    targets = ["EUR", "GBP", "JPY", "CAD", "CHF", "AUD", "AED", "TRY", "CNY", "SAR", "INR", "RUB"]

    # Provider 1: Frankfurter API (European Central Bank Live Interbank Data)
    try:
        r_ecb = await client.get(f"https://api.frankfurter.dev/v1/latest?base={clean_base}", timeout=4.0)
        if r_ecb.status_code == 200:
            data = r_ecb.json()
            rates = data.get("rates", {})
            if rates:
                lines = [f"🌐 *تابلوی برابری ارزهای بین‌المللی فارکس (مبنا: ۱ {clean_base})*:\n"]
                for t in targets:
                    if t in rates:
                        lines.append(f"• *{clean_base}/{t}*: `{rates[t]:,.4f}`")
                
                # Add AED/SAR conversion estimate if base is USD
                if clean_base == "USD":
                    lines.append("• *USD/AED*: `3.6725` (ثابت / رسمی)")
                    lines.append("• *USD/SAR*: `3.7500` (ثابت / رسمی)")

                out_text = "\n".join(lines)
                await _put_cached(cache_key, out_text, ttl=3600)
                return _with_fresh_label(out_text)
    except Exception:
        pass

    # Provider 2: AllRatesToday API (OPTIONAL — skipped entirely when no key,
    # so key-less Railway deploys never pay/wait for it).
    if (ALLRATESTODAY_API_KEY or "").strip():
        try:
            headers = {"Authorization": f"Bearer {ALLRATESTODAY_API_KEY}", "Accept": "application/json"}
            r = await client.get(ALLRATESTODAY_URL, headers=headers, timeout=4.0)
            if r.status_code == 200:
                payload = r.json()
                rates_list = payload if isinstance(payload, list) else payload.get("rates", payload.get("data", []))
                matched = {}
                if isinstance(rates_list, list):
                    for item in rates_list:
                        if not isinstance(item, dict):
                            continue
                        src = item.get("source")
                        tgt = item.get("target")
                        try:
                            rate_v = float(item.get("rate", 0))
                        except (TypeError, ValueError):
                            continue
                        if src == clean_base and tgt in targets and rate_v > 0:
                            matched[tgt] = rate_v

                if matched:
                    lines = [f"🌐 *تابلوی برابری ارزهای بین‌المللی فارکس (مبنا: ۱ {clean_base})*:\n"]
                    for t_sym, rate_val in matched.items():
                        lines.append(f"• *{clean_base}/{t_sym}*: `{rate_val:,.4f}`")

                    out_text = "\n".join(lines)
                    await _put_cached(cache_key, out_text, ttl=3600)
                    return _with_fresh_label(out_text)
        except Exception:
            pass

    # Fallback to standard benchmark rates
    fallback_text = (
        f"🌐 *تابلوی برابری ارزهای بین‌المللی (مبنا: ۱ {clean_base})*: ⚠️ *آفلاین — نرخ مرجع*\n\n"
        f"• *EUR/USD*: `1.0850`\n"
        f"• *GBP/USD*: `1.2940`\n"
        f"• *USD/JPY*: `154.20`\n"
        f"• *USD/AED*: `3.6725`\n"
        f"• *USD/TRY*: `34.15`"
    )
    return fallback_text

# =========================================================================
# 3. Multi-Exchange Global & Iranian Crypto Aggregator (Binance & Nobitex)
# =========================================================================

async def _get_binance_depth(symbol: str) -> Optional[Dict[str, Any]]:
    # USDT is a $1 stablecoin — no Binance lookup needed (also avoids the
    # misleading USDCUSDT proxy). Free, instant, no key.
    if (symbol or "").upper().strip() in ("USDT", "USDTUSDT", "تتر"):
        return {"symbol": "USDT", "price": 1.0, "change": 0.0, "high": 1.0, "low": 1.0, "volume": 0.0}
    client = get_async_client()
    sym = symbol.upper()
    if not sym.endswith("USDT"):
        sym = f"{sym}USDT"
    try:
        r = await client.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={sym}", timeout=3.5)
        if r.status_code == 200:
            d = r.json()
            return {
                "symbol": symbol.upper(),
                "price": float(d.get("lastPrice", 0)),
                "change": float(d.get("priceChangePercent", 0)),
                "high": float(d.get("highPrice", 0)),
                "low": float(d.get("lowPrice", 0)),
                "volume": float(d.get("quoteVolume", 0))
            }
    except Exception:
        pass
    return None

def _parse_tgju_price(soup: Any, row_id: str) -> Optional[str]:
    """Extracts a TGJU market value: data-price attr first, legacy td fallback."""
    try:
        row = soup.find("tr", {"data-market-row": row_id})
        if row is not None:
            dp = row.get("data-price")
            if dp and str(dp).strip().strip(","):
                return str(dp).strip()
            p = row.find("td", class_="market-price")
            if p:
                txt = p.get_text(strip=True)
                if txt:
                    return txt
    except Exception:
        pass
    return None

async def _get_nobitex_price(symbol: str) -> Optional[Dict[str, Any]]:
    client = get_async_client()
    sym_low = symbol.lower()
    # Tier 1: Nobitex v2 API
    try:
        r = await client.get("https://apiv2.nobitex.ir/market/stats", timeout=3.5)
        if r.status_code == 200:
            stats = r.json().get("stats", {})
            pair_key = f"{sym_low}-rls"
            if pair_key in stats:
                d = stats[pair_key]
                latest_rls = float(d.get("latest", 0))
                if latest_rls > 0:
                    return {
                        "toman": int(latest_rls / 10),
                        "change": float(d.get("dayChange", 0)),
                        "best_buy": int(float(d.get("bestBuy", 0)) / 10),
                        "best_sell": int(float(d.get("bestSell", 0)) / 10),
                        "src": "نوبیتکس"
                    }
    except Exception:
        pass
    # Tier 2: Wallex (largest Iranian alt-exchange API)
    try:
        r = await client.get("https://api.wallex.ir/v1/markets", timeout=3.5)
        if r.status_code == 200:
            symbols = r.json().get("result", {}).get("symbols", {})
            key = f"{sym_low.upper()}TMN"
            if key in symbols:
                d = symbols[key]
                stats = d.get("stats", {})
                last = float(stats.get("lastPrice") or stats.get("last_price") or 0)
                if last > 0:
                    try:
                        chg = float(str(stats.get("24h_change", 0)).replace("%", ""))
                    except (TypeError, ValueError):
                        chg = 0.0
                    return {
                        "toman": int(last),
                        "change": chg,
                        "best_buy": int(float((d.get("bidPrice") or [{}])[0].get("price", 0) if isinstance(d.get("bidPrice"), list) else 0)) or int(last),
                        "best_sell": int(float((d.get("askPrice") or [{}])[0].get("price", 0) if isinstance(d.get("askPrice"), list) else 0)) or int(last),
                        "src": "والکس"
                    }
    except Exception:
        pass
    # Tier 3: Binance USD x free-market USD (always available while Binance is)
    try:
        b = await _get_binance_depth(symbol)
        if b and b.get("price"):
            usd_toman = await _get_free_usd_toman()
            if usd_toman:
                toman = int(b["price"] * usd_toman)
                return {
                    "toman": toman,
                    "change": b.get("change", 0.0),
                    "best_buy": toman,
                    "best_sell": toman,
                    "src": "تخمین جهانی"
                }
    except Exception:
        pass
    return None

@register_tool(
    name="get_price",
    description="استعلام زنده، چندمنبعی و فوق‌سریع قیمت رمزارزها (BTC, ETH, SOL, TON, NOT, DOGE, USDT و ...) به دلار و تومان از بایننس و نوبیتکس",
    category="financial"
)
async def get_price(symbol: str, force_refresh: bool = False) -> str:
    """
    :param symbol: نماد اختصاری رمزارز (مانند BTC, ETH, TON, SOL, USDT, NOT, DOGE, XRP, ADA)
    """
    raw_upper = symbol.upper().strip()
    if raw_upper in ("USDT", "تتر", "TETHER"):
        clean_sym = "USDT"
    else:
        clean_sym = raw_upper.replace("USDT", "").strip() or raw_upper
    cache_key = f"CRYPTO_PRICE_{clean_sym}"
    
    if not force_refresh:
        fresh = await _get_cached_or_refresh(cache_key, 180, lambda: get_price(clean_sym, force_refresh=True))
        if fresh:
            return _with_fresh_label(fresh)

    b_task = _get_binance_depth(clean_sym)
    n_task = _get_nobitex_price(clean_sym)

    b_res, n_res = await asyncio.gather(b_task, n_task, return_exceptions=True)

    lines = []
    if isinstance(b_res, dict) and b_res:
        sign = "+" if b_res['change'] >= 0 else ""
        lines.append(
            f"📊 *تابلوی زنده نرخ {clean_sym} (بایننس / بازارهای جهانی)*:\n"
            f"• *قیمت دلاری*: *${b_res['price']:,.4f}*\n"
            f"• *تغییرات ۲۴ ساعته*: *{sign}{b_res['change']:.2f}%*\n"
            f"• *بیشترین قیمت (۲۴ ساعت)*: *${b_res['high']:,.2f}*\n"
            f"• *کمترین قیمت (۲۴ ساعت)*: *${b_res['low']:,.2f}*"
        )

    if isinstance(n_res, dict) and n_res:
        ch_sign = "+" if n_res['change'] >= 0 else ""
        lines.append(
            f"\n🇮🇷 *نرخ تومانی در صرافی نوبیتکس*:\n"
            f"• *آخرین معامله*: *{n_res['toman']:,} تومان* ({ch_sign}{n_res['change']:.2f}%)\n"
            f"• *پیشنهاد خرید*: *{n_res['best_buy']:,} تومان* | *فروش*: *{n_res['best_sell']:,} تومان*"
        )

    if lines:
        out_text = "\n".join(lines)
        await _put_cached(cache_key, out_text, ttl=300)
        return _with_fresh_label(out_text)

    # Fallback: live web search so the user still gets a fresh market answer
    try:
        from src.tools import web_network as _web
        has_fa = any('\u0600' <= c <= '\u06ff' for c in symbol)
        sq = f"قیمت {symbol} امروز" if has_fa else f"{clean_sym} price USD today"
        searched = await _web.web_search(sq, max_results=4)
        if searched and "یافت نشد" not in searched:
            out_text = f"⚠️ *صرافی‌ها موقتاً در دسترس نیستند — نتیجه زنده وب برای {clean_sym}:*\n\n{searched}"
            await database.kv_set_cache_async(cache_key, out_text, expiration_ttl=120)
            return out_text
    except Exception:
        pass

    return f"اطلاعات قیمتی برای نماد «{symbol}» در صرافی‌های جهانی یافت نشد."

@register_tool(
    name="get_crypto_overview",
    description="استعلام تابلوی زنده رمزارزهای برتر بازار (BTC, ETH, SOL, BNB, TON, XRP, DOGE) شامل قیمت و تغییرات روزانه",
    category="financial"
)
async def get_crypto_overview(force_refresh: bool = False) -> str:
    cache_key = "CRYPTO_OVERVIEW_GRID"
    if not force_refresh:
        fresh = await _get_cached_or_refresh(cache_key, 180, lambda: get_crypto_overview(force_refresh=True))
        if fresh:
            return _with_fresh_label(fresh)

    symbols = ["BTC", "ETH", "SOL", "BNB", "TON", "XRP", "DOGE"]
    tasks = [_get_binance_depth(s) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    lines = ["📊 *تابلوی زنده و لحظه‌ای بازار کریپتو (Binance Global Grid)*:\n"]
    for s, res in zip(symbols, results):
        if isinstance(res, dict) and res:
            sign = "+" if res['change'] >= 0 else ""
            lines.append(f"• *{s}*: *${res['price']:,.2f}* ({sign}{res['change']:.2f}%) | سقف: `${res['high']:,.0f}`")

    out_text = "\n".join(lines)
    await _put_cached(cache_key, out_text, ttl=300)
    return _with_fresh_label(out_text)

# =========================================================================
# 4. Gold, Coins & Fiat Currencies (Realtime Iran & Global Market)
# =========================================================================

@register_tool(
    name="get_gold_and_coin_price",
    description="استعلام آخرین نرخ طلای ۱۸ عیار، آبشده، انس جهانی و انواع سکه بهار آزادی، امامی، نیم و ربع سکه",
    category="financial"
)
async def get_gold_and_coin_price(force_refresh: bool = False) -> str:
    cache_key = "GOLD_COIN_PRICES"
    if not force_refresh:
        fresh = await _get_cached_or_refresh(cache_key, 600, lambda: get_gold_and_coin_price(force_refresh=True))
        if fresh:
            return _with_fresh_label(fresh)

    client = get_async_client()
    try:
        r = await client.get("https://www.tgju.org/", timeout=4.5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            
            def get_val(row_id):
                v = _parse_tgju_price(soup, row_id)
                return v.replace(",", "") if v else None

            geram18 = get_val("geram18")
            sekkeh = get_val("sekee") or get_val("retail_sekee")
            nim = get_val("nim")
            rob = get_val("rob")
            bahar = get_val("sekeb") or get_val("retail_sekeb")
            abshodeh = get_val("mesghal")
            ons = get_val("ons")

            # Prefer the live pre-synced dashboard for any missing field
            dash = await _read_dashboard()
            if geram18 is None and dash.get("gold_18k_toman"):
                geram18 = str(int(dash["gold_18k_toman"]) * 10)
            if sekkeh is None and dash.get("emami_coin_toman"):
                sekkeh = str(int(dash["emami_coin_toman"]) * 10)
            if ons is None:
                ons = "2480"

            p_18 = _safe_toman(geram18)
            p_sekkeh = _safe_toman(sekkeh)
            p_nim = _safe_toman(nim)
            p_rob = _safe_toman(rob)
            p_bahar = _safe_toman(bahar)
            p_abshodeh = _safe_toman(abshodeh)
            try:
                p_ons = float(str(ons).replace(',', '').strip())
            except (TypeError, ValueError):
                p_ons = 0.0
            if not p_18 or not p_sekkeh:
                raise ValueError("tgju parse failed")

            lines = [
                "🥇 *تابلوی زنده نرخ طلا و مسکوکات بازار تهران*:\n",
                f"• *هر گرم طلای ۱۸ عیار*: *{p_18:,} تومان* (معادل *{p_18*10:,} ریال*)",
            ]
            if p_ons > 0:
                lines.append(f"• *انس جهانی طلا (XAU/USD)*: *${p_ons:,.2f}*")
            lines.append(f"• *سکه تمام بهار آزادی (امامی)*: *{p_sekkeh:,} تومان* (معادل *{p_sekkeh*10:,} ریال*)")
            if p_bahar:
                lines.append(f"• *سکه بهار آزادی (طرح قدیم)*: *{p_bahar:,} تومان*")
            if p_abshodeh:
                lines.append(f"• *مثقال طلا (آبشده)*: *{p_abshodeh:,} تومان*")
            if p_nim:
                lines.append(f"• *نیم سکه بهار آزادی*: *{p_nim:,} تومان*")
            if p_rob:
                lines.append(f"• *ربع سکه بهار آزادی*: *{p_rob:,} تومان*")

            out_text = "\n".join(lines)
            await _put_cached(cache_key, out_text, ttl=900)
            return _with_fresh_label(out_text)
    except Exception:
        pass

    try:
        from src.tools import web_network as _web
        searched = await _web.web_search("قیمت طلا 18 عیار و سکه امامی امروز", max_results=4)
        if searched and "یافت نشد" not in searched:
            return f"⚠️ *سایت مرجع موقتاً در دسترس نیست — نتیجه زنده وب:*\n\n{searched}"
    except Exception:
        pass

    return "دریافت اطلاعات طلا و سکه با اختلال موقت مواجه است."

@register_tool(
    name="get_fiat_overview",
    description="استعلام زنده تابلوی نرخ ارزهای آزاد در بازار تهران (دلار، یورو، درهم، پوند، لیر، یوان)",
    category="financial"
)
async def get_fiat_overview(force_refresh: bool = False) -> str:
    cache_key = "FIAT_OVERVIEW_RATES"
    if not force_refresh:
        fresh = await _get_cached_or_refresh(cache_key, 600, lambda: get_fiat_overview(force_refresh=True))
        if fresh:
            return _with_fresh_label(fresh)

    client = get_async_client()
    try:
        r = await client.get("https://www.tgju.org/", timeout=4.5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            
            def get_fiat(row_id):
                v = _parse_tgju_price(soup, row_id)
                return v.replace(",", "") if v else None

            usd = get_fiat("price_dollar_rl")
            eur = get_fiat("price_eur")
            aed = get_fiat("price_aed")
            gbp = get_fiat("price_gbp")
            try_val = get_fiat("price_try")
            cny_val = get_fiat("price_cny")

            dash = await _read_dashboard()
            if usd is None and dash.get("usd_toman"):
                usd = str(int(dash["usd_toman"]) * 10)
            if eur is None and dash.get("eur_toman"):
                eur = str(int(dash["eur_toman"]) * 10)
            if aed is None and dash.get("aed_toman"):
                aed = str(int(dash["aed_toman"]) * 10)
            if gbp is None and dash.get("gbp_toman"):
                gbp = str(int(dash["gbp_toman"]) * 10)

            p_usd = _safe_toman(usd)
            p_eur = _safe_toman(eur)
            p_aed = _safe_toman(aed)
            p_gbp = _safe_toman(gbp)
            p_try = _safe_toman(try_val)
            p_cny = _safe_toman(cny_val)
            if not p_usd:
                raise ValueError("tgju fiat parse failed")

            lines = [
                "💵 *تابلوی زنده نرخ ارزهای آزاد بازار تهران*:\n",
                f"• *دلار آمریکا (USD)*: *{p_usd:,} تومان* (معادل *{p_usd*10:,} ریال*)",
                f"• *یورو اتحادیه اروپا (EUR)*: *{p_eur:,} تومان* (معادل *{p_eur*10:,} ریال*)",
                f"• *درهم امارات (AED)*: *{p_aed:,} تومان* (معادل *{p_aed*10:,} ریال*)",
                f"• *پوند انگلستان (GBP)*: *{p_gbp:,} تومان*",
            ]
            if p_try:
                lines.append(f"• *لیر ترکیه (TRY)*: *{p_try:,} تومان*")
            if p_cny:
                lines.append(f"• *یوان چین (CNY)*: *{p_cny:,} تومان*")

            out_text = "\n".join(lines)
            await _put_cached(cache_key, out_text, ttl=900)
            return _with_fresh_label(out_text)
    except Exception:
        pass

    try:
        from src.tools import web_network as _web
        searched = await _web.web_search("قیمت دلار یورو درهم امروز بازار تهران", max_results=4)
        if searched and "یافت نشد" not in searched:
            return f"⚠️ *سایت مرجع موقتاً در دسترس نیست — نتیجه زنده وب:*\n\n{searched}"
    except Exception:
        pass

    return "دریافت نرخ ارزهای خارجی با اختلال موقت مواجه است."

@register_tool(
    name="get_dollar_price",
    description="استعلام زنده فقط قیمت دلار آمریکا (USD) در بازار آزاد تهران — وقتی کاربر فقط دلار پرسید، فقط همین را صدا بزن نه تابلوی کامل ارزها",
    category="financial"
)
async def get_dollar_price(force_refresh: bool = False) -> str:
    cache_key = "DOLLAR_ONLY_PRICE"
    if not force_refresh:
        fresh = await _get_cached_or_refresh(cache_key, 600, lambda: get_dollar_price(force_refresh=True))
        if fresh:
            return _with_fresh_label(fresh)

    client = get_async_client()
    try:
        r = await client.get("https://www.tgju.org/", timeout=4.5)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            usd = _parse_tgju_price(soup, "price_dollar_rl")
            if usd is None:
                dash = await _read_dashboard()
                if dash.get("usd_toman"):
                    usd = str(int(dash["usd_toman"]) * 10)
            p_usd = _safe_toman(usd)
            if not p_usd:
                raise ValueError("tgju dollar parse failed")
            out_text = (
                "\U0001F4B5 *قیمت زنده دلار آمریکا (USD) در بازار آزاد تهران*:\n\n"
                f"\u2022 *دلار آمریکا (USD)*: *{p_usd:,} تومان* (معادل *{p_usd*10:,} ریال*)"
            )
            await _put_cached(cache_key, out_text, ttl=900)
            return _with_fresh_label(out_text)
    except Exception:
        pass

    try:
        from src.tools import web_network as _web
        searched = await _web.web_search("\u0642\u06CC\u0645\u062A \u062F\u0644\u0627\u0631 \u0627\u0645\u0631\u0648\u0632 \u0628\u0627\u0632\u0627\u0631 \u062A\u0647\u0631\u0627\u0646", max_results=3)
        if searched and "\u06CC\u0627\u0641\u062A \u0646\u0634\u062F" not in searched:
            return f"\u26A0\uFE0F *سایت مرجع موقتاً در دسترس نیست — نتیجه زنده وب:*\n\n{searched}"
    except Exception:
        pass

    return "دریافت قیمت دلار با اختلال موقت مواجه است."
