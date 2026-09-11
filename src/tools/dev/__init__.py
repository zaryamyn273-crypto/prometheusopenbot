import urllib.parse
import logging
from src.core.http import shared_client_ctx
from bs4 import BeautifulSoup
from src.tools.registry import register_tool
from src.core import database
from src.core.config import GITHUB_TOKEN

logger = logging.getLogger(__name__)

# =========================================================================
# 1. Reddit Explorer & Community Discussions Search
# =========================================================================

@register_tool(
    name="reddit_search",
    description="جستجو و کاوش در ردیت (Reddit) برای یافتن تاپیک‌ها، تجربیات کاربران، حل مشکلات برنامه‌نویسی و بحث‌های جامعه ردیت",
    category="dev"
)
async def reddit_search(query: str, subreddit: str = "", sort: str = "relevance", max_results: int = 5) -> str:
    """
    :param query: موضوع، خطا یا سوال مورد نظر برای جستجو در ردیت
    :param subreddit: ساب‌ردیت خاص در صورت تمایل (مانند: python, learnprogramming, reactjs, webdev)
    :param sort: نحوه مرتب‌سازی (relevance, top, new)
    :param max_results: حداکثر تعداد نتایج (۱ تا ۱۰)
    """
    clean_q = (query or "").strip()
    if not clean_q:
        return "عبارت جستجو برای ردیت مشخص نشده است."

    sub_clean = (subreddit or "").strip().replace("r/", "").replace("/", "")
    cache_key = f"REDDIT_{sub_clean}_{clean_q.lower().replace(' ', '_')}_{sort}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    }

    # Tier 1: Reddit Real-Time Search RSS Feed
    try:
        async with shared_client_ctx("web") as client:
            encoded_q = urllib.parse.quote(clean_q)
            if sub_clean:
                rss_url = f"https://www.reddit.com/r/{sub_clean}/search.rss?q={encoded_q}&restrict_sr=1&sort={sort}"
            else:
                rss_url = f"https://www.reddit.com/search.rss?q={encoded_q}&sort={sort}"

            r = await client.get(rss_url, headers=headers)
            if r.status_code == 200 and len(r.text) > 200:
                soup = BeautifulSoup(r.text, "xml")
                entries = soup.find_all("entry")
                if entries:
                    lines = [f"👽 *نتایج جستجو در ردیت (Reddit) برای «{clean_q}»:*\n"]
                    count = 0
                    for entry in entries:
                        if count >= max(1, min(10, max_results)):
                            break
                        t_tag = entry.find("title")
                        l_tag = entry.find("link")
                        c_tag = entry.find("content")
                        a_tag = entry.find("author")

                        title = t_tag.get_text(strip=True) if t_tag else "بحث ردیت"
                        link = l_tag.get("href") if l_tag else ""
                        author = a_tag.find("name").get_text(strip=True) if (a_tag and a_tag.find("name")) else "کاربر ردیت"

                        snippet = ""
                        if c_tag:
                            snippet_soup = BeautifulSoup(c_tag.get_text(), "html.parser")
                            for bad in snippet_soup(["a", "img"]):
                                bad.decompose()
                            snippet = snippet_soup.get_text(separator=" ", strip=True)[:300]

                        sub_name = ""
                        if "/r/" in link:
                            try:
                                sub_name = "r/" + link.split("/r/")[1].split("/")[0]
                            except Exception:
                                pass

                        header_line = f"{count + 1}. *{title}*"
                        if sub_name:
                            header_line += f" (`{sub_name}`)"

                        res_entry = f"{header_line}\n   👤 نویسنده: `{author}`\n"
                        if snippet:
                            res_entry += f"   📄 {snippet}\n"
                        if link:
                            res_entry += f"   🔗 [مشاهده تاپیک در ردیت]({link})\n"
                        lines.append(res_entry)
                        count += 1

                    out_text = "\n".join(lines)
                    await database.kv_set_cache_async(cache_key, out_text, expiration_ttl=600)
                    return out_text
    except Exception as e:
        logger.debug(f"Reddit RSS error: {e}")

    # Tier 2: Site-directed web search fallback
    try:
        from src.tools.web_network import web_search
        site_term = f"site:reddit.com/r/{sub_clean}" if sub_clean else "site:reddit.com"
        searched = await web_search(f"{site_term} {clean_q}", max_results=max_results)
        if searched and "یافت نشد" not in searched:
            return f"👽 *نتایج ردیت (از موتور جستجو):*\n\n{searched}"
    except Exception:
        pass

    return f"موردی برای «{clean_q}» در ردیت یافت نشد."

# =========================================================================
# 2. StackOverflow & StackExchange Developer Knowledge Base
# =========================================================================

@register_tool(
    name="stackoverflow_search",
    description="جستجوی تخصصی در استک اورفلو (StackOverflow) شامل پرسش‌ها، پاسخ‌های تاییدشده (Accepted Answer)، رای‌ها و کدهای پیشنهادی برای رفع باگ و ارورها",
    category="dev"
)
async def stackoverflow_search(query: str, tagged: str = "", max_results: int = 4) -> str:
    """
    :param query: متن خطا، سوال یا مفهوم برنامه‌نویسی (به انگلیسی یا اصطلاحات فنی)
    :param tagged: تگ مرتبط در صورت وجود (مانند: python, javascript, docker, asyncio, postgresql)
    :param max_results: حداکثر تعداد سوالات همراه با پاسخ (۱ تا ۵)
    """
    clean_q = (query or "").strip()
    if not clean_q:
        return "متن خطا یا سوال برنامه‌نویسی مشخص نشده است."

    cache_key = f"SO_{tagged}_{clean_q.lower().replace(' ', '_')}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached

    try:
        async with shared_client_ctx("api") as client:
            params = {
                "order": "desc",
                "sort": "relevance",
                "q": clean_q,
                "site": "stackoverflow",
                "filter": "withbody"
            }
            if tagged:
                params["tagged"] = tagged.strip().lower()

            r = await client.get("https://api.stackexchange.com/2.3/search/advanced", params=params)
            if r.status_code == 200:
                items = r.json().get("items", [])
                if not items:
                    return f"پرسشی مرتبط با «{clean_q}» در StackOverflow یافت نشد."

                lines = [f"💻 *پرسش‌ها و پاسخ‌های فنی StackOverflow برای «{clean_q}»:*\n"]
                count = 0
                for it in items[:max(1, min(5, max_results))]:
                    qid = it.get("question_id")
                    title = it.get("title", "Question")
                    link = it.get("link", "")
                    score = it.get("score", 0)
                    ans_count = it.get("answer_count", 0)
                    is_ans = it.get("is_answered", False)
                    tags = ", ".join(f"`{t}`" for t in it.get("tags", [])[:4])

                    status_emoji = "✅ [پاسخ تاییدشده]" if is_ans else "❓"
                    q_block = f"{count + 1}. *{title}*\n   {status_emoji} امتیاز: *{score}* | پاسخ‌ها: *{ans_count}* | تگ‌ها: {tags}\n"

                    # Top answer query with strict 2.0s timeout to prevent latency waterfall
                    if ans_count > 0:
                        try:
                            a_url = f"https://api.stackexchange.com/2.3/questions/{qid}/answers"
                            a_res = await client.get(a_url, params={"order": "desc", "sort": "votes", "site": "stackoverflow", "filter": "withbody"}, timeout=2.0)
                            if a_res.status_code == 200:
                                a_items = a_res.json().get("items", [])
                                if a_items:
                                    top_a = a_items[0]
                                    a_score = top_a.get("score", 0)
                                    a_soup = BeautifulSoup(top_a.get("body", ""), "html.parser")
                                    a_text = a_soup.get_text(separator=" ", strip=True)[:350]
                                    q_block += f"   ⭐ *برترین پاسخ ({a_score} رأی):*\n   > {a_text}\n"
                        except Exception:
                            pass

                    if link:
                        q_block += f"   🔗 [مشاهده کامل در StackOverflow]({link})\n"
                    lines.append(q_block)
                    count += 1

                out_text = "\n".join(lines)
                await database.kv_set_cache_async(cache_key, out_text, expiration_ttl=900)
                return out_text
    except Exception as e:
        logger.debug(f"StackOverflow error: {e}")

    # Fallback to web search
    try:
        from src.tools.web_network import web_search
        searched = await web_search(f"site:stackoverflow.com {clean_q}", max_results=max_results)
        if searched and "یافت نشد" not in searched:
            return f"💻 *نتایج StackOverflow از وب:*\n\n{searched}"
    except Exception:
        pass

    return f"استعلام از StackOverflow برای «{clean_q}» با مشکل مواجه شد."

# =========================================================================
# 3. GitHub Issues & Bug Fixes Explorer
# =========================================================================

@register_tool(
    name="github_issues_search",
    description="جستجوی ایشوها و باگ‌های گزارش‌شده در مخازن گیت‌هاب (GitHub Issues) برای یافتن راه‌حل باگ‌ها، پیام‌های خطا و راهکارهای ارائه‌شده توسط توسعه‌دهندگان",
    category="dev"
)
async def github_issues_search(query: str, repo: str = "", state: str = "all", max_results: int = 4) -> str:
    """
    :param query: عنوان خطا، باگ یا پکیج مورد نظر (به عنوان مثال: D1 timeout, docker permission denied)
    :param repo: نام مخزن مشخص در صورت تمایل (مانند: tiangolo/fastapi, facebook/react)
    :param state: وضعیت ایشو (all, open, closed)
    :param max_results: حداکثر تعداد ایشوهای خروجی (۱ تا ۵)
    """
    clean_q = (query or "").strip()
    if not clean_q:
        return "متن خطا یا ایشو برای جستجو در گیت‌هاب وارد نشده است."

    cache_key = f"GH_ISSUES_{repo}_{clean_q.lower().replace(' ', '_')}_{state}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PrometheusSuperAgent/5.0"
    }
    if GITHUB_TOKEN and len(GITHUB_TOKEN) > 10:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        async with shared_client_ctx("api") as client:
            q_parts = [clean_q, "is:issue"]
            if repo:
                clean_r = repo.strip().replace("https://github.com/", "").strip("/")
                q_parts.append(f"repo:{clean_r}")
            if state in ("open", "closed"):
                q_parts.append(f"state:{state}")

            full_query = " ".join(q_parts)
            url = f"https://api.github.com/search/issues?q={urllib.parse.quote(full_query)}&per_page={max(1, min(5, max_results))}"
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                items = r.json().get("items", [])
                if not items:
                    return f"ایشویی منطبق با «{clean_q}» در گیت‌هاب یافت نشد."

                lines = [f"🐙 *ایشوها و باگ‌های مرتبط در گیت‌هاب (GitHub Issues) برای «{clean_q}»:*\n"]
                count = 0
                for it in items:
                    title = it.get("title", "Issue")
                    html_url = it.get("html_url", "")
                    issue_state = it.get("state", "open")
                    comments_count = it.get("comments", 0)
                    body = (it.get("body") or "")[:250].replace("\n", " ").strip()

                    state_label = "🟢 [باز]" if issue_state == "open" else "🟣 [حل‌شده/بسته]"
                    entry = f"{count + 1}. *{title}*\n   {state_label} | کامنت‌ها: *{comments_count}*\n"
                    if body:
                        entry += f"   📄 {body}...\n"
                    if html_url:
                        entry += f"   🔗 [مشاهده ایشو در گیت‌هاب]({html_url})\n"
                    lines.append(entry)
                    count += 1

                out_text = "\n".join(lines)
                await database.kv_set_cache_async(cache_key, out_text, expiration_ttl=900)
                return out_text
    except Exception as e:
        logger.debug(f"GitHub issues search error: {e}")

    try:
        from src.tools.web_network import web_search
        searched = await web_search(f"site:github.com issues {clean_q}", max_results=max_results)
        if searched and "یافت نشد" not in searched:
            return f"🐙 *نتایج ایشوهای گیت‌هاب از وب:*\n\n{searched}"
    except Exception:
        pass

    return f"استعلام ایشوهای گیت‌هاب برای «{clean_q}» با اختلال مواجه شد."


@register_tool(
    name="quick_http_inspect_tool",
    description="ابزار بررسی سریع، امن و سبک وضعیت پاسخ‌دهی و هدرهای یک آدرس URL جهت اعتبارسنجی لینک‌ها و سرورها",
    category="network"
)
async def quick_http_inspect_tool(url: str) -> str:
    """
    :param url: آدرس اینترنتی وب‌سایت یا سرور مورد نظر
    """
    clean_url = (url or "").strip()
    if not clean_url.startswith("http"):
        clean_url = "https://" + clean_url
    try:
        async with shared_client_ctx("fast") as client:
            r = await client.head(clean_url)
            if r.status_code in [405, 403]:
                r = await client.get(clean_url)
            return (
                f"🌐 *گزارش بررسی پیوند اینترنتی*:\n"
                f"• *آدرس*: `{clean_url}`\n"
                f"• *کد وضعیت HTTP*: `{r.status_code}` ({r.reason_phrase})\n"
                f"• *نوع محتوا*: `{r.headers.get('content-type', 'نامشخص')}`\n"
                f"• *حجم تخمینی*: `{r.headers.get('content-length', 'نامشخص')} بایت`"
            )
    except Exception as e:
        return f"❌ خطا در اتصال به `{clean_url}`: {str(e)}"
