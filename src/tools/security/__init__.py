import httpx
from src.core.http import shared_client_ctx
import logging
from bs4 import BeautifulSoup
import urllib.parse
import asyncio
from src.tools.registry import register_tool

logger = logging.getLogger(__name__)

@register_tool(
    name="darkweb_search",
    description="جستجوی امن و کاوش پیوندها و دامنه‌های پنهان شبکه تور (Tor Hidden Services .onion)",
    category="security"
)
async def darkweb_search(query: str) -> str:
    """
    :param query: عبارت جستجو برای کاوش در شبکه پنهان تور (.onion)
    """
    results = []
    clean_q = query.strip()
    if not clean_q:
        return "عبارت جستجو خالی است."

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    }

    # 1. Ahmia Tor Search Engine (Fast mirror)
    async def search_ahmia():
        try:
            url = f"https://ahmia.fi/search/?q={urllib.parse.quote(clean_q)}"
            async with shared_client_ctx("web") as client:
                r = await client.get(url, headers=headers)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "html.parser")
                    items = []
                    for item in soup.find_all("li", class_="result")[:5]:
                        title_tag = item.find("h4")
                        cite_tag = item.find("cite")
                        desc_tag = item.find("p")

                        title = title_tag.get_text(strip=True) if title_tag else "سرویس مخفی تور"
                        onion_link = cite_tag.get_text(strip=True) if cite_tag else ""
                        desc = desc_tag.get_text(strip=True) if desc_tag else ""

                        if onion_link:
                            items.append(f"• *{title}*\n  آدرس (.onion): `{onion_link}`\n  توضیحات: {desc}")
                    return items
        except Exception:
            return []
        return []

    # 2. DuckDuckGo Onion Mirror Search
    async def search_ddg_onion():
        try:
            ddg_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(clean_q + ' site:onion')}&format=json&no_html=1"
            async with shared_client_ctx("fast") as client:
                r = await client.get(ddg_url, headers=headers)
                if r.status_code == 200:
                    items = []
                    for topic in r.json().get("RelatedTopics", [])[:4]:
                        t_text = topic.get("Text", "")
                        t_url = topic.get("FirstURL", "")
                        if t_url:
                            items.append(f"• *{t_text[:80]}*\n  پیوند: `{t_url}`")
                    return items
        except Exception:
            return []
        return []

    r_ahmia, r_ddg = await asyncio.gather(search_ahmia(), search_ddg_onion(), return_exceptions=True)

    if isinstance(r_ahmia, list) and r_ahmia:
        results.extend(r_ahmia)
    if isinstance(r_ddg, list) and r_ddg:
        results.extend(r_ddg)

    if not results:
        # Graceful clearnet fallback: still answer with related surface-web intel
        # instead of a dead-end failure marker.
        try:
            from src.tools import web_network as _web
            surface = await _web.web_search(f"{clean_q} onion hidden service", max_results=4)
            if surface and "یافت نشد" not in surface and len(surface) > 60:
                return (
                    f"🕵️ *کاوش تور (.onion)*: پیوند مستقیم فعالی برای «{clean_q}» یافت نشد، اما اطلاعات مرتبط وب:\n\n{surface}"
                )
        except Exception:
            pass
        return f"هیچ پیوند فعالی در شبکه پنهان تور (.onion) برای '{clean_q}' یافت نشد."

    return "🕵️ *نتایج جستجو در شبکه‌های پنهان تور (Darknet .onion)*:\n\n" + "\n\n".join(results[:5])
