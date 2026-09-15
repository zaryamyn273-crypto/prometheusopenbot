import urllib.parse
import time
import re
import logging
from typing import Dict, Tuple, List
from bs4 import BeautifulSoup
from src.core.http import shared_client_ctx
from src.tools.registry import register_tool
from src.core import database

logger = logging.getLogger(__name__)

_L1_ECOMMERCE_CACHE: Dict[str, Tuple[float, str]] = {}
_L1_TTL_SECONDS = 900.0

# =========================================================================
# 1. Amazon Global Search (Zero-API Stealth & Resilient Fallback)
# =========================================================================

@register_tool(
    name="amazon_search",
    description="جستجوی زنده کالا، استعلام قیمت دلاری، امتیاز خریداران، وضعیت Prime و لینک خرید محصولات در فروشگاه جهانی آمازون (Amazon) بدون نیاز به کلید API",
    category="ecommerce"
)
async def amazon_search(query: str, max_results: int = 5) -> str:
    """
    :param query: نام کالا، برند، قطعه یا محصول مورد نظر برای استعلام در آمازون (مانند: 'macbook air m3', 'sony wh-1000xm5')
    :param max_results: حداکثر تعداد نتایج (۱ تا ۱۰)
    """
    clean_q = (query or "").strip()
    if not clean_q:
        return "نام کالایی برای جستجو در آمازون مشخص نشده است."

    cache_key = f"AMZ_{clean_q.lower().replace(' ', '_')}"
    now = time.time()
    if cache_key in _L1_ECOMMERCE_CACHE:
        ts, val = _L1_ECOMMERCE_CACHE[cache_key]
        if (now - ts) < _L1_TTL_SECONDS:
            return val
    if len(_L1_ECOMMERCE_CACHE) >= 400:
        for _k in list(_L1_ECOMMERCE_CACHE.keys())[:50]:
            _L1_ECOMMERCE_CACHE.pop(_k, None)

    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        _L1_ECOMMERCE_CACHE[cache_key] = (now, cached)
        return cached

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }

    products: List[Dict[str, str]] = []

    # Tier 1: Direct Amazon Search Page Scraping
    try:
        async with shared_client_ctx("web") as client:
            enc_q = urllib.parse.quote_plus(clean_q)
            url = f"https://www.amazon.com/s?k={enc_q}"
            r = await client.get(url, headers=headers, follow_redirects=True, timeout=7.0)
            is_anti_bot = (
                r.status_code in (503, 403, 429) or
                "To discuss automated access" in r.text or
                "Robot Check" in r.text or
                "bm-verify" in r.text or
                "api-services-support@amazon.com" in r.text or
                "validateCaptcha" in r.text
            )
            if r.status_code == 200 and not is_anti_bot:
                soup = BeautifulSoup(r.text, "html.parser")
                cards = soup.select('[data-component-type="s-search-result"]')
                for card in cards:
                    if len(products) >= max(1, min(10, max_results)):
                        break
                    asin = card.get("data-asin", "").strip()
                    if not asin:
                        continue

                    title = ""
                    for a in card.select("a"):
                        txt = a.get_text(separator=" ", strip=True)
                        if len(txt) > 15 and "Sponsored" not in txt and "Leave ad feedback" not in txt:
                            title = txt
                            break
                    if not title:
                        h2 = card.select_one("h2")
                        if h2:
                            title = h2.get_text(strip=True)

                    if not title or len(title) < 5:
                        continue

                    # Price
                    price_el = card.select_one(".a-price .a-offscreen") or card.select_one(".a-price-whole")
                    price_str = price_el.get_text(strip=True) if price_el else "مشاهده در سایت"

                    # Rating and reviews
                    rating_el = card.select_one(".a-icon-alt")
                    rating_str = ""
                    if rating_el:
                        raw_rate = rating_el.get_text(strip=True)
                        rate_m = re.search(r"([\d\.]+)\s+out of", raw_rate)
                        if rate_m:
                            rating_str = f" ⭐ {rate_m.group(1)}/5"

                    reviews_el = card.select_one(".a-size-base.s-underline-text") or card.select_one(".s-underline-text")
                    reviews_str = f" ({reviews_el.get_text(strip=True)} نظر)" if reviews_el else ""

                    # Prime status
                    has_prime = bool(card.select_one(".a-icon-prime"))
                    prime_tag = " | 📦 *Prime*" if has_prime else ""

                    prod_link = f"https://www.amazon.com/dp/{asin}"
                    products.append({
                        "title": title[:140],
                        "price": price_str,
                        "rating": f"{rating_str}{reviews_str}{prime_tag}",
                        "link": prod_link
                    })
    except Exception as e:
        logger.debug(f"Direct Amazon search error: {e}")

    # Tier 2: Resilient Web Search Fallback for Amazon
    if not products:
        try:
            from src.tools.web_network import web_search
            fallback_res = await web_search(f"site:amazon.com {clean_q}", max_results=max_results)
            if not fallback_res or "یافت نشد" in fallback_res:
                fallback_res = await web_search(f"amazon {clean_q} price", max_results=max_results)
            if fallback_res and "یافت نشد" not in fallback_res:
                out_text = f"📦 *نتایج جستجو و استعلام قیمت آمازون (Amazon) برای «{clean_q}»:*\n\n{fallback_res}"
                _L1_ECOMMERCE_CACHE[cache_key] = (now, out_text)
                await database.kv_set_cache_async(cache_key, out_text, expiration_ttl=900)
                return out_text
        except Exception as fb_err:
            logger.debug(f"Amazon fallback search error: {fb_err}")

    if products:
        lines = [f"📦 *نتایج استعلام قیمت و کالاهای آمازون (Amazon) برای «{clean_q}»:*\n"]
        for idx, p in enumerate(products, 1):
            lines.append(
                f"{idx}. *{p['title']}*{p['rating']}\n"
                f"   • *قیمت*: `{p['price']}`\n"
                f"   🔗 [مشاهده کالا در Amazon]({p['link']})\n"
            )
        out_text = "\n".join(lines)
        _L1_ECOMMERCE_CACHE[cache_key] = (now, out_text)
        await database.kv_set_cache_async(cache_key, out_text, expiration_ttl=900)
        return out_text

    return f"کالایی منطبق با «{clean_q}» در آمازون یافت نشد یا دسترسی به سرور آمازون موقتاً با محدودیت مواجه شد."


# =========================================================================
# 2. eBay Global Marketplace Search (Zero-API Multi-Channel)
# =========================================================================

@register_tool(
    name="ebay_search",
    description="جستجوی زنده کالا، استعلام قیمت حراجی و خرید فوری، مشخصات و لینک مستقیم محصولات در مارکت جهانی ای‌بی (eBay) بدون نیاز به کلید API",
    category="ecommerce"
)
async def ebay_search(query: str, condition: str = "all", max_results: int = 5) -> str:
    """
    :param query: نام کالا، مدل یا پارت نامبر مورد نظر برای استعلام در eBay (مانند: 'thinkpad x1 carbon', 'rtx 4080 super')
    :param condition: وضعیت کالا: 'all' (همه), 'new' (نو و آکبند), 'used' (کارکرده / دست دوم)
    :param max_results: حداکثر تعداد اقلام پیشنهادی (۱ تا ۱۰)
    """
    clean_q = (query or "").strip()
    if not clean_q:
        return "نام کالایی برای جستجو در eBay مشخص نشده است."

    cond_clean = (condition or "all").lower().strip()
    cache_key = f"EBAY_{clean_q.lower().replace(' ', '_')}_{cond_clean}"
    now = time.time()
    if cache_key in _L1_ECOMMERCE_CACHE:
        ts, val = _L1_ECOMMERCE_CACHE[cache_key]
        if (now - ts) < _L1_TTL_SECONDS:
            return val

    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        _L1_ECOMMERCE_CACHE[cache_key] = (now, cached)
        return cached

    items: List[Dict[str, str]] = []

    # Channel 1: Targeted Live Search via Yahoo for direct ebay.com/itm items
    try:
        async with shared_client_ctx("web") as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9"
            }
            sq = f"site:ebay.com/itm {clean_q}"
            if cond_clean == "new":
                sq += " brand new"
            elif cond_clean == "used":
                sq += " used pre-owned"

            url = "https://search.yahoo.com/search?p=" + urllib.parse.quote(sq)
            r = await client.get(url, headers=headers, follow_redirects=True, timeout=6.0)
            is_anti_bot = (
                r.status_code in (503, 500, 403, 429, 307) or
                "captcha" in r.text.lower() or
                "verify you are human" in r.text.lower()
            )
            if r.status_code == 200 and not is_anti_bot:
                soup = BeautifulSoup(r.text, "html.parser")
                algos = soup.select(".algo")
                for li in algos:
                    if len(items) >= max(1, min(10, max_results)):
                        break
                    a_tag = li.find("a")
                    if not a_tag:
                        continue
                    raw_href = a_tag.get("href", "")
                    target_link = raw_href
                    if "/RU=" in raw_href:
                        try:
                            target_link = urllib.parse.unquote(raw_href.split("/RU=")[1].split("/RK=")[0])
                        except Exception:
                            pass

                    raw_title = a_tag.get_text(strip=True)
                    title = re.sub(r"^eBayhttps://www\.ebay\.com › itm › \d+", "", raw_title).strip()
                    title = title.replace(" - eBay", "").replace(" | eBay", "").strip()
                    if not title or len(title) < 5:
                        continue

                    snippet_el = li.select_one(".compText") or li.select_one(".lh-16")
                    snippet = snippet_el.get_text(strip=True) if snippet_el else ""

                    # Extract price if present in snippet or title
                    price_m = re.search(r"((?:US\s*|AU\s*|C\s*)?\$[\d\.,]+|[\£\€][\d\.,]+|\b(?:EUR|GBP|USD)\s*[\d\.,]+)", snippet + " " + title, re.IGNORECASE)
                    price_str = price_m.group(1).strip() if price_m else "استعلام در صفحه"

                    items.append({
                        "title": title[:130],
                        "price": price_str,
                        "snippet": snippet[:180],
                        "link": target_link
                    })
    except Exception as e:
        logger.debug(f"eBay search error: {e}")

    # Channel 2: Resilient Web Search Fallback
    if not items:
        try:
            from src.tools.web_network import web_search
            fallback_res = await web_search(f"site:ebay.com {clean_q}", max_results=max_results)
            if not fallback_res or "یافت نشد" in fallback_res:
                fallback_res = await web_search(f"ebay {clean_q} price", max_results=max_results)
            if fallback_res and "یافت نشد" not in fallback_res:
                out_text = f"🛒 *نتایج استعلام قیمت و کالاهای مارکت جهانی ای‌بی (eBay) برای «{clean_q}»:*\n\n{fallback_res}"
                _L1_ECOMMERCE_CACHE[cache_key] = (now, out_text)
                await database.kv_set_cache_async(cache_key, out_text, expiration_ttl=900)
                return out_text
        except Exception as fb_err:
            logger.debug(f"eBay web search fallback error: {fb_err}")

    if items:
        lines = [f"🛒 *نتایج استعلام زنده از مارکت جهانی ای‌بی (eBay) برای «{clean_q}»:*\n"]
        for idx, item in enumerate(items, 1):
            snip_line = f"   • _{item['snippet']}_\n" if item.get("snippet") else ""
            lines.append(
                f"{idx}. *{item['title']}*\n"
                f"   • *قیمت*: `{item['price']}`\n"
                f"{snip_line}"
                f"   🔗 [مشاهده کالا در eBay]({item['link']})\n"
            )
        out_text = "\n".join(lines)
        _L1_ECOMMERCE_CACHE[cache_key] = (now, out_text)
        await database.kv_set_cache_async(cache_key, out_text, expiration_ttl=900)
        return out_text

    return f"کالایی منطبق با «{clean_q}» در eBay یافت نشد یا دسترسی به سرور با اختلال مواجه شد."
