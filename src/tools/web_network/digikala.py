import urllib.parse
import time
import re
import logging
from typing import Dict, Tuple
from src.core.http import shared_client_ctx
from src.tools.registry import register_tool
from src.core import database

logger = logging.getLogger(__name__)

_L1_DIGIKALA_CACHE: Dict[str, Tuple[float, str]] = {}
_L1_TTL_SECONDS = 900.0

def clean_digikala_query(query: str) -> str:
    cleaned = (query or "").strip()
    noise_words = [
        "قیمت", "نرخ", "خرید", "فروش", "دیجیکالا", "دیجی کالا", "digikala",
        "چنده", "چند است", "مشخصات", "ارزان ترین", "بهترین", "اصل", "اورجینال",
        "رو چک کن", "چک کن", "استعلام", "ببین", "لطفا", "لطفاً"
    ]
    for w in noise_words:
        cleaned = re.sub(rf"\b{re.escape(w)}\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if len(cleaned) >= 2 else (query or "").strip()

@register_tool(
    name="digikala_search",
    description="جستجوی زنده، فوق‌سریع و هوشمند کالا، استعلام قیمت، تخفیف‌های شگفت‌انگیز، فروشنده، امتیاز و لینک خرید مستقیم محصولات از فروشگاه دیجی‌کالا (Digikala)",
    category="search"
)
async def digikala_search(query: str, max_results: int = 5) -> str:
    """
    :param query: نام محصول، برند یا مدل کالا برای استعلام در دیجی‌کالا
    :param max_results: حداکثر تعداد اقلام پیشنهادی (۱ تا ۱۰)
    """
    raw_q = (query or "").strip()
    if not raw_q:
        return "نام کالایی برای جستجو در دیجی‌کالا مشخص نشده است."

    clean_q = clean_digikala_query(raw_q)
    cache_key = "DK_" + clean_q.lower().replace(" ", "_")

    now = time.time()
    if cache_key in _L1_DIGIKALA_CACHE:
        ts, val = _L1_DIGIKALA_CACHE[cache_key]
        if (now - ts) < _L1_TTL_SECONDS:
            return val
    # Bounded L1: drop oldest 50 entries past 400 so long uptimes never leak RAM.
    if len(_L1_DIGIKALA_CACHE) >= 400:
        for _k in list(_L1_DIGIKALA_CACHE.keys())[:50]:
            _L1_DIGIKALA_CACHE.pop(_k, None)

    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        _L1_DIGIKALA_CACHE[cache_key] = (now, cached)
        return cached

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.digikala.com/",
        "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    # Primary & Secondary Digikala Endpoints
    endpoints = [
        f"https://api.digikala.com/v1/search/?q={urllib.parse.quote(clean_q)}",
        f"https://api.digikala.com/v2/search/?q={urllib.parse.quote(clean_q)}",
    ]

    products = []
    try:
        async with shared_client_ctx("web") as client:
            for ep_url in endpoints:
                try:
                    r = await client.get(ep_url, headers=headers, follow_redirects=True, timeout=8.0)
                    if r.status_code == 200:
                        data = r.json().get("data", {})
                        p_list = data.get("products", [])
                        if p_list:
                            products = p_list
                            break
                except Exception as inner_e:
                    logger.debug(f"Digikala endpoint {ep_url} failed: {inner_e}")
                    continue

            if products:
                lines = [f"🛍 *نتایج استعلام زنده و موجودی دیجی‌کالا برای «{clean_q}»:*\n"]
                count = 0
                for p in products:
                    if count >= max(1, min(10, max_results)):
                        break
                    title = (p.get("title_fa") or p.get("title_en") or "محصول").strip()
                    if not p.get("id"):
                        continue
                    pid = str(p.get("id"))
                    product_url = f"https://www.digikala.com/product/dkp-{pid}"

                    var_info = p.get("default_variant") or {}
                    price_info = var_info.get("price") or {}
                    sp = price_info.get("selling_price", 0)
                    rrp = price_info.get("rrp_price", 0)
                    discount = price_info.get("discount_percent", 0)
                    is_incredible = price_info.get("is_incredible", False) or price_info.get("is_promotion", False)

                    # Seller
                    seller_info = var_info.get("seller") or p.get("seller") or {}
                    seller_title = seller_info.get("title", "")
                    seller_tag = f" | فروشنده: _{seller_title}_" if seller_title else ""

                    # Stock status & price
                    status = p.get("status", "")
                    if sp and sp > 0:
                        toman = sp // 10
                        orig_toman = (rrp // 10) if (rrp and rrp > sp) else 0
                        badge = "🔥 *شگفت‌انگیز* | " if is_incredible else ""
                        price_line = f"• {badge}*قیمت*: *{toman:,} تومان*"
                        if discount and discount > 0 and orig_toman:
                            price_line += f" (تخفیف: *{discount}%* | قبل: ~~{orig_toman:,} تومان~~)"
                        price_line += f"{seller_tag}"
                    else:
                        stock_label = "ناموجود در انبار" if status == "out_of_stock" else "نامشخص / تمام شده"
                        price_line = f"• *وضعیت*: `🔴 {stock_label}`"

                    # Rating and reviews
                    rate_info = p.get("rating") or {}
                    rate_val = rate_info.get("rate", 0)
                    rate_count = rate_info.get("count", 0)
                    rate_str = ""
                    if rate_val:
                        stars = f" ⭐ {rate_val / 20:.1f}/5"
                        count_text = f" ({rate_count:,} نظر)" if rate_count else ""
                        rate_str = f"{stars}{count_text}"

                    lines.append(
                        f"{count + 1}. *{title}*{rate_str}\n"
                        f"   {price_line}\n"
                        f"   🔗 [مشاهده و خرید مستقیم در دیجی‌کالا]({product_url})\n"
                    )
                    count += 1

                if count > 0:
                    out_text = "\n".join(lines)
                    _L1_DIGIKALA_CACHE[cache_key] = (now, out_text)
                    await database.kv_set_cache_async(cache_key, out_text, expiration_ttl=900)
                    return out_text
    except Exception as e:
        logger.debug(f"Digikala API error: {e}")

    # Seamless Fallback: Live Web Search targeted to Digikala products
    try:
        from src.tools.web_network import web_search
        searched = await web_search(f"site:digikala.com/product {clean_q}", max_results=4)
        if searched and "یافت نشد" not in searched:
            fallback_text = f"🛍 *نتایج محصولات دیجی‌کالا (از وب) برای «{clean_q}»:*\n\n{searched}"
            _L1_DIGIKALA_CACHE[cache_key] = (now, fallback_text)
            return fallback_text
    except Exception:
        pass

    return f"هیچ کالایی منطبق با «{clean_q}» در فروشگاه دیجی‌کالا یافت نشد یا سرویس موقتاً پاسخ نداد."
