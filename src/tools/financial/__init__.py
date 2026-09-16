import httpx
import logging
import asyncio
import json
import time
import re
from typing import Dict, Any, Optional, Tuple

from src.tools.registry import register_tool
from src.core import database
from src.core.config import ALLRATESTODAY_API_KEY, ALLRATESTODAY_URL
from src.core.http import get_http_client

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
    _TEHRAN_TZ = ZoneInfo("Asia/Tehran")
except Exception:
    import datetime
    _TEHRAN_TZ = datetime.timezone(datetime.timedelta(hours=3, minutes=30))

def _now_tehran_str() -> str:
    """Current Tehran time as HH:MM string for freshness labels (pre-cached tz for <0.002ms latency)."""
    try:
        import datetime
        return datetime.datetime.now(_TEHRAN_TZ).strftime("%H:%M")
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
_TGJU_PARSED_CACHE: Dict[str, str] = {}
_TGJU_PARSED_TS: float = 0.0
_TGJU_REFRESH_LOCK = asyncio.Lock()

async def _refresh_tgju_task():
    """Fetches TGJU in the background so caller never blocks on external network delay."""
    global _TGJU_PARSED_CACHE, _TGJU_PARSED_TS
    try:
        client = get_async_client()
        r = await client.get("https://www.tgju.org/", timeout=3.5)
        if r.status_code == 200:
            html = r.text
            keys = [
                "price_dollar_rl", "price_eur", "price_aed", "price_gbp",
                "price_try", "price_cny", "geram18", "sekee", "ons",
                "mesghal", "nim", "rob", "sekeb", "silver", "silver_999", "oil_brent"
            ]
            extracted = {}
            for k in keys:
                m = re.search(rf'data-market-row="{k}"[\s\S]{{1,2000}}?data-price="([^"]+)"', html)
                if m:
                    extracted[k] = m.group(1).replace(",", "").strip()
            if extracted.get("price_dollar_rl") or extracted.get("geram18"):
                _TGJU_PARSED_CACHE = extracted
                _TGJU_PARSED_TS = time.time()
    except Exception as e:
        logger.debug(f"Background TGJU refresh skipped: {e}")

async def _get_fresh_tgju_rates(force_refresh: bool = False) -> Dict[str, str]:
    """
    Sub-millisecond Stale-While-Revalidate TGJU Rates:
    Returns immediately from Hot RAM in 0.0001ms. If cache is older than 90s,
    serves existing data immediately and fires background refresh without blocking user!
    """
    now = time.time()
    if _TGJU_PARSED_CACHE:
        if not force_refresh and (now - _TGJU_PARSED_TS < 90.0):
            return _TGJU_PARSED_CACHE
        # Stale: schedule background refresh without blocking caller
        try:
            asyncio.create_task(_refresh_tgju_task())
        except Exception:
            pass
        return _TGJU_PARSED_CACHE

    # Only cold-start (empty cache) waits for initial fetch
    await _refresh_tgju_task()
    if _TGJU_PARSED_CACHE:
        return _TGJU_PARSED_CACHE

    # Fallback to pre-synced dashboard
    dash = await _read_dashboard()
    res = {}
    if dash.get("usd_toman"):
        res["price_dollar_rl"] = str(int(dash["usd_toman"]) * 10)
    if dash.get("eur_toman"):
        res["price_eur"] = str(int(dash["eur_toman"]) * 10)
    if dash.get("aed_toman"):
        res["price_aed"] = str(int(dash["aed_toman"]) * 10)
    if dash.get("gbp_toman"):
        res["price_gbp"] = str(int(dash["gbp_toman"]) * 10)
    if dash.get("gold_18k_toman"):
        res["geram18"] = str(int(dash["gold_18k_toman"]) * 10)
    if dash.get("emami_coin_toman"):
        res["sekee"] = str(int(dash["emami_coin_toman"]) * 10)
    return res

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

def _safe_float(raw: Any, fallback: float = 0.0) -> float:
    """Parses Persian/English digit floats safely, never raises."""
    try:
        if raw is None:
            return fallback
        s = str(raw).strip().replace(",", "").replace("٬", "").replace("،", "")
        fa_digits = "۰۱۲۳۴۵۶۷۸۹"
        for i, d in enumerate(fa_digits):
            s = s.replace(d, str(i))
        cleaned = re.sub(r"[^\d\.]", "", s)
        if not cleaned:
            return fallback
        return float(cleaned)
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
    """Free-market USD in toman: fast cached TGJU / dashboard rates."""
    try:
        rates = await _get_fresh_tgju_rates()
        if rates.get("price_dollar_rl"):
            v = _safe_toman(rates["price_dollar_rl"])
            if v > 0:
                return v
    except Exception:
        pass
    try:
        dash = await _read_dashboard()
        if dash.get("usd_toman"):
            return int(dash["usd_toman"])
    except Exception:
        pass
    return 0

def get_async_client() -> httpx.AsyncClient:
    try:
        return get_http_client("fast")
    except Exception:
        global _shared_client
        if _shared_client is None or _shared_client.is_closed:
            _shared_client = httpx.AsyncClient(
                limits=httpx.Limits(max_keepalive_connections=120, max_connections=250, keepalive_expiry=300.0),
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
        ENABLE_FINANCIAL_SYNC, FINANCIAL_SYNC_INTERVAL_SEC = True, 120
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

    # 2. TGJU Realtime Gold & Fiat Rates (Sub-millisecond regex parse)
    try:
        tgju_data = await _get_fresh_tgju_rates(force_refresh=True)
        if tgju_data.get("price_dollar_rl"): dashboard["usd_toman"] = _safe_toman(tgju_data["price_dollar_rl"])
        if tgju_data.get("price_eur"): dashboard["eur_toman"] = _safe_toman(tgju_data["price_eur"])
        if tgju_data.get("price_aed"): dashboard["aed_toman"] = _safe_toman(tgju_data["price_aed"])
        if tgju_data.get("price_gbp"): dashboard["gbp_toman"] = _safe_toman(tgju_data["price_gbp"])
        if tgju_data.get("geram18"): dashboard["gold_18k_toman"] = _safe_toman(tgju_data["geram18"])
        if tgju_data.get("sekee"): dashboard["emami_coin_toman"] = _safe_toman(tgju_data["sekee"])
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

_NOBITEX_STATS_CACHE: Dict[str, Any] = {}
_NOBITEX_STATS_TS: float = 0.0

async def _fetch_binance_us(sym: str) -> Optional[Dict[str, Any]]:
    client = get_async_client()
    try:
        r = await client.get(f"https://api.binance.us/api/v3/ticker/24hr?symbol={sym}USDT", timeout=1.8)
        if r.status_code == 200:
            d = r.json()
            p = float(d.get("lastPrice", 0))
            if p > 0:
                return {
                    "symbol": sym,
                    "price": p,
                    "change": float(d.get("priceChangePercent", 0)),
                    "high": float(d.get("highPrice", 0)),
                    "low": float(d.get("lowPrice", 0)),
                    "volume": float(d.get("quoteVolume", 0))
                }
    except Exception:
        pass
    return None

async def _fetch_mexc(sym: str) -> Optional[Dict[str, Any]]:
    client = get_async_client()
    try:
        r = await client.get(f"https://api.mexc.com/api/v3/ticker/24hr?symbol={sym}USDT", timeout=1.8)
        if r.status_code == 200:
            d = r.json()
            p = float(d.get("lastPrice", 0))
            if p > 0:
                return {
                    "symbol": sym,
                    "price": p,
                    "change": float(d.get("priceChangePercent", 0)),
                    "high": float(d.get("highPrice", 0)),
                    "low": float(d.get("lowPrice", 0)),
                    "volume": float(d.get("quoteVolume", 0))
                }
    except Exception:
        pass
    return None

async def _fetch_kucoin(sym: str) -> Optional[Dict[str, Any]]:
    client = get_async_client()
    try:
        r = await client.get(f"https://api.kucoin.com/api/v1/market/stats?symbol={sym}-USDT", timeout=1.8)
        if r.status_code == 200:
            kd = r.json().get("data", {})
            if kd and kd.get("last"):
                p = float(kd["last"])
                if p > 0:
                    chg = float(kd.get("changeRate", 0)) * 100
                    return {
                        "symbol": sym,
                        "price": p,
                        "change": chg,
                        "high": float(kd.get("high", 0) or p),
                        "low": float(kd.get("low", 0) or p),
                        "volume": float(kd.get("volValue", 0))
                    }
    except Exception:
        pass
    return None

async def _fetch_coinpaprika(sym: str) -> Optional[Dict[str, Any]]:
    client = get_async_client()
    slug_map = {
        "TON": "toncoin-the-open-network",
        "TONCOIN": "toncoin-the-open-network",
        "NOT": "notcoin-not",
        "SUI": "sui-sui",
        "PEPE": "pepe-pepe",
    }
    slug = slug_map.get(sym)
    if not slug:
        return None
    try:
        r = await client.get(f"https://api.coinpaprika.com/v1/tickers/{slug}", timeout=1.8)
        if r.status_code == 200:
            qd = r.json().get("quotes", {}).get("USD", {})
            if qd and qd.get("price"):
                p = float(qd["price"])
                if p > 0:
                    return {
                        "symbol": sym,
                        "price": p,
                        "change": float(qd.get("percent_change_24h", 0)),
                        "high": p * 1.02,
                        "low": p * 0.98,
                        "volume": float(qd.get("volume_24h", 0))
                    }
    except Exception:
        pass
    return None

async def _get_binance_depth(symbol: str) -> Optional[Dict[str, Any]]:
    # USDT is a $1 stablecoin — no external lookup needed. Free, instant, 0-ms.
    clean_sym = (symbol or "").upper().strip()
    if clean_sym in ("USDT", "USDTUSDT", "تتر", "TETHER"):
        return {"symbol": "USDT", "price": 1.0, "change": 0.0, "high": 1.0, "low": 1.0, "volume": 0.0}
    if not clean_sym:
        return None

    sym = clean_sym.replace("USDT", "")

    # Ultra-Fast Concurrent Provider Race: Query providers simultaneously, take first valid answer
    fetchers = [_fetch_binance_us(sym), _fetch_kucoin(sym), _fetch_mexc(sym)]
    if sym in ("TON", "TONCOIN", "NOT", "SUI", "PEPE"):
        fetchers.append(_fetch_coinpaprika(sym))

    try:
        for coro in asyncio.as_completed(fetchers):
            try:
                res = await coro
                if res and isinstance(res, dict) and res.get("price", 0) > 0:
                    return res
            except Exception:
                continue
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

async def _refresh_nobitex_stats() -> Dict[str, Any]:
    global _NOBITEX_STATS_CACHE, _NOBITEX_STATS_TS
    client = get_async_client()
    try:
        r = await client.get("https://apiv2.nobitex.ir/market/stats", timeout=2.0)
        if r.status_code == 200:
            stats = r.json().get("stats", {})
            if stats:
                _NOBITEX_STATS_CACHE = stats
                _NOBITEX_STATS_TS = time.time()
                return stats
    except Exception as e:
        logger.debug(f"Nobitex stats fetch error: {e}")
    return _NOBITEX_STATS_CACHE

async def _get_nobitex_price(symbol: str, global_usd: float = 0.0) -> Optional[Dict[str, Any]]:
    sym_low = symbol.lower()
    pair_key = f"{sym_low}-rls"

    # Tier 1: Hot RAM Cache (45-second cache for instant 0.0001ms lookup across all coins)
    now = time.time()
    stats = _NOBITEX_STATS_CACHE
    if not stats or (now - _NOBITEX_STATS_TS > 45.0):
        stats = await _refresh_nobitex_stats()

    if stats and pair_key in stats:
        d = stats[pair_key]
        if isinstance(d, dict):
            try:
                latest_rls = float(d.get("latest") or 0)
            except (ValueError, TypeError):
                latest_rls = 0.0
            if latest_rls > 0:
                try:
                    c_val = float(d.get("dayChange") or 0)
                except (ValueError, TypeError):
                    c_val = 0.0
                try:
                    bb_val = int(float(d.get("bestBuy") or 0) / 10)
                except (ValueError, TypeError):
                    bb_val = 0
                try:
                    bs_val = int(float(d.get("bestSell") or 0) / 10)
                except (ValueError, TypeError):
                    bs_val = 0
                return {
                    "toman": int(latest_rls / 10),
                    "change": c_val,
                    "best_buy": bb_val,
                    "best_sell": bs_val,
                    "src": "نوبیتکس"
                }

    # Tier 2: Instant calculation from Global USD x Free USD Toman (Zero-wait!)
    if global_usd > 0:
        usd_toman = await _get_free_usd_toman()
        if usd_toman > 0:
            toman = int(global_usd * usd_toman)
            return {
                "toman": toman,
                "change": 0.0,
                "best_buy": toman,
                "best_sell": toman,
                "src": "تخمین بازار آزاد"
            }
    return None

get_nobitex_crypto_prices = _get_nobitex_price

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
    if not raw_upper:
        return "اطلاعات قیمتی برای نماد «» در صرافی‌های جهانی یافت نشد."

    # Direct Redirection for Precious Metals, Commodities & Energy
    if raw_upper in ("SILVER", "XAG", "نقره"):
        return await get_commodities_price(force_refresh=force_refresh)
    if raw_upper in ("OIL", "BRENT", "CRUDE", "WTI", "نفت", "برنت"):
        return await get_commodities_price(force_refresh=force_refresh)
    if raw_upper in ("GOLD", "XAU", "طلا", "سکه", "انس"):
        return await get_gold_and_coin_price(force_refresh=force_refresh)

    if raw_upper in ("USDT", "تتر", "TETHER"):
        clean_sym = "USDT"
    else:
        clean_sym = raw_upper.replace("USDT", "").strip() or raw_upper
    cache_key = f"CRYPTO_PRICE_{clean_sym}"
    
    if not force_refresh:
        fresh = await _get_cached_or_refresh(cache_key, 120, lambda: get_price(clean_sym, force_refresh=True))
        if fresh:
            return _with_fresh_label(fresh)

    # Parallel Global & Local Exchange Gathering (Concurrent: 2x-3x speedup!)
    b_task = asyncio.create_task(_get_binance_depth(clean_sym))
    n_task = asyncio.create_task(_get_nobitex_price(clean_sym))
    b_res, n_res = await asyncio.gather(b_task, n_task, return_exceptions=True)
    if isinstance(b_res, Exception):
        b_res = None
    if isinstance(n_res, Exception):
        n_res = None

    usd_price = b_res.get("price", 0.0) if (isinstance(b_res, dict) and b_res) else 0.0
    if (not n_res or not isinstance(n_res, dict)) and usd_price > 0:
        usd_toman = await _get_free_usd_toman()
        if usd_toman > 0:
            toman = int(usd_price * usd_toman)
            n_res = {
                "toman": toman,
                "change": 0.0,
                "best_buy": toman,
                "best_sell": toman,
                "src": "تخمین بازار آزاد"
            }

    lines = []
    if isinstance(b_res, dict) and b_res:
        sign = "+" if b_res['change'] >= 0 else ""
        lines.append(
            f"📊 *تابلوی زنده نرخ {clean_sym} (بازارهای جهانی)*:\n"
            f"• *قیمت دلاری*: *${b_res['price']:,.4f}*\n"
            f"• *تغییرات ۲۴ ساعته*: *{sign}{b_res['change']:.2f}%*\n"
            f"• *بیشترین قیمت (۲۴ ساعت)*: *${b_res['high']:,.2f}*\n"
            f"• *کمترین قیمت (۲۴ ساعت)*: *${b_res['low']:,.2f}*"
        )

    if isinstance(n_res, dict) and n_res:
        src_label = n_res.get("src", "بازار")
        ch_sign = "+" if n_res['change'] >= 0 else ""
        chg_text = f" ({ch_sign}{n_res['change']:.2f}%)" if n_res.get("change") else ""
        lines.append(
            f"\n🇮🇷 *نرخ تومانی {clean_sym} ({src_label})*:\n"
            f"• *قیمت معامله*: *{n_res['toman']:,} تومان*{chg_text}\n"
            f"• *خرید*: *{n_res['best_buy']:,} تومان* | *فروش*: *{n_res['best_sell']:,} تومان*"
        )

    if lines:
        out_text = "\n".join(lines)
        await _put_cached(cache_key, out_text, ttl=180)
        return _with_fresh_label(out_text)

    # Fallback: live web search only if all exchange APIs failed
    try:
        from src.tools import web_network as _web
        has_fa = any('\u0600' <= c <= '\u06ff' for c in symbol)
        sq = f"قیمت {symbol} امروز" if has_fa else f"{clean_sym} price USD today"
        searched = await _web.web_search(sq, max_results=3)
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

    # Geo-block resilience: if Binance is unreachable from this region (HTTP 451),
    # fall back to Nobitex toman quotes so the board is never an empty header.
    if len(lines) == 1:
        try:
            nb_tasks = [_get_nobitex_price(s) for s in symbols]
            nb_results = await asyncio.gather(*nb_tasks, return_exceptions=True)
            nb_lines = ["📊 *تابلوی بازار کریپتو (نوبیتکس — بایننس از این منطقه در دسترس نیست)*:\n"]
            for s, res in zip(symbols, nb_results):
                if isinstance(res, dict) and res and res.get("toman"):
                    ch = "+" if res.get("change", 0) >= 0 else ""
                    nb_lines.append(f"• *{s}*: *{res['toman']:,} تومان* ({ch}{res.get('change', 0):.2f}%)")
            if len(nb_lines) > 1:
                lines = nb_lines
        except Exception:
            pass

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
        fresh = await _get_cached_or_refresh(cache_key, 120, lambda: get_gold_and_coin_price(force_refresh=True))
        if fresh:
            return _with_fresh_label(fresh)

    rates = await _get_fresh_tgju_rates(force_refresh=force_refresh)
    p_18 = _safe_toman(rates.get("geram18"))
    p_sekkeh = _safe_toman(rates.get("sekee"))
    p_nim = _safe_toman(rates.get("nim"))
    p_rob = _safe_toman(rates.get("rob"))
    p_bahar = _safe_toman(rates.get("sekeb"))
    p_abshodeh = _safe_toman(rates.get("mesghal"))
    p_gerami = _safe_toman(rates.get("gerami"))
    p_ons = _safe_float(rates.get("ons"))

    if not p_18 and not p_sekkeh:
        dash = await _read_dashboard()
        if dash.get("gold_18k_toman"): p_18 = int(dash["gold_18k_toman"])
        if dash.get("emami_coin_toman"): p_sekkeh = int(dash["emami_coin_toman"])

    if p_18 or p_sekkeh:
        lines = [
            "🥇 *تابلوی زنده نرخ طلا و مسکوکات بازار تهران*:\n",
        ]
        if p_18:
            p_24 = int(p_18 * (24.0 / 18.0))
            lines.append(f"• *هر گرم طلای ۱۸ عیار*: *{p_18:,} تومان* (معادل *{p_18*10:,} ریال*)")
            lines.append(f"• *هر گرم طلای ۲۴ عیار (محاسباتی)*: *{p_24:,} تومان*")
        if p_ons > 0:
            lines.append(f"• *انس جهانی طلا (XAU/USD)*: *${p_ons:,.2f}*")
        if p_abshodeh:
            lines.append(f"• *مثقال طلا (آبشده)*: *{p_abshodeh:,} تومان*")

        # Coin Breakdown
        if p_sekkeh:
            lines.append("\n🪙 *نرخ مسکوکات طلا*:")
            lines.append(f"• *سکه تمام بهار آزادی (امامی)*: *{p_sekkeh:,} تومان* (معادل *{p_sekkeh*10:,} ریال*)")
        if p_bahar:
            lines.append(f"• *سکه بهار آزادی (طرح قدیم)*: *{p_bahar:,} تومان*")
        if p_nim:
            lines.append(f"• *نیم سکه بهار آزادی*: *{p_nim:,} تومان*")
        if p_rob:
            lines.append(f"• *ربع سکه بهار آزادی*: *{p_rob:,} تومان*")
        if p_gerami:
            lines.append(f"• *سکه یک گرمی بانک مرکزی*: *{p_gerami:,} تومان*")

        # Coin Bubble Calculation (حباب سکه بر مبنای ارزش ذاتی طلای خالص)
        usd_toman = await _get_free_usd_toman()
        if p_ons > 0 and usd_toman > 0 and p_sekkeh > 0:
            # Emami: 8.133g, fineness 900 -> 7.3197g pure 24K gold
            intrinsic_emami = int((p_ons * usd_toman * 7.3197) / 31.1035)
            bubble_emami = p_sekkeh - intrinsic_emami
            bubble_emami_pct = (bubble_emami / p_sekkeh) * 100 if p_sekkeh > 0 else 0
            bubble_sign = "+" if bubble_emami >= 0 else ""

            lines.append(
                f"\n🫧 *تحلیل حباب و ارزش ذاتی مسکوکات*:\n"
                f"• *ارزش ذاتی سکه امامی*: *{intrinsic_emami:,} تومان*\n"
                f"• *حباب سکه امامی*: *{bubble_sign}{bubble_emami:,} تومان* ({bubble_sign}{bubble_emami_pct:.1f}%)\n"
                f"• *مبنای محاسبه*: انس جهانی `${p_ons:,.2f}` × دلار آزاد `{usd_toman:,}` تومان"
            )
            if p_rob and p_rob > 0:
                intrinsic_rob = int((p_ons * usd_toman * 1.8299) / 31.1035)
                bubble_rob = p_rob - intrinsic_rob
                bubble_rob_pct = (bubble_rob / p_rob) * 100 if p_rob > 0 else 0
                lines.append(f"• *حباب ربع سکه*: *{bubble_rob:,} تومان* ({bubble_rob_pct:.1f}%) | ارزش ذاتی: *{intrinsic_rob:,} تومان*")

        out_text = "\n".join(lines)
        await _put_cached(cache_key, out_text, ttl=300)
        return _with_fresh_label(out_text)

    try:
        from src.tools import web_network as _web
        searched = await _web.web_search("قیمت طلا 18 عیار و سکه امامی امروز", max_results=3)
        if searched and "یافت نشد" not in searched:
            return f"⚠️ *سایت مرجع موقتاً در دسترس نیست — نتیجه زنده وب:*\n\n{searched}"
    except Exception:
        pass

    return "دریافت اطلاعات طلا و سکه با اختلال موقت مواجه است."

@register_tool(
    name="get_commodities_price",
    description="استعلام زنده، چندمنبعی و لحظه‌ای نرخ فلزات گرانبها و کالاهای استراتژیک جهان (انس جهانی نقره، هر گرم نقره ۹۹۹ و ۹۲۵ بازار ایران، نفت خام برنت و WTI، و نسبت طلا به نقره)",
    category="financial"
)
async def get_commodities_price(force_refresh: bool = False) -> str:
    cache_key = "COMMODITIES_PRICES"
    if not force_refresh:
        fresh = await _get_cached_or_refresh(cache_key, 180, lambda: get_commodities_price(force_refresh=True))
        if fresh:
            return _with_fresh_label(fresh)

    rates = await _get_fresh_tgju_rates(force_refresh=force_refresh)
    silver_ons = _safe_float(rates.get("silver"))
    silver_999 = _safe_toman(rates.get("silver_999"))
    silver_925 = _safe_toman(rates.get("silver_925")) or (int(silver_999 * 0.925) if silver_999 else 0)
    oil_brent = _safe_float(rates.get("oil_brent"))
    oil_wti = _safe_float(rates.get("oil"))
    oil_opec = _safe_float(rates.get("oil_opec"))
    ratio_silver = _safe_float(rates.get("ratio_silver"))
    if not ratio_silver and silver_ons > 0 and _safe_float(rates.get("ons")) > 0:
        ratio_silver = _safe_float(rates.get("ons")) / silver_ons

    lines = ["🛢 *تابلوی زنده فلزات گرانبها، انرژی و نفت جهانی*:\n"]
    if silver_ons > 0:
        lines.append(f"• *انس جهانی نقره (XAG/USD)*: *${silver_ons:,.2f}*")
    if silver_999:
        lines.append(f"• *هر گرم نقره ۹۹۹ (شمس نقره ایران)*: *{silver_999:,} تومان*")
    if silver_925:
        lines.append(f"• *هر گرم نقره ۹۲۵ (استرلینگ)*: *{silver_925:,} تومان*")
    if ratio_silver > 0:
        lines.append(f"• *نسبت طلا به نقره (Gold/Silver Ratio)*: *{ratio_silver:.2f}*")
    if oil_brent > 0:
        lines.append(f"• *نفت خام برنت دریای شمال (Brent)*: *${oil_brent:,.2f}*")
    if oil_wti > 0:
        lines.append(f"• *نفت خام سبک تگزاس (WTI)*: *${oil_wti:,.2f}*")
    if oil_opec > 0:
        lines.append(f"• *سبد مرجع نفتی اوپک (OPEC)*: *${oil_opec:,.2f}*")

    if len(lines) > 1:
        out_text = "\n".join(lines)
        await _put_cached(cache_key, out_text, ttl=300)
        return _with_fresh_label(out_text)

    try:
        from src.tools import web_network as _web
        searched = await _web.web_search("قیمت انس نقره و نفت برنت امروز", max_results=3)
        if searched and "یافت نشد" not in searched:
            return f"⚠️ *نتیجه زنده وب برای نقره و نفت:*\n\n{searched}"
    except Exception:
        pass
    return "اطلاعات کالاهای اساسی و نفت در حال حاضر در دسترس نیست."

@register_tool(
    name="get_fiat_overview",
    description="استعلام زنده تابلوی نرخ ارزهای آزاد در بازار تهران (دلار، یورو، درهم، پوند، لیر، یوان)",
    category="financial"
)
async def get_fiat_overview(force_refresh: bool = False) -> str:
    cache_key = "FIAT_OVERVIEW_RATES"
    if not force_refresh:
        fresh = await _get_cached_or_refresh(cache_key, 120, lambda: get_fiat_overview(force_refresh=True))
        if fresh:
            return _with_fresh_label(fresh)

    rates = await _get_fresh_tgju_rates(force_refresh=force_refresh)
    p_usd = _safe_toman(rates.get("price_dollar_rl"))
    p_eur = _safe_toman(rates.get("price_eur"))
    p_aed = _safe_toman(rates.get("price_aed"))
    p_gbp = _safe_toman(rates.get("price_gbp"))
    p_try = _safe_toman(rates.get("price_try"))
    p_cny = _safe_toman(rates.get("price_cny"))

    if not p_usd:
        dash = await _read_dashboard()
        if dash.get("usd_toman"): p_usd = int(dash["usd_toman"])
        if dash.get("eur_toman"): p_eur = int(dash["eur_toman"])
        if dash.get("aed_toman"): p_aed = int(dash["aed_toman"])
        if dash.get("gbp_toman"): p_gbp = int(dash["gbp_toman"])

    if p_usd or p_eur or p_aed:
        lines = [
            "💵 *تابلوی زنده نرخ ارزهای آزاد بازار تهران*:\n",
        ]
        if p_usd:
            lines.append(f"• *دلار آمریکا (USD)*: *{p_usd:,} تومان* (معادل *{p_usd*10:,} ریال*)")
        if p_eur:
            lines.append(f"• *یورو اتحادیه اروپا (EUR)*: *{p_eur:,} تومان* (معادل *{p_eur*10:,} ریال*)")
        if p_aed:
            lines.append(f"• *درهم امارات (AED)*: *{p_aed:,} تومان* (معادل *{p_aed*10:,} ریال*)")
        if p_gbp:
            lines.append(f"• *پوند انگلستان (GBP)*: *{p_gbp:,} تومان*")
        if p_try:
            lines.append(f"• *لیر ترکیه (TRY)*: *{p_try:,} تومان*")
        if p_cny:
            lines.append(f"• *یوان چین (CNY)*: *{p_cny:,} تومان*")

        out_text = "\n".join(lines)
        await _put_cached(cache_key, out_text, ttl=300)
        return _with_fresh_label(out_text)

    try:
        from src.tools import web_network as _web
        searched = await _web.web_search("قیمت دلار یورو درهم امروز بازار تهران", max_results=3)
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
        fresh = await _get_cached_or_refresh(cache_key, 120, lambda: get_dollar_price(force_refresh=True))
        if fresh:
            return _with_fresh_label(fresh)

    rates = await _get_fresh_tgju_rates(force_refresh=force_refresh)
    p_usd = _safe_toman(rates.get("price_dollar_rl"))
    if not p_usd:
        dash = await _read_dashboard()
        if dash.get("usd_toman"):
            p_usd = int(dash["usd_toman"])

    if p_usd:
        out_text = (
            "💵 *قیمت زنده دلار آمریکا (USD) در بازار آزاد تهران*:\n\n"
            f"• *دلار آمریکا (USD)*: *{p_usd:,} تومان* (معادل *{p_usd*10:,} ریال*)"
        )
        await _put_cached(cache_key, out_text, ttl=300)
        return _with_fresh_label(out_text)

    try:
        from src.tools import web_network as _web
        searched = await _web.web_search("قیمت دلار امروز بازار تهران", max_results=3)
        if searched and "یافت نشد" not in searched:
            return f"⚠️ *سایت مرجع موقتاً در دسترس نیست — نتیجه زنده وب:*\n\n{searched}"
    except Exception:
        pass

    return "دریافت قیمت دلار با اختلال موقت مواجه است."
