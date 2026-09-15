import httpx
import logging
import socket
import ssl
import re
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional, List, Tuple
import time
import urllib.parse
import asyncio
from src.tools.registry import register_tool
from src.core import database

logger = logging.getLogger(__name__)

# High-concurrency connection pool for fast web exploration
_http_limits = httpx.Limits(max_keepalive_connections=120, max_connections=250, keepalive_expiry=240.0)
_client: Optional[httpx.AsyncClient] = None

# Ultra-Fast L1 RAM Cache for Web Search (Sub-millisecond latency for repeated queries)
_L1_WEB_CACHE: Dict[str, Tuple[float, str]] = {}
_L1_FRESH_TTL = 90.0      # 90 seconds for fresh/breaking/price queries
_L1_STANDARD_TTL = 3600.0  # 1 hour for general knowledge
_L1_WEB_MAX_KEYS = 400


def _l1_web_put(key: str, value: str) -> None:
    # Bounded L1: evict oldest 100 when full so Railway small RAM never leaks.
    try:
        if len(_L1_WEB_CACHE) >= _L1_WEB_MAX_KEYS:
            for _k in list(_L1_WEB_CACHE.keys())[:100]:
                _L1_WEB_CACHE.pop(_k, None)
        _L1_WEB_CACHE[key] = (time.time(), value)
    except Exception:
        pass


def _kv_safe_key(prefix: str, query: str) -> str:
    # Cloudflare KV keys max out at 512 chars; hash long Persian queries.
    try:
        base = f"{prefix}_{(query or '').lower().replace(' ', '_')}"
        if len(base) <= 300:
            return base
        import hashlib as _hl
        h = _hl.sha1((query or '').lower().encode("utf-8")).hexdigest()[:16]
        return f"{prefix}_{h}"
    except Exception:
        return f"{prefix}_q"

_TAVILY_EXHAUSTED_UNTIL = 0.0

def get_async_client(profile: str = "web") -> httpx.AsyncClient:
    """Returns pooled high-concurrency AsyncClient with keep-alive socket reuse."""
    try:
        from src.core.http import get_http_client
        return get_http_client(profile)
    except Exception:
        global _client
        if _client is None or _client.is_closed:
            _client = httpx.AsyncClient(
                limits=_http_limits,
                timeout=4.0,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7"
                }
            )
        return _client

def _normalize_search_query(q: str) -> str:
    """Normalize Persian characters (ye/ke), remove zero-width spaces and noise for sub-millisecond cache hits."""
    if not q:
        return ""
    text = q.replace("\u064a", "\u06cc").replace("\u0643", "\u06a9").replace("\u200c", " ").replace("\u200b", "")
    text = re.sub(r'[!?,;؛؟،"\'\(\)\[\]\{\}\<\>]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip().lower()

async def tavily_search_raw(query: str, max_results: int = 5, search_depth: str = "basic", include_answer: bool = True, time_range: Optional[str] = None) -> Dict[str, Any]:
    """Direct Tavily API call with circuit breaker on quota exhaustion. Uses fast basic depth (<800ms). Never raises."""
    global _TAVILY_EXHAUSTED_UNTIL
    if time.time() < _TAVILY_EXHAUSTED_UNTIL:
        return {}
    try:
        from src.core.config import TAVILY_API_URL
        try:
            from src.core.config import TAVILY_API_KEYS as _KEYS
        except Exception:
            _KEYS = []
        try:
            from src.core.config import TAVILY_API_KEY as _K1
        except Exception:
            _K1 = ""
        keys = [k for k in (list(_KEYS or []) + [_K1]) if k]
        seen_k = set()
        keys = [k for k in keys if not (k in seen_k or seen_k.add(k))]
    except Exception:
        return {}
    if not keys:
        return {}
    try:
        client = get_async_client("api")
        last_err = ""
        for _key in keys:
            try:
                payload: Dict[str, Any] = {
                    "api_key": _key,
                    "query": (query or "").strip(),
                    "max_results": max(1, min(10, int(max_results or 5))),
                    "search_depth": search_depth,
                    "include_answer": bool(include_answer),
                    "include_images": False,
                }
                if time_range:
                    payload["time_range"] = time_range
                r = await client.post(TAVILY_API_URL, json=payload, timeout=2.2)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, dict) and data.get("results"):
                        return data
                    last_err = "empty-results"
                    continue
                if r.status_code in (429, 432, 401, 403):
                    # Quota reached or unauthorized: trip circuit breaker for 30 mins
                    _TAVILY_EXHAUSTED_UNTIL = time.time() + 1800
                    logger.info(f"Tavily circuit breaker tripped (HTTP {r.status_code}) for 30m.")
                    return {}
                last_err = f"HTTP {r.status_code}"
                continue
            except Exception as e:
                last_err = str(e)[:100]
        if last_err:
            logger.debug(f"Tavily search attempts finished without success: {last_err}")
        return {}
    except Exception as e:
        logger.debug(f"Tavily search failed: {e}")
        return {}


def _tavily_items_to_text(data: Dict[str, Any], max_results: int = 5) -> str:
    """Format Tavily JSON into the bot's bullet format (same as other engines)."""
    try:
        blocks = []
        ans = (data.get("answer") or "").strip()
        if ans:
            blocks.append(f"\U0001F9E0 *\u067e\u0627\u0633\u062e \u0645\u0633\u062a\u0642\u06cc\u0645 Tavily:* {ans[:600]}")
        for it in (data.get("results") or [])[:max_results]:
            title = (it.get("title") or "").strip().replace("\n", " ")[:120]
            link = (it.get("url") or "").strip()
            snippet = (it.get("content") or "").strip().replace("\n", " ")[:400]
            pub = (it.get("published_date") or "").strip()
            if not title or not link:
                continue
            line = f"\u2022 *{title}*\n  \U0001F517 {link}"
            if pub:
                line += f"\n  \U0001F4C5 {pub}"
            if snippet:
                line += f"\n  \U0001F4C4 {snippet}"
            blocks.append(line)
        return "\n\n".join(blocks)
    except Exception:
        return ""


def clean_target_host(target: str) -> str:
    if not target:
        return ""
    t = target.strip().replace("https://", "").replace("http://", "")
    return t.split("/")[0].split("?")[0].split(":")[0].strip()

# =========================================================================
# 1. High-Performance Multi-Engine Web Search & Deep Crawler Architecture
# =========================================================================

# Freshness markers: queries carrying these want the NEWEST data, never stale cache.
_FRESH_MARKERS = (
    "امروز", "امشب", "جدید", "تازه", "آخرین", "اخیر", "لحظه", "فوری",
    "به‌روز", "بروز", "داغ", "همین الان", "همین حالا",
    "breaking", "latest", "today", "live", "now", "recent", "update",
    "قیمت", "نرخ", "جدول", "نتایج", "نتیجه",
)


def _is_fresh_query(q: str) -> bool:
    try:
        _ql = (q or "").lower()
        return any(_m in _ql for _m in _FRESH_MARKERS)
    except Exception:
        return False


@register_tool(
    name="web_search",
    description="موتور جستجوی چندلایه‌ای، فوق‌سریع و زنده وب (شامل نتایج وب، اخبار، پیوندها و منابع معتبر)",
    category="search"
)
async def web_search(query: str, max_results: int = 5, force_refresh: bool = False) -> str:
    """
    :param query: عبارت مورد نظر برای جستجو در وب
    :param max_results: حداکثر تعداد نتایج جستجو
    :param force_refresh: اگر True باشد کش نادیده گرفته و حتماً زنده سرچ می‌شود (برای اخبار لحظه‌ای)
    """
    clean_q = (query or "").strip()
    if not clean_q:
        return "عبارت جستجو خالی است."

    # Freshness-aware cache: breaking/live queries revalidate every 90s so the
    # user always sees the newest data; ordinary queries keep the 3600s TTL.
    _fresh = _is_fresh_query(clean_q)
    _norm_q = _normalize_search_query(clean_q)
    cache_key = _kv_safe_key("SEARCH", _norm_q)
    _now = time.time()

    # 1. Fast L1 In-Memory RAM Cache (Sub-millisecond retrieval)
    if not force_refresh and cache_key in _L1_WEB_CACHE:
        _ts, _cached_val = _L1_WEB_CACHE[cache_key]
        _max_age = _L1_FRESH_TTL if _fresh else _L1_STANDARD_TTL
        if (_now - _ts) < _max_age:
            return _cached_val

    # 2. L2 Cloudflare KV Cache
    if not force_refresh:
        cached = await database.kv_get_cache_async(cache_key)
        if cached:
            if not _fresh:
                _l1_web_put(cache_key, cached)
                return cached
            try:
                _age_ok = await database.kv_get_cache_async(cache_key + "_TS")
                if _age_ok and (_now - float(_age_ok)) < _L1_FRESH_TTL:
                    _l1_web_put(cache_key, cached)
                    return cached
            except Exception:
                _l1_web_put(cache_key, cached)
                return cached

    client = get_async_client("fast")
    encoded = urllib.parse.quote(clean_q)

    def _decode_search_url(url: str) -> str:
        if not url:
            return ""
        if "uddg=" in url:
            try:
                return urllib.parse.unquote(url.split("uddg=")[1].split("&")[0])
            except Exception:
                pass
        if "bing.com/ck/a" in url:
            m = re.search(r'(?:[?&]|&amp;)u=a1([a-zA-Z0-9_\-]+)', url)
            if m:
                b64_str = m.group(1) + "=" * (-len(m.group(1)) % 4)
                try:
                    import base64
                    decoded = base64.urlsafe_b64decode(b64_str).decode('utf-8', errors='ignore')
                    if decoded.startswith('http'):
                        return decoded
                except Exception:
                    pass
        return url

    # Engine 0 (FIRST PRIORITY): Tavily AI search — dated, ranked, with direct answer.
    # Fresh queries get time_range=week so the newest releases win; failures
    # fall through to the scraping engines below (never abort the search).
    async def search_tavily() -> Tuple[List[str], bool]:
        try:
            _tr = "week" if _is_fresh_query(clean_q) else None
            data = await tavily_search_raw(clean_q, max_results=max_results + 2, time_range=_tr)
            if not data or not data.get("results"):
                return [], False
            seen = set()
            out = []
            has_ans = bool((data.get("answer") or "").strip())
            if has_ans:
                out.append(f"\U0001F9E0 *پاسخ مستقیم Tavily:* {(data['answer']).strip()[:600]}")
            for it in (data.get("results") or [])[:max_results + 2]:
                title = (it.get("title") or "").strip()[:120]
                link = (it.get("url") or "").strip()
                snippet = (it.get("content") or "").strip().replace("\n", " ")[:400]
                pub = (it.get("published_date") or "").strip()
                if not title or not link or not link.startswith("http") or link in seen:
                    continue
                seen.add(link)
                line = f"• *{title}*\n  🔗 {link}"
                if pub:
                    line += f"\n  📅 {pub}"
                if snippet:
                    line += f"\n  📄 {snippet}"
                out.append(line)
            return out, has_ans
        except Exception:
            return [], False
    # Engine 1: DuckDuckGo High-Speed HTML Engine (High-reliability, anti-bot resilient, zero JS/captchas)
    async def search_ddg_lite():
        try:
            r = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": clean_q, "b": "", "kl": "wt-wt"},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    "Referer": "https://html.duckduckgo.com/",
                },
                follow_redirects=True,
                timeout=2.5
            )
            if r.status_code in (200, 202):
                soup = BeautifulSoup(r.text, "html.parser")
                results = []
                for res_div in soup.find_all("div", class_="result"):
                    if any("ad" in c.lower() for c in res_div.get("class", [])):
                        continue
                    a_title = res_div.find("a", class_="result__a")
                    a_snippet = res_div.find("a", class_="result__snippet")
                    if not a_title:
                        continue
                    raw_href = a_title.get("href", "")
                    if any(bad in raw_href for bad in ["duckduckgo.com/y.js", "bing.com/aclick", "ad_provider"]):
                        continue
                    target_url = _decode_search_url(raw_href)
                    title = a_title.get_text(strip=True)
                    snippet = a_snippet.get_text(strip=True) if a_snippet else ""
                    if title and target_url and target_url.startswith("http"):
                        results.append(f"• *{title}*\n  🔗 {target_url}\n  📄 {snippet}")
                        if len(results) >= max_results + 2:
                            break
                if results:
                    return results
        except Exception:
            pass

        # Fast fallback to Lite endpoint
        try:
            r = await client.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": clean_q},
                follow_redirects=True,
                timeout=2.0
            )
            if r.status_code in (200, 202):
                soup = BeautifulSoup(r.text, "html.parser")
                links = soup.find_all("a", class_="result-link")
                snippets = soup.find_all("td", class_="result-snippet")
                results = []
                for idx, a in enumerate(links):
                    raw_href = a.get("href", "")
                    if any(bad in raw_href for bad in ["duckduckgo.com/y.js", "bing.com/aclick", "ad_provider"]):
                        continue
                    target_url = _decode_search_url(raw_href)
                    title = a.get_text(strip=True)
                    snippet = snippets[idx].get_text(strip=True) if idx < len(snippets) else ""
                    if title and target_url and target_url.startswith("http"):
                        results.append(f"• *{title}*\n  🔗 {target_url}\n  📄 {snippet}")
                        if len(results) >= max_results + 2:
                            break
                if results:
                    return results
        except Exception:
            pass
        return []

    # Engine 2: Wikipedia Knowledge Engine (Strictly for definitions/concepts; NEVER for pricing/commerce/news)
    async def search_wikipedia():
        # Anti-Hallucination Guard: Never search Wikipedia for pricing, live rates, news, or commercial goods
        non_wiki_words = [
            "قیمت", "نرخ", "چنده", "چند است", "دلار", "ارز", "طلا", "سکه", "تومان", "ریال",
            "خرید", "فروش", "بازار", "امروز", "لحظه", "خودرو", "گوشی", "موبایل", "آیفون",
            "سهام", "بنزین", "بورس", "دیجیکالا", "دیجی کالا", "لپتاپ", "لپ تاپ", "کالا", "اجناس",
            "price", "rate", "today", "buy", "stock"
        ]
        if any(nw in clean_q.lower() for nw in non_wiki_words):
            return []

        res = []
        query_tokens = [t for t in re.split(r"\s+", clean_q.lower()) if len(t) >= 2]
        wiki_headers = {"User-Agent": "PrometheusBot/2.0 (KnowledgeEngine; +https://t.me/AMZprometheusopenbot)"}
        for lang in ["fa", "en"]:
            try:
                wiki_url = f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search&srsearch={encoded}&format=json&utf8=1"
                r = await client.get(wiki_url, headers=wiki_headers, timeout=2.0)
                if r.status_code == 200:
                    for item in r.json().get("query", {}).get("search", [])[:3]:
                        title = item.get("title", "")
                        # Article title MUST contain query tokens to prevent bizarre false matches
                        if query_tokens and not any(token in title.lower() for token in query_tokens):
                            continue
                        clean_text = BeautifulSoup(item.get("snippet", ""), "html.parser").get_text()
                        res.append(f"• *[دانشنامه {lang.upper()}] {title}*\n  🔗 https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title)}\n  📄 {clean_text}")
                if res:
                    break
            except Exception:
                pass
        return res

    # Engine 3: Bing Live Search
    async def search_bing():
        try:
            r = await client.get(f"https://www.bing.com/search?q={encoded}", timeout=2.5)
            if r.status_code == 200:
                res = []
                soup = BeautifulSoup(r.text, "html.parser")
                for el in soup.find_all("li", class_="b_algo")[:6]:
                    h2 = el.find("h2")
                    p_tag = el.find("p")
                    if h2:
                        a_tag = h2.find("a")
                        title = h2.get_text(strip=True)
                        link = a_tag.get("href", "") if a_tag else ""
                        decoded_link = _decode_search_url(link)
                        snippet = p_tag.get_text(strip=True) if p_tag else ""
                        if title and decoded_link and decoded_link.startswith("http") and not decoded_link.startswith("https://r.bing.com"):
                            res.append(f"• *{title}*\n  🔗 {decoded_link}\n  📄 {snippet}")
                if res:
                    return res

                # Fast regex fallback for Bing
                h2s = re.findall(r"<h2[^>]*>\s*<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", r.text)
                for raw_l, raw_t in h2s[:6]:
                    clean_t = re.sub(r"<[^>]+>", "", raw_t).strip()
                    dec_l = _decode_search_url(raw_l)
                    if clean_t and dec_l and dec_l.startswith("http") and "bing.com" not in dec_l:
                        res.append(f"• *{clean_t}*\n  🔗 {dec_l}")
                return res
        except Exception:
            return []
        return []

    # Engine 4: DuckDuckGo Instant Answer API (fast facts, abstracts, prices)
    async def search_ddg_instant():
        try:
            r = await client.get(f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1", timeout=3.5)
            if r.status_code == 200:
                d = r.json()
                res = []
                abstract = (d.get("AbstractText") or "").strip()
                if abstract:
                    src = d.get("AbstractURL") or "DuckDuckGo"
                    res.append(f"• *{d.get('Heading') or clean_q}*\n  🔗 {src}\n  📄 {abstract[:400]}")
                for topic in (d.get("RelatedTopics") or [])[:4]:
                    if isinstance(topic, dict) and topic.get("FirstURL"):
                        res.append(f"• *{(topic.get('Text') or '')[:90]}*\n  🔗 {topic.get('FirstURL')}\n  📄 {(topic.get('Text') or '')[:250]}")
                return res
        except Exception:
            return []
        return []

    # Engine 5: Mojeek independent index (no Big-Tech blind spots)
    async def search_mojeek():
        try:
            r = await client.get(f"https://www.mojeek.com/search?q={encoded}", timeout=4.0)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                res = []
                for el in soup.find_all("a", class_="title")[:5]:
                    title = el.get_text(strip=True)
                    link = el.get("href", "")
                    if title and link and link.startswith("http"):
                        res.append(f"• *{title}*\n  🔗 {link}")
                return res
        except Exception:
            return []
        return []

    # Engine 6: Brave Search (independent index, anti-bot tolerant)
    async def search_brave():
        try:
            r = await client.get(f"https://search.brave.com/search?q={encoded}&source=web", timeout=4.0)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                res = []
                for el in soup.select('div.snippet[data-url], a.result-header')[:6]:
                    if el.name == "a":
                        title = el.get_text(strip=True)
                        link = el.get("href", "")
                    else:
                        a_tag = el.find("a")
                        title = a_tag.get_text(strip=True) if a_tag else ""
                        link = el.get("data-url") or (a_tag.get("href", "") if a_tag else "")
                    if title and link and link.startswith("http"):
                        res.append(f"• *{title}*\n  🔗 {link}")
                return res
        except Exception:
            return []
        return []

    # Strict Relevance Filter to eliminate spam, foreign language noise and false Bing hits
    def _is_result_relevant(item_str: str, q: str) -> bool:
        if item_str.startswith("\U0001F9E0"):
            return True
        low_item = item_str.lower()
        # Extract title and snippet
        t_m = re.search(r'•\s*\*([^*]+)\*', item_str)
        s_m = re.search(r'📄\s*([^\n]+)', item_str)
        text_content = f"{t_m.group(1) if t_m else ''} {s_m.group(1) if s_m else ''}".lower()

        # Reject known noise & spam
        if any(bad in low_item for bad in ["duckduckgo.com/y.js", "bing.com/aclick", "support.google.com/youtube", "zhihu.com", "deepl.com", "reverso.net", "googletraduction"]):
            return False

        # If query has Persian characters, result MUST contain Persian characters
        has_fa_query = any(0x0600 <= ord(c) <= 0x06FF for c in q)
        if has_fa_query:
            has_fa_result = any(0x0600 <= ord(c) <= 0x06FF for c in text_content)
            if not has_fa_result:
                return False

        # Check keyword hits
        q_tokens = [re.sub(r'[^\w\u0600-\u06FF]', '', w) for w in re.split(r'\s+', q.lower())]
        q_tokens = [w for w in q_tokens if len(w) >= 2]
        hits = sum(1 for tok in q_tokens if tok in text_content)
        return hits > 0 or len(q_tokens) == 0

    def _rank_score(item_str: str, q: str) -> float:
        if item_str.startswith("\U0001F9E0"):
            return 999.0
        t_m = re.search(r'•\s*\*([^*]+)\*', item_str)
        s_m = re.search(r'📄\s*([^\n]+)', item_str)
        text_content = f"{t_m.group(1) if t_m else ''} {s_m.group(1) if s_m else ''}".lower()
        q_tokens = [re.sub(r'[^\w\u0600-\u06FF]', '', w) for w in re.split(r'\s+', q.lower())]
        q_tokens = [w for w in q_tokens if len(w) >= 2]
        if not q_tokens:
            return 0.0
        hits = sum(1 for tok in q_tokens if tok in text_content)
        score = hits / max(1, len(q_tokens))
        joined = " ".join(q_tokens)
        if joined and joined in text_content:
            score += 0.5
        if any(src in item_str for src in ("wikipedia.org", "tgju.org", "varzesh3.com")):
            score += 0.1
        return score

    def _filter_and_dedup(items: List[str], q: str, limit: int) -> List[str]:
        seen_urls = set()
        scored = []
        for item in items:
            if item.startswith("\U0001F9E0"):
                scored.append((999.0, item))
                continue
            url_match = re.search(r'🔗\s*(\S+)', item)
            url_key = url_match.group(1) if url_match else item
            if url_key in seen_urls:
                continue
            if not _is_result_relevant(item, q):
                continue
            seen_urls.add(url_key)
            scored.append((_rank_score(item, q), item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [it for _, it in scored][:limit]

    async def _format_and_cache(deduped_items: List[str]) -> str:
        _stamp = time.strftime("%H:%M")
        out_text = f"🕐 _به‌روزرسانی زنده وب ({_stamp})_\n\n" + "\n\n".join(deduped_items)
        _l1_web_put(cache_key, out_text)
        try:
            await database.kv_set_cache_async(cache_key, out_text, expiration_ttl=3600 if not _fresh else 90)
            await database.kv_set_cache_async(cache_key + "_TS", str(time.time()), expiration_ttl=3600)
        except Exception:
            pass
        return out_text

    # High-Speed Multi-Engine Speculative Race:
    # Run all fast, anti-bot resilient engines concurrently with pooled sockets.
    # Returns as soon as ANY fast engine delivers valid results, dropping latency to <1.0s.
    try:
        from src.core.config import has_tavily as _has_tv_cfg
        _tavily_enabled = bool(_has_tv_cfg()) and (time.time() >= _TAVILY_EXHAUSTED_UNTIL)
    except Exception:
        _tavily_enabled = False

    tavily_task = asyncio.create_task(search_tavily()) if _tavily_enabled else None
    ddg_task = asyncio.create_task(search_ddg_lite())
    wiki_task = asyncio.create_task(search_wikipedia())
    ddg_instant_task = asyncio.create_task(search_ddg_instant())
    bing_task = asyncio.create_task(search_bing())

    all_spec_tasks = [t for t in (tavily_task, ddg_task, wiki_task, ddg_instant_task, bing_task) if t is not None]
    collected_results: List[str] = []
    has_direct_ans = False

    try:
        # Active Collector Loop: Process results as each engine finishes (deadline 1.6s)
        race_deadline = time.time() + 1.6
        for fut in asyncio.as_completed(all_spec_tasks, timeout=1.6):
            try:
                res = await fut
                if isinstance(res, tuple):
                    res, is_ans = res
                    if is_ans:
                        has_direct_ans = True
                if isinstance(res, list) and res:
                    collected_results.extend(res)
                    clean_res = _filter_and_dedup(collected_results, clean_q, max_results + 2)
                    # Instant early exit: direct answer or at least 2 relevant hits
                    if has_direct_ans or len(clean_res) >= 2:
                        for t in all_spec_tasks:
                            if not t.done():
                                t.cancel()
                        return await _format_and_cache(clean_res)
            except asyncio.TimeoutError:
                break
            except Exception:
                pass
            if time.time() >= race_deadline:
                break

        if collected_results:
            clean_combined = _filter_and_dedup(collected_results, clean_q, max_results + 2)
            if clean_combined:
                for t in all_spec_tasks:
                    if not t.done():
                        t.cancel()
                return await _format_and_cache(clean_combined)

    except Exception:
        pass
    finally:
        for t in all_spec_tasks:
            if not t.done():
                t.cancel()

    # Fallback to secondary search engines (Brave & Mojeek)
    try:
        rem = await asyncio.gather(
            search_brave(),
            search_mojeek(),
            return_exceptions=True
        )
        r_brave, r_mojeek = [
            res if isinstance(res, list) else [] for res in rem
        ]
        combined_secondary = _filter_and_dedup(r_brave + r_mojeek, clean_q, max_results)
        if combined_secondary:
            return await _format_and_cache(combined_secondary)
    except Exception:
        pass

    if collected_results:
        deduped = _filter_and_dedup(collected_results, clean_q, max_results + 2)
        if deduped:
            return await _format_and_cache(deduped)

    return f"نتیجه‌ای برای جستجوی '{clean_q}' در وب یافت نشد."

@register_tool(
    name="deep_search_and_read",
    description="معماری پیشرفته جستجو و مطالعه عمیق وب: جستجوی همزمان در اینترنت، استخراج پیوندهای برتر و مطالعه موازی محتوای کامل صفحات وب جهت تحلیل و نتیجه‌گیری جامع",
    category="search"
)
async def deep_search_and_read(query: str, max_pages: int = 3) -> str:
    """
    :param query: موضوع یا سوال تحقیقی برای جستجو و مطالعه عمیق
    :param max_pages: تعداد صفحات وب برای مطالعه و استخراج کامل متن (پیش‌فرض ۳ صفحه)
    """
    clean_q = query.strip()
    if not clean_q:
        return "موضوع تحقیق خالی است."

    cache_key = f"DEEP_RESEARCH_{clean_q.lower().replace(' ', '_')}"
    _fresh_deep = _is_fresh_query(clean_q)
    if not _fresh_deep:
        cached = await database.kv_get_cache_async(cache_key)
        if cached:
            return cached

    # 1. Execute initial search (fresh queries always revalidate live)
    search_output = await web_search(clean_q, max_results=max_pages + 2, force_refresh=_fresh_deep)
    urls = re.findall(r'🔗\s*(https?://[^\s\)]+)', search_output)

    if not urls:
        return search_output

    # 2. Parallel Deep Crawl & Read Top Pages (hard budget so one slow
    # origin never stalls the whole research report).
    try:
        page_contents = await asyncio.wait_for(
            asyncio.gather(*[fetch_webpage_content(u, max_chars=1800) for u in urls[:max_pages]], return_exceptions=True),
            timeout=6.0 + 4.0 * max(1, min(4, max_pages)),
        )
    except asyncio.TimeoutError:
        page_contents = ["خطا: اتمام مهلت مطالعه صفحات"]

    summary_blocks = [f"🌐 *گزارش پژوهش و مطالعه عمیق وب برای موضوع «{clean_q}»:*\n"]

    for u, content in zip(urls[:max_pages], page_contents):
        if isinstance(content, str) and not content.startswith("خطا"):
            summary_blocks.append(f"📄 *منبع*: `{u}`\n{content.strip()[:1500]}\n---")

    import time as _t5
    final_report = f"🕐 _به‌روزرسانی زنده وب ({_t5.strftime('%H:%M')})_\n\n" + "\n\n".join(summary_blocks)
    await database.kv_set_cache_async(cache_key, final_report, expiration_ttl=120 if _fresh_deep else 600)
    return final_report

@register_tool(
    name="tavily_search",
    description="موتور جستجوی اختصاصی Tavily AI (اختیاری؛ بدون کلید خودکار به web_search رایگان برمی‌گردد)",
    category="search"
)
async def tavily_search(query: str, max_results: int = 5, time_range: str = "") -> str:
    clean_q = (query or "").strip()
    if not clean_q:
        return "عبارت جستجو خالی است."
    try:
        from src.core.config import has_tavily as _has_tv2
        if not bool(_has_tv2()):
            # No key configured → free path, zero failure for key-less deploys.
            return await web_search(clean_q, max_results=max_results, force_refresh=True)
    except Exception:
        pass
    data = await tavily_search_raw(clean_q, max_results=max_results, time_range=(time_range or None))
    if not data or not data.get("results"):
        return await web_search(clean_q, max_results=max_results, force_refresh=True)
    text = _tavily_items_to_text(data, max_results=max_results)
    if not text:
        return await web_search(clean_q, max_results=max_results, force_refresh=True)
    import time as _t6
    return f"\U0001F570 _Tavily \u0632\u0646\u062F\u0647 ({_t6.strftime('%H:%M')})_\n\n" + text


@register_tool(
    name="live_news",
    description="استعلام آخرین اخبار فوری ۲۴ ساعت اخیر جهان، فناوری، هوش مصنوعی، کریپتو، بورس و ایران",
    category="search"
)
async def live_news(topic: str = "general") -> str:
    """
    :param topic: موضوع خبر (general, crypto, ai, tech, iran, world)
    """
    clean_topic = topic.lower().strip()
    cache_key = f"LIVE_NEWS_{clean_topic}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached

    query_map = {
        "general": "اخبار فوری جهان و ایران",
        "crypto": "crypto news bitcoin ethereum",
        "ai": "artificial intelligence news openai anthropic deepseek",
        "tech": "technology science news",
        "iran": "اخبار مهم روز ایران",
        "world": "world breaking news"
    }

    q = query_map.get(clean_topic, f"اخبار {clean_topic}")
    res = await web_search(q, max_results=5, force_refresh=True)
    await database.kv_set_cache_async(cache_key, res, expiration_ttl=120)
    return res

@register_tool(
    name="fetch_webpage_content",
    description="استخراج و مطالعه کامل متن، مقالات و محتوای خالص یک آدرس اینترنتی (URL) با پاکسازی کدهای تبلیغاتی و HTML",
    category="search"
)
async def fetch_webpage_content(url: str, max_chars: int = 4000) -> str:
    """
    :param url: آدرس کامل صفحه وب (https://...)
    :param max_chars: حداکثر کاراکتر خروجی متن استخراج شده
    """
    clean_u = url.strip()
    if not clean_u.startswith("http"):
        clean_u = f"https://{clean_u}"
    try:
        from src.utils.net_guard import assert_public_url as _guard_url
        clean_u = _guard_url(clean_u)
    except Exception:
        return "⛔ این آدرس مجاز نیست (اهداف داخلی/خصوصی مسدود است)."

    cache_key = f"WEBPAGE_{clean_u}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached

    client = get_async_client()
    try:
        from src.utils.net_guard import safe_stream_get as _safe_stream
        # 8MB cap: never buffer hostile giant pages into RAM & enforce hop-by-hop redirect SSRF safety
        async with _safe_stream(client, clean_u, timeout=7.0) as r:
            if r.status_code == 200:
                body = b""
                async for chunk in r.aiter_bytes(65536):
                    body += chunk
                    if len(body) > 8 * 1024 * 1024:
                        break
                html = body.decode("utf-8", errors="replace")
            else:
                return f"خطا در دریافت صفحه: کد وضعیت HTTP {r.status_code}"
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "form", "aside", "iframe"]):
            tag.decompose()

        # Freshness-first extraction: prefer <article>/<main> body, collect
        # headings + paragraphs in order so the newest facts survive trimming.
        _scope = soup.find("article") or soup.find("main") or soup
        _parts = []
        for _el in _scope.find_all(["h1", "h2", "h3", "p", "li", "time"]):
            _t = _el.get_text(" ", strip=True)
            if _t and len(_t) > 2:
                _parts.append(_t)
        text = " ".join(_parts) or " ".join(soup.stripped_strings)
        text = re.sub(r'\s+', ' ', text).strip()

        if text:
            trimmed = text[:max_chars]
            await database.kv_set_cache_async(cache_key, trimmed, expiration_ttl=3600)
            return trimmed
        return "محتوای متنی مفیدی در این آدرس یافت نشد."
    except Exception as e:
        return f"خطا در واکشی آدرس اینترنتی: {str(e)}"

# =========================================================================
# 2. Network Diagnostics, DNS, IP Intelligence & Security Tools
# =========================================================================

@register_tool(
    name="check_website_status",
    description="بررسی وضعیت در دسترس بودن، پینگ و زمان پاسخگویی یک وب‌سایت یا سرور",
    category="network"
)
async def check_website_status(target: str) -> str:
    """
    :param target: آدرس دامنه یا سایت (مانند google.com یا https://example.com)
    """
    clean_t = target.strip()
    if not clean_t.startswith("http"):
        clean_t = f"https://{clean_t}"
    try:
        from src.utils.net_guard import assert_public_url as _guard_url
        clean_t = _guard_url(clean_t)
    except Exception:
        return "⛔ این هدف مجاز نیست (اهداف داخلی/خصوصی مسدود است)."

    client = get_async_client()
    loop = asyncio.get_running_loop()
    start_time = loop.time()
    try:
        from src.utils.net_guard import safe_http_get as _safe_get
        r = await _safe_get(client, clean_t, timeout=6.0)
        elapsed_ms = int((loop.time() - start_time) * 1000)
        status_symbol = "🟢 آنلاین" if r.status_code < 400 else "🔴 با خطا"
        return (
            f"🌐 *وضعیت وب‌سایت `{clean_t}`*:\n\n"
            f"• *وضعیت سرور*: {status_symbol} (کد HTTP `{r.status_code}`)\n"
            f"• *زمان پاسخگویی (Latency)*: `{elapsed_ms}ms`\n"
            f"• *پروتکل نهایی*: `{r.http_version}`"
        )
    except Exception as e:
        return f"🔴 وب‌سایت `{clean_t}` از دسترس خارج است یا پاسخ نمی‌دهد.\nعلت خطا: `{str(e)}`"

@register_tool(
    name="resolve_dns",
    description="استعلام رکوردهای DNS دامنه (A, AAAA, MX, NS, TXT) با DNS-over-HTTPS از سرورهای جهانی Cloudflare",
    category="network"
)
async def resolve_dns(domain: str, record_type: str = "A") -> str:
    """
    :param domain: نام دامنه مورد نظر (مانند google.com)
    :param record_type: نوع رکورد (A, AAAA, MX, NS, TXT, CNAME)
    """
    clean_d = clean_target_host(domain)
    clean_type = record_type.upper().strip()
    if clean_type not in ("A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA", "SRV"):
        return f"نوع رکورد `{record_type}` نامعتبر است. مقادیر مجاز: A, AAAA, MX, NS, TXT, CNAME, SOA, SRV"
    if not clean_d or "." not in clean_d or not re.match(r"^[A-Za-z0-9._-]+$", clean_d):
        return f"نام دامنه «{domain}» نامعتبر است."
    client = get_async_client()
    try:
        url = f"https://cloudflare-dns.com/dns-query?name={clean_d}&type={clean_type}"
        headers = {"Accept": "application/dns-json"}
        r = await client.get(url, headers=headers, timeout=4.0)
        if r.status_code == 200:
            data = r.json()
            answers = data.get("Answer", [])
            if answers:
                lines = [f"🌐 *رکوردهای DNS دامنه `{clean_d}` (نوع: `{clean_type}`)*:\n"]
                for ans in answers:
                    lines.append(f"• `{ans.get('data')}` (TTL: `{ans.get('TTL')}s`)")
                return "\n".join(lines)
            return f"رکوردی از نوع `{clean_type}` برای دامنه `{clean_d}` یافت نشد."
    except Exception as e:
        return f"خطا در استعلام DNS: {str(e)}"
    return "استعلام رکورد DNS ناموفق بود."

@register_tool(
    name="get_ip_info",
    description="استعلام اطلاعات جغرافیایی، کشور، شهر، ISP و سازمان ارائه‌دهنده یک آدرس IP یا دامنه",
    category="network"
)
async def get_ip_info(target: str) -> str:
    """
    :param target: آدرس IP یا نام دامنه
    """
    clean_t = clean_target_host(target)
    if clean_t.lower() in ("localhost", "127.0.0.1", "::1", "169.254.169.254") or clean_t.endswith(".internal"):
        return "⛔ استعلام آدرس‌های شبکه داخلی یا متادیتا مجاز نیست."
    client = get_async_client()
    try:
        r = await client.get(f"http://ip-api.com/json/{clean_t}?fields=status,message,country,countryCode,regionName,city,zip,lat,lon,timezone,isp,org,as,query", timeout=4.0)
        if r.status_code == 200:
            d = r.json()
            if d.get("status") == "success":
                return (
                    f"🌍 *اطلاعات موقعیت و مالکیت IP (`{d.get('query')}`)*:\n\n"
                    f"• *کشور*: {d.get('country')} ({d.get('countryCode')})\n"
                    f"• *شهر / استان*: {d.get('city')}, {d.get('regionName')}\n"
                    f"• *منطقه زمانی*: `{d.get('timezone')}`\n"
                    f"• *ارائه‌دهنده اینترنت (ISP)*: `{d.get('isp')}`\n"
                    f"• *سازمان*: `{d.get('org')}`\n"
                    f"• *شماره خودمختار (AS)*: `{d.get('as')}`"
                )
            return f"اطلاعاتی برای `{clean_t}` یافت نشد: {d.get('message')}"
    except Exception as e:
        return f"خطا در دریافت مشخصات IP: {str(e)}"
    return "دریافت اطلاعات IP ناموفق بود."

@register_tool(
    name="check_ssl_certificate",
    description="بررسی مشخصات و تاریخ انقضای گواهی امنیتی SSL/TLS دامنه و صادرکننده آن",
    category="network"
)
async def check_ssl_certificate(domain: str) -> str:
    """
    :param domain: نام دامنه (مانند example.com)
    """
    clean_d = clean_target_host(domain)
    
    def _fetch_ssl():
        context = ssl.create_default_context()
        with socket.create_connection((clean_d, 443), timeout=4.0) as sock:
            with context.wrap_socket(sock, server_hostname=clean_d) as ssock:
                return ssock.getpeercert()

    try:
        cert = await asyncio.to_thread(_fetch_ssl)
        subject = dict(x[0] for x in cert.get("subject", []))
        issuer = dict(x[0] for x in cert.get("issuer", []))
        not_after = cert.get("notAfter", "")

        return (
            f"🔒 *مشخصات گواهی SSL/TLS دامنه `{clean_d}`*:\n\n"
            f"• *دامنه ثبت‌شده (CN)*: `{subject.get('commonName', clean_d)}`\n"
            f"• *صادرکننده (Issuer)*: `{issuer.get('organizationName', issuer.get('commonName', 'نامشخص'))}`\n"
            f"• *تاریخ انقضا*: `{not_after}`\n"
            f"• *وضعیت امنیت*: 🟢 معتبر و فعال"
        )
    except Exception as e:
        return f"🔴 خطا در اعتبارسنجی SSL برای `{clean_d}`: {str(e)}"

# =========================================================================
# 3. Weather & Meteorological Forecasting Engine (Open-Meteo & wttr.in)
# =========================================================================

@register_tool(
    name="get_weather",
    description="استعلام زنده وضعیت آب و هوا، دما، رطوبت، وضعیت جوی و سرعت باد تمام شهرهای ایران و جهان",
    category="weather"
)
async def get_weather(city: str = "Tehran") -> str:
    """
    :param city: نام شهر به فارسی یا انگلیسی (مانند Tehran, Mashhad, Isfahan, Tabriz, London)
    """
    clean_city = city.strip()
    cache_key = f"WEATHER_{clean_city.lower()}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached

    _WEATHER_FA = {
        "clear": "صاف", "sunny": "آفتابی", "partly cloudy": "نیمه‌ابری", "cloudy": "ابری",
        "overcast": "تمام‌ابری", "mist": "مه‌آلود", "fog": "مه غلیظ", "rain": "بارانی",
        "light rain": "باران سبک", "heavy rain": "باران شدید", "drizzle": "نم‌نم باران",
        "thunderstorm": "رعدوبرق", "snow": "برفی", "light snow": "برف سبک",
        "heavy snow": "برف سنگین", "sleet": "برف و باران", "hail": "تگرگ",
        "windy": "وزش باد", "smoky haze": "غبارآلود", "haze": "غبار",
        "dust": "گردوغبار", "sandstorm": "طوفان شن",
    }
    def _fa_desc(en: str) -> str:
        key = (en or "").lower().strip()
        return f"{_WEATHER_FA.get(key, en)} ({en})" if en and en != "N/A" else "نامشخص"

    client = get_async_client()
    try:
        r = await client.get(f"https://wttr.in/{urllib.parse.quote(clean_city)}?format=j1", timeout=4.5)
        if r.status_code == 200:
            d = r.json()
            curr = d.get("current_condition", [{}])[0]
            temp = curr.get("temp_C", "N/A")
            feels = curr.get("FeelsLikeC", "N/A")
            desc = curr.get("weatherDesc", [{}])[0].get("value", "N/A")
            humidity = curr.get("humidity", "N/A")
            wind = curr.get("windspeedKmph", "N/A")

            res_text = (
                f"🌦 *وضعیت آب و هوای شهر {clean_city}*:\n\n"
                f"• *دمای هوا*: *{temp}°C* (دمای حسی: *{feels}°C*)\n"
                f"• *وضعیت جوی*: *{_fa_desc(desc)}*\n"
                f"• *میزان رطوبت*: *{humidity}%*\n"
                f"• *سرعت وزش باد*: *{wind} km/h*"
            )
            await database.kv_set_cache_async(cache_key, res_text, expiration_ttl=600)
            return res_text
    except Exception:
        pass

    # Provider 2: Open-Meteo geocoding + current weather (no key needed)
    try:
        g = await client.get(f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(clean_city)}&count=1&language=fa&format=json", timeout=4.0)
        if g.status_code == 200 and (g.json().get("results") or []):
            loc = g.json()["results"][0]
            w = await client.get(f"https://api.open-meteo.com/v1/forecast?latitude={loc['latitude']}&longitude={loc['longitude']}&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m&timezone=auto", timeout=4.0)
            if w.status_code == 200:
                cur = w.json().get("current", {})
                codes = {0: "صاف", 1: "غالباً صاف", 2: "نیمه‌ابری", 3: "تمام‌ابری", 45: "مه‌آلود", 48: "مه یخ‌زده", 51: "نم‌نم باران", 61: "بارانی", 71: "برفی", 80: "باران پراکنده", 95: "رعدوبرق"}
                res_text = (
                    f"🌦 *وضعیت آب و هوای {loc.get('name', clean_city)} ({loc.get('country', '')})*:\n\n"
                    f"• *دمای هوا*: *{cur.get('temperature_2m', '?')}°C* (دمای حسی: *{cur.get('apparent_temperature', '?')}°C*)\n"
                    f"• *وضعیت جوی*: *{codes.get(cur.get('weather_code'), '—')}*\n"
                    f"• *میزان رطوبت*: *{cur.get('relative_humidity_2m', '?')}%*\n"
                    f"• *سرعت وزش باد*: *{cur.get('wind_speed_10m', '?')} km/h*"
                )
                await database.kv_set_cache_async(cache_key, res_text, expiration_ttl=600)
                return res_text
    except Exception:
        pass

    try:
        searched = await web_search(f"weather {clean_city} today temperature", max_results=3)
        if searched and "یافت نشد" not in searched:
            return f"⚠️ *سرویس هواشناسی موقتاً در دسترس نیست — نتیجه زنده وب برای {clean_city}:*\n\n{searched}"
    except Exception:
        pass

    return f"اطلاعات هواشناسی برای شهر «{clean_city}» در دسترس نیست."

# =========================================================================
# 4. Twitter / X Real-Time Search Engine
# =========================================================================

@register_tool(
    name="twitter_search",
    description="جستجوی بلادرنگ، سریع و دقیق توییت‌ها، پست‌ها، هشتگ‌ها و حساب‌های کاربری در توییتر (X / Twitter) به زبان فارسی و انگلیسی",
    category="search"
)
async def twitter_search(query: str, max_results: int = 6) -> str:
    """
    :param query: عبارت جستجو، نام کاربری (مثلاً elonmusk@)، هشتگ یا موضوع مورد نظر در توییتر / X
    :param max_results: تعداد نتایج مورد نظر (پیش‌فرض ۶)
    """
    clean_q = (query or "").strip()
    if not clean_q:
        return "لطفاً عبارت، هشتگ یا حساب کاربری مورد نظر برای جستجو در توییتر (X) را وارد نمایید."

    cache_key = f"TWITTER_{clean_q.lower().replace(' ', '_')}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached

    client = get_async_client()

    # Smart query formation for X / Twitter
    search_variants = []
    if clean_q.startswith("@"):
        uname = clean_q.lstrip("@")
        search_variants.append(f"site:x.com/{uname} OR site:twitter.com/{uname}")
        search_variants.append(f"site:x.com {uname}")
    elif clean_q.startswith("#"):
        search_variants.append(f"site:x.com/hashtag {clean_q}")
        search_variants.append(f"site:x.com {clean_q}")
    else:
        search_variants.append(f"site:x.com {clean_q}")
        search_variants.append(f"site:twitter.com {clean_q}")
        search_variants.append(f"{clean_q} twitter x.com")

    found_posts = []
    seen_urls = set()

    for sv in search_variants:
        try:
            r = await client.post("https://html.duckduckgo.com/html/", data={"q": sv}, timeout=4.5)
            if r.status_code in (200, 202):
                soup = BeautifulSoup(r.text, "html.parser")
                divs = soup.find_all("div", class_="result")
                for res_div in divs:
                    a_title = res_div.find("a", class_="result__a")
                    a_snippet = res_div.find("a", class_="result__snippet")
                    if not a_title:
                        continue

                    raw_href = a_title.get("href", "")
                    target_url = raw_href
                    if "uddg=" in raw_href:
                        try:
                            target_url = urllib.parse.unquote(raw_href.split("uddg=")[1].split("&")[0])
                        except Exception:
                            pass

                    if not target_url or ("x.com" not in target_url and "twitter.com" not in target_url):
                        continue

                    # Filter out generic static policy/help pages
                    if any(bad in target_url.lower() for bad in ["rules-and-policies", "privacy", "tos", "help.x.com"]):
                        continue

                    if target_url in seen_urls:
                        continue
                    seen_urls.add(target_url)

                    title = a_title.get_text(strip=True)
                    clean_title = re.sub(r'on X:?|/ X|/ Twitter|/ Posts', '', title, flags=re.I).strip(' "“”-—')
                    snippet = a_snippet.get_text(strip=True) if a_snippet else ""

                    # Extract author handle from URL
                    handle_m = re.search(r'(?:x\.com|twitter\.com)/([^/?#]+)', target_url)
                    handle = f"@{handle_m.group(1)}" if handle_m and handle_m.group(1).lower() not in ("i", "search", "explore", "hashtag") else ""

                    found_posts.append({
                        "handle": handle,
                        "title": clean_title or title,
                        "text": snippet,
                        "url": target_url
                    })

                    if len(found_posts) >= max_results:
                        break
        except Exception:
            pass

        if len(found_posts) >= max_results:
            break

    if not found_posts:
        gen_res = await web_search(f"{clean_q} twitter", max_results=3)
        return f"🐦 *نتایج زنده توییتر (X) برای «{clean_q}»:*\n\n{gen_res}"

    lines = [f"🐦 *نتایج زنده توییتر (X / Twitter) برای «{clean_q}»:*\n"]
    for idx, p in enumerate(found_posts, 1):
        author_label = f" *{p['handle']}*" if p['handle'] else ""
        lines.append(f"{idx}.{author_label} <b>{p['title']}</b>")
        if p['text']:
            lines.append(f"   💬 <i>«{p['text']}»</i>")
        lines.append(f"   🔗 [مشاهده در X]({p['url']})\n")

    res_str = "\n".join(lines)
    await database.kv_set_cache_async(cache_key, res_str, expiration_ttl=300)
    return res_str

# Auto-register Digikala, OSINT & E-Commerce Tools (re-exported below so linters stay green)
from src.tools.web_network.digikala import digikala_search
from src.tools.web_network.ecommerce import amazon_search, ebay_search
from src.tools.web_network.osint import (
    osint_person_dossier,
    osint_ip_intelligence,
    osint_domain_dns,
    osint_phone_intelligence,
)

__all__ = [
    "digikala_search",
    "amazon_search",
    "ebay_search",
    "osint_person_dossier",
    "osint_ip_intelligence",
    "osint_domain_dns",
    "osint_phone_intelligence",
]
