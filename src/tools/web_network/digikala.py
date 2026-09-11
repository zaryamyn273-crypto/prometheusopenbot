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
    description="جستجوی زنده کالا، استعلام قیمت، وضعیت موجودی، تخفیف و لینک خرید مستقیم محصولات از فروشگاه دیجی‌کالا (Digikala)",
    category="search"
)
async def digikala_search(query: str, max_results: int = 5) -> str:
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
        "Accept": "application/json",
        "Referer": "https://www.digikala.com/",
        "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    try:
        async with shared_client_ctx("web") as client:
            encoded_q = urllib.parse.quote(clean_q)
            url = "https://api.digikala.com/v1/search/?q=" + encoded_q
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                data = r.json().get("data", {})
                products = data.get("products", [])
                if not products:
                    return "هیچ کالایی منطبق با «" + clean_q + "» در فروشگاه دیجی‌کالا یافت نشد."

                lines = ["🛍 *نتایج استعلام زنده از فروشگاه دیجی‌کالا برای «" + clean_q + "»:*\n"]
                count = 0
                for p in products:
                    if count >= max(1, min(10, max_results)):
                        break
                    title = p.get("title_fa") or p.get("title_en") or "محصول"
                    if not p.get("id"):
                        continue
                    pid = str(p.get("id"))
                    product_url = "https://www.digikala.com/product/dkp-" + pid

                    var_info = p.get("default_variant") or {}
                    price_info = var_info.get("price") or {}
                    sp = price_info.get("selling_price", 0)
                    rrp = price_info.get("rrp_price", 0)
                    discount = price_info.get("discount_percent", 0)

                    if sp and sp > 0:
                        toman = sp // 10
                        orig_toman = (rrp // 10) if (rrp and rrp > sp) else 0
                        price_line = "• *قیمت*: *" + f"{toman:,}" + " تومان*"
                        if discount and discount > 0 and orig_toman:
                            price_line += " (تخفیف: *" + str(discount) + "%* | قبل: ~~" + f"{orig_toman:,}" + " تومان~~)"
                    else:
                        price_line = "• *وضعیت*: `ناموجود / نامشخص`"

                    rate_info = p.get("rating") or {}
                    rate_val = rate_info.get("rate", 0)
                    rate_str = " ⭐ " + f"{rate_val / 20:.1f}" + "/5" if rate_val else ""

                    lines.append(f"{count + 1}. *{title}*{rate_str}\n   {price_line}\n   🔗 [مشاهده و خرید در دیجی‌کالا]({product_url})\n")
                    count += 1

                out_text = "\n".join(lines)
                _L1_DIGIKALA_CACHE[cache_key] = (now, out_text)
                await database.kv_set_cache_async(cache_key, out_text, expiration_ttl=900)
                return out_text
    except Exception as e:
        logger.debug("Digikala API error: " + str(e))

    try:
        from src.tools.web_network import web_search
        searched = await web_search("site:digikala.com/product " + clean_q, max_results=4)
        if searched and "یافت نشد" not in searched:
            return "🛍 *نتایج دیجی‌کالا از وب:*\n\n" + searched
    except Exception:
        pass

    return "استعلام محصول از دیجی‌کالا برای «" + clean_q + "» با اختلال موقت مواجه شد."
