from src.core.http import shared_client_ctx
import logging
import base64
import re
import urllib.parse
from bs4 import BeautifulSoup
from typing import Dict, Any
from src.tools.registry import register_tool
from src.core import database

logger = logging.getLogger(__name__)

def _get_headers() -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PrometheusSuperAgent/4.0"
    }
    import os
    from src.core import config as _cfg
    token = getattr(_cfg, "GITHUB_TOKEN", "") or os.getenv("GITHUB_TOKEN", "")
    if token and len(str(token).strip()) > 10:
        headers["Authorization"] = f"Bearer {str(token).strip()}"
    return headers


_FA_TO_EN_DEV_TERMS = {
    "بات تلگرام": "telegram bot",
    "ربات تلگرام": "telegram bot",
    "ربات": "bot",
    "هوش مصنوعی": "ai artificial intelligence",
    "یادگیری ماشین": "machine learning",
    "پایتون": "python",
    "جاوااسکریپت": "javascript",
    "تایپ اسکریپت": "typescript",
    "راست": "rust",
    "گو": "golang",
    "سی پلاس پلاس": "cpp c++",
    "سی شارپ": "csharp",
    "لینوکس": "linux",
    "آرچ": "arch linux",
    "بک اند": "backend",
    "فرانت اند": "frontend",
    "دیتابیس": "database",
    "کرون": "cron",
    "زمانبندی": "scheduler",
    "پکیج": "package",
    "امنیت": "security",
    "اسکنر": "scanner",
    "پروکسی": "proxy",
    "وی پی ان": "vpn",
    "ابزار": "tool",
    "کتابخانه": "library",
    "فریمورک": "framework",
}

def _clean_repo(repo: str) -> str:
    r = (repo or "").strip()
    r = re.sub(r"^https?://github\.com/", "", r).strip().strip("/")
    return r

async def _web_fallback(query: str) -> str:
    """Last-resort live web search when the GitHub API is unreachable."""
    try:
        from src.tools import web_network as _web
        searched = await _web.web_search(query, max_results=4)
        if searched and "یافت نشد" not in searched:
            return searched
    except Exception:
        pass
    return ""

@register_tool(
    name="github_search_repositories",
    description="جستجوی برترین مخازن، کتابخانه‌ها و پروژه‌های گیت‌هاب بر اساس عنوان، موضوع، زبان برنامه‌نویسی یا تگ‌ها",
    category="github"
)
async def github_search_repositories(query: str, sort: str = "stars", max_results: int = 5, language: str = "") -> str:
    """
    :param query: عبارت جستجو (مانند telegram bot python, fast-api, react)
    :param sort: معیار مرتب‌سازی (stars, forks, updated)
    :param max_results: حداکثر تعداد نتایج (۱ تا ۱۰)
    :param language: فیلتر زبان برنامه‌نویسی (مانند python, typescript؛ خالی یعنی همه زبان‌ها)
    """
    clean_q = query.strip()
    # Intelligent Persian-to-English Developer Query Expansion
    expanded_terms = []
    low_q = clean_q.lower()
    for fa_term, en_term in _FA_TO_EN_DEV_TERMS.items():
        if fa_term in low_q:
            expanded_terms.append(en_term)
    
    # If user queried purely in Persian, translate the core intent
    search_terms = clean_q
    if expanded_terms:
        # Combine clean English terms with non-Persian parts
        en_part = " ".join(expanded_terms)
        latin_words = [w for w in clean_q.split() if re.match(r"^[A-Za-z0-9_\-]+$", w)]
        search_terms = f"{en_part} {' '.join(latin_words)}".strip() if latin_words else en_part

    clean_sort = (sort or "stars").lower().strip()
    if clean_sort not in ("stars", "forks", "updated"):
        clean_sort = "stars"
    clean_lang = (language or "").strip()
    full_q = search_terms + (f" language:{clean_lang}" if clean_lang else "")
    cache_key = f"GH_SEARCH_{full_q.lower()}_{clean_sort}_{max_results}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached

    try:
        encoded_q = urllib.parse.quote(full_q)
        per_page = max(1, min(10, max_results))
        url = f"https://api.github.com/search/repositories?q={encoded_q}&sort={clean_sort}&order=desc&per_page={per_page}"
        async with shared_client_ctx("api") as client:
            r = await client.get(url, headers=_get_headers())
            if r.status_code == 200:
                items = r.json().get("items", [])
                if not items:
                    return f"هیچ مخزنی برای '{query}' در گیت‌هاب یافت نشد."
                lines = [f"🔍 *برترین مخازن گیت‌هاب برای «{clean_q}»:*\n"]
                for idx, repo in enumerate(items, 1):
                    name = repo.get("full_name")
                    stars = repo.get("stargazers_count", 0)
                    forks = repo.get("forks_count", 0)
                    lang = repo.get("language") or "چندزبانه"
                    desc = repo.get("description") or "بدون توضیحات"
                    link = repo.get("html_url")
                    lines.append(f"*{idx}. [{name}]({link})*\n• ⭐ ستاره: *{stars:,}* | 🍴 فورک: *{forks:,}* | 💻 زبان: `{lang}`\n• {desc}\n")
                out_text = "\n".join(lines)
                await database.kv_set_cache_async(cache_key, out_text, expiration_ttl=600)
                return out_text
            if r.status_code in (403, 429):
                fb = await _web_fallback(f"github {clean_q} repository")
                if fb:
                    return f"⚠️ *محدودیت نرخ API گیت‌هاب — نتیجه زنده وب:*\n\n{fb}"
            return f"خطا در جستجوی گیت‌هاب (کد وضعیت: {r.status_code})"
    except Exception as e:
        fb = await _web_fallback(f"github {clean_q} repository")
        if fb:
            return f"⚠️ *ارتباط مستقیم گیت‌هاب برقرار نشد — نتیجه زنده وب:*\n\n{fb}"
        return f"خطا در ارتباط با گیت‌هاب: {str(e)}"

@register_tool(
    name="github_repo_info",
    description="استعلام جزییات کامل و آماری یک مخزن گیت‌هاب شامل تعداد ستاره‌ها، فورک‌ها، آخرین کامیت، لایسنس و شاخه‌ها",
    category="github"
)
async def github_repo_info(repo: str) -> str:
    """
    :param repo: نام مخزن به صورت owner/repo یا لینک کامل گیت‌هاب
    """
    clean_repo = _clean_repo(repo)
    if "/" not in clean_repo:
        return "فرمت مخزن نامعتبر است. مثال: `psf/requests`"
    cache_key = f"GH_REPO_{clean_repo.lower()}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached
    try:
        url = f"https://api.github.com/repos/{clean_repo}"
        async with shared_client_ctx("api") as client:
            r = await client.get(url, headers=_get_headers())
            if r.status_code == 200:
                d = r.json()
                name = d.get("full_name")
                desc = d.get("description") or "بدون توضیحات"
                stars = d.get("stargazers_count", 0)
                forks = d.get("forks_count", 0)
                watchers = d.get("subscribers_count", 0)
                open_issues = d.get("open_issues_count", 0)
                lang = d.get("language") or "چندزبانه"
                license_info = d.get("license", {}).get("name") if d.get("license") else "نامشخص"
                def_branch = d.get("default_branch", "main")
                updated_at = d.get("updated_at", "")[:10]
                created_at = d.get("created_at", "")[:10]
                html_url = d.get("html_url")
                topics = ", ".join(f"`{t}`" for t in (d.get("topics") or [])[:6]) or "—"

                out = (
                    f"📦 *اطلاعات جامع مخزن گیت‌هاب [{name}]({html_url})*:\n\n"
                    f"• *توضیحات*: {desc}\n"
                    f"• *زبان اصلی*: `{lang}` | *تاپیک‌ها*: {topics}\n"
                    f"• *ستاره‌ها (Stars)*: *{stars:,}* | *فورک‌ها*: *{forks:,}* | *دنبال‌کنندگان*: *{watchers:,}*\n"
                    f"• *ایشیوهای باز*: *{open_issues}* | *شاخه پیش‌فرض*: `{def_branch}`\n"
                    f"• *مجوز (License)*: `{license_info}`\n"
                    f"• *ساخته‌شده*: `{created_at}` | *آخرین بروزرسانی*: `{updated_at}`"
                )
                await database.kv_set_cache_async(cache_key, out, expiration_ttl=900)
                return out
            if r.status_code == 404:
                return f"مخزن `{clean_repo}` در گیت‌هاب یافت نشد."
            return f"مخزن {repo} یافت نشد (کد: {r.status_code})."
    except Exception as e:
        return f"خطا در دریافت مشخصات مخزن گیت‌هاب: {str(e)}"

@register_tool(
    name="github_read_readme",
    description="خواندن و استخراج کامل فایل راهنما (README.md) هر مخزن گیت‌هاب جهت بررسی عملکرد و نحوه راه‌اندازی",
    category="github"
)
async def github_read_readme(repo: str) -> str:
    """
    :param repo: نام مخزن به صورت owner/repo یا آدرس اینترنتی مخزن
    """
    clean_repo = _clean_repo(repo)
    if "/" not in clean_repo:
        return "فرمت مخزن نامعتبر است. مثال: `psf/requests`"
    cache_key = f"GH_README_{clean_repo.lower()}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached
    try:
        url = f"https://api.github.com/repos/{clean_repo}/readme"
        async with shared_client_ctx("api") as client:
            r = await client.get(url, headers=_get_headers())
            if r.status_code == 200:
                content_b64 = r.json().get("content", "")
                if content_b64:
                    readme_text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
                    if len(readme_text) > 3500:
                        readme_text = readme_text[:3500] + "\n\n...[ادامه ریدمی خلاصه شد]"
                    out = f"📄 *محتوای README مخزن {clean_repo}:*\n\n{readme_text}"
                    await database.kv_set_cache_async(cache_key, out, expiration_ttl=3600)
                    return out
            # Fallback: raw file on default branches
            for br in ("main", "master"):
                for fname in ("README.md", "readme.md", "Readme.md"):
                    try:
                        raw = await client.get(f"https://raw.githubusercontent.com/{clean_repo}/{br}/{fname}", timeout=8.0)
                        if raw.status_code == 200 and len(raw.text.strip()) > 20:
                            txt = raw.text
                            if len(txt) > 3500:
                                txt = txt[:3500] + "\n\n...[ادامه ریدمی خلاصه شد]"
                            out = f"📄 *محتوای README مخزن {clean_repo} (شاخه `{br}`):*\n\n{txt}"
                            await database.kv_set_cache_async(cache_key, out, expiration_ttl=3600)
                            return out
                    except Exception:
                        continue
            return f"فایل README برای مخزن {repo} یافت نشد (کد: {r.status_code})."
    except Exception as e:
        return f"خطا در دریافت ریدمی گیت‌هاب: {str(e)}"

@register_tool(
    name="github_read_file",
    description="خواندن مستقیم و تحلیل سورس‌کد یا محتوای فایل مشخص در مخازن گیت‌هاب (با تلاش خودکار روی همه شاخه‌ها)",
    category="github"
)
async def github_read_file(repo: str, filepath: str, branch: str = "main") -> str:
    """
    :param repo: نام مخزن (owner/repo)
    :param filepath: مسیر فایل در مخزن (مانند src/main.py)
    :param branch: نام برنچ (پیش‌فرض main؛ در صورت نبود خودکار master هم امتحان می‌شود)
    """
    clean_repo = _clean_repo(repo)
    clean_path = (filepath or "").strip().lstrip("/")
    if "/" not in clean_repo or not clean_path:
        return "نام مخزن یا مسیر فایل نامعتبر است."
    branches = []
    for b in [(branch or "main"), "main", "master"]:
        if b and b not in branches:
            branches.append(b)
    cache_key = f"GH_FILE_{clean_repo.lower()}_{clean_path}_{branches[0]}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached
    try:
        async with shared_client_ctx("api") as client:
            for br in branches:
                try:
                    url = f"https://api.github.com/repos/{clean_repo}/contents/{clean_path}?ref={br}"
                    r = await client.get(url, headers=_get_headers())
                    if r.status_code == 200:
                        payload = r.json()
                        if isinstance(payload, list):
                            return f"`{clean_path}` یک پوشه است؛ از ابزار `github_list_tree` برای دیدن محتوای آن استفاده کنید."
                        content_b64 = payload.get("content", "")
                        if content_b64:
                            file_text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
                            size = payload.get("size", len(file_text))
                            if len(file_text) > 3500:
                                file_text = file_text[:3500] + "\n\n...[ادامه کد خلاصه شد]"
                            out = f"📁 *محتوای فایل `{clean_path}` در مخزن {clean_repo} (شاخه `{br}`، حجم `{size:,}` بایت):*\n\n```\n{file_text}\n```"
                            await database.kv_set_cache_async(cache_key, out, expiration_ttl=3600)
                            return out
                except Exception:
                    continue
                # Raw fallback per branch
                try:
                    raw = await client.get(f"https://raw.githubusercontent.com/{clean_repo}/{br}/{clean_path}", timeout=8.0)
                    if raw.status_code == 200 and raw.text.strip():
                        file_text = raw.text
                        if len(file_text) > 3500:
                            file_text = file_text[:3500] + "\n\n...[ادامه کد خلاصه شد]"
                        out = f"📁 *محتوای فایل `{clean_path}` در مخزن {clean_repo} (شاخه `{br}`):*\n\n```\n{file_text}\n```"
                        await database.kv_set_cache_async(cache_key, out, expiration_ttl=3600)
                        return out
                except Exception:
                    continue
            return f"فایل `{clean_path}` در مخزن {clean_repo} یافت نشد (شاخه‌های بررسی‌شده: {', '.join(branches)})."
    except Exception as e:
        return f"خطا در خواندن فایل گیت‌هاب: {str(e)}"

@register_tool(
    name="github_list_tree",
    description="مشاهده ساختار پوشه‌ها، دایرکتوری‌ها و لیست فایل‌های موجود در مخزن گیت‌هاب (با پشتیبانی از شاخه دلخواه)",
    category="github"
)
async def github_list_tree(repo: str, path: str = "", branch: str = "") -> str:
    """
    :param repo: نام مخزن (owner/repo)
    :param path: مسیر پوشه درون مخزن (خالی برای روت)
    :param branch: نام شاخه (خالی یعنی شاخه پیش‌فرض مخزن)
    """
    clean_repo = _clean_repo(repo)
    clean_path = (path or "").strip().strip("/")
    clean_branch = (branch or "").strip()
    if "/" not in clean_repo:
        return "فرمت مخزن نامعتبر است. مثال: `psf/requests`"
    cache_key = f"GH_TREE_{clean_repo.lower()}_{clean_path}_{clean_branch or 'default'}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached
    try:
        url = f"https://api.github.com/repos/{clean_repo}/contents/{clean_path}"
        if clean_branch:
            url += f"?ref={clean_branch}"
        async with shared_client_ctx("api") as client:
            r = await client.get(url, headers=_get_headers())
            if r.status_code == 200:
                items = r.json()
                if isinstance(items, list):
                    lines = [f"📂 *ساختار فایل‌های مخزن {clean_repo} (مسیر: /{clean_path or ''}):*"]
                    for item in items[:35]:
                        itype = "📁" if item.get("type") == "dir" else "📄"
                        lines.append(f"{itype} `{item.get('name')}` ({item.get('size', 0):,} bytes)")
                    if len(items) > 35:
                        lines.append(f"\n... و {len(items) - 35} مورد دیگر")
                    out = "\n".join(lines)
                    await database.kv_set_cache_async(cache_key, out, expiration_ttl=900)
                    return out
                return f"`{clean_path}` یک فایل است؛ از ابزار `github_read_file` برای خواندن آن استفاده کنید."
            if r.status_code == 404:
                return f"مسیر `/{clean_path}` در مخزن {clean_repo} یافت نشد."
            return f"خطا در لیست کردن مخزن (کد: {r.status_code})."
    except Exception as e:
        return f"خطا در لیست کردن مخزن: {str(e)}"

@register_tool(
    name="github_user_info",
    description="مشاهده پروفایل کامل کاربر گیت‌هاب شامل بیو، فالوورها، تعداد مخازن و پرستاره‌ترین پروژه‌هایش",
    category="github"
)
async def github_user_info(username: str) -> str:
    """
    :param username: نام کاربری گیت‌هاب (مانند torvalds)
    """
    clean_u = (username or "").strip().lstrip("@")
    if not clean_u:
        return "نام کاربری گیت‌هاب را وارد کنید."
    cache_key = f"GH_USER_{clean_u.lower()}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached
    try:
        async with shared_client_ctx("api") as client:
            r = await client.get(f"https://api.github.com/users/{clean_u}", headers=_get_headers())
            if r.status_code == 404:
                return f"کاربر `{clean_u}` در گیت‌هاب یافت نشد."
            if r.status_code != 200:
                return f"خطا در دریافت پروفایل گیت‌هاب (کد: {r.status_code})."
            d = r.json()
            top_repos_text = ""
            try:
                rr = await client.get(f"https://api.github.com/users/{clean_u}/repos?sort=stars&order=desc&per_page=5", headers=_get_headers(), timeout=8.0)
                if rr.status_code == 200:
                    tops = [x for x in rr.json() if not x.get("fork")][:5] or rr.json()[:5]
                    top_repos_text = "\n".join(f"• [{x.get('name')}]({x.get('html_url')}) — ⭐ *{x.get('stargazers_count', 0):,}*" for x in tops)
            except Exception:
                pass
            out = (
                f"👤 *پروفایل گیت‌هاب [{d.get('login')}]({d.get('html_url')})*:\n\n"
                f"• *نام*: {d.get('name') or '—'}\n"
                f"• *بیو*: {d.get('bio') or '—'}\n"
                f"• *موقعیت*: {d.get('location') or '—'} | *وبلاگ*: {d.get('blog') or '—'}\n"
                f"• *مخازن عمومی*: *{d.get('public_repos', 0)}* | *فالوور*: *{d.get('followers', 0):,}* | *دنبال‌شونده*: *{d.get('following', 0):,}*\n"
                f"• *عضویت از*: `{str(d.get('created_at', ''))[:10]}`"
            )
            if top_repos_text:
                out += f"\n\n⭐ *پرستاره‌ترین مخازن:*\n{top_repos_text}"
            await database.kv_set_cache_async(cache_key, out, expiration_ttl=3600)
            return out
    except Exception as e:
        return f"خطا در دریافت پروفایل گیت‌هاب: {str(e)}"

@register_tool(
    name="github_repo_commits",
    description="مشاهده آخرین کامیت‌های یک مخزن گیت‌هاب شامل نویسنده، تاریخ و پیام هر کامیت",
    category="github"
)
async def github_repo_commits(repo: str, max_results: int = 5, branch: str = "") -> str:
    """
    :param repo: نام مخزن (owner/repo)
    :param max_results: تعداد کامیت‌ها (۱ تا ۱۰)
    :param branch: شاخه (خالی یعنی شاخه پیش‌فرض)
    """
    clean_repo = _clean_repo(repo)
    if "/" not in clean_repo:
        return "فرمت مخزن نامعتبر است. مثال: `psf/requests`"
    n = max(1, min(10, max_results))
    clean_branch = (branch or "").strip()
    cache_key = f"GH_COMMITS_{clean_repo.lower()}_{n}_{clean_branch or 'default'}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached
    try:
        url = f"https://api.github.com/repos/{clean_repo}/commits?per_page={n}"
        if clean_branch:
            url += f"&sha={clean_branch}"
        async with shared_client_ctx("api") as client:
            r = await client.get(url, headers=_get_headers())
            if r.status_code == 200:
                items = r.json()
                if not items:
                    return f"کامیتی در مخزن {clean_repo} یافت نشد."
                lines = [f"📝 *آخرین کامیت‌های مخزن {clean_repo}:*\n"]
                for c in items:
                    sha = (c.get("sha") or "")[:7]
                    commit = c.get("commit", {})
                    msg = (commit.get("message") or "").split("\n")[0][:120]
                    author = (commit.get("author") or {}).get("name", "نامشخص")
                    date = str((commit.get("author") or {}).get("date", ""))[:10]
                    lines.append(f"• `{sha}` — *{msg}*\n  👤 {author} | 📅 `{date}`")
                out = "\n".join(lines)
                await database.kv_set_cache_async(cache_key, out, expiration_ttl=600)
                return out
            if r.status_code == 404:
                return f"مخزن `{clean_repo}` یافت نشد."
            if r.status_code == 409:
                return f"مخزن `{clean_repo}` خالی است (بدون کامیت)."
            return f"خطا در دریافت کامیت‌ها (کد: {r.status_code})."
    except Exception as e:
        return f"خطا در دریافت کامیت‌های گیت‌هاب: {str(e)}"

@register_tool(
    name="github_repo_issues",
    description="مشاهده ایسیوهای (Issues) باز یک مخزن گیت‌هاب شامل عنوان، نویسنده و تعداد کامنت‌ها",
    category="github"
)
async def github_repo_issues(repo: str, max_results: int = 5) -> str:
    """
    :param repo: نام مخزن (owner/repo)
    :param max_results: تعداد ایسیوها (۱ تا ۱۰)
    """
    clean_repo = _clean_repo(repo)
    if "/" not in clean_repo:
        return "فرمت مخزن نامعتبر است. مثال: `psf/requests`"
    n = max(1, min(10, max_results))
    cache_key = f"GH_ISSUES_{clean_repo.lower()}_{n}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached
    try:
        url = f"https://api.github.com/repos/{clean_repo}/issues?state=open&sort=updated&per_page={n + 5}"
        async with shared_client_ctx("api") as client:
            r = await client.get(url, headers=_get_headers())
            if r.status_code == 200:
                items = [x for x in r.json() if "pull_request" not in x][:n]
                if not items:
                    return f"🟢 ایسیوی بازی در مخزن {clean_repo} وجود ندارد."
                lines = [f"🐞 *ایسیوهای باز مخزن {clean_repo}:*\n"]
                for it in items:
                    num = it.get("number")
                    title = (it.get("title") or "")[:120]
                    user = (it.get("user") or {}).get("login", "نامشخص")
                    comments = it.get("comments", 0)
                    created = str(it.get("created_at", ""))[:10]
                    link = it.get("html_url")
                    lines.append(f"• [#{num} {title}]({link})\n  👤 {user} | 💬 {comments} کامنت | 📅 `{created}`")
                out = "\n".join(lines)
                await database.kv_set_cache_async(cache_key, out, expiration_ttl=600)
                return out
            if r.status_code == 404:
                return f"مخزن `{clean_repo}` یافت نشد."
            return f"خطا در دریافت ایسیوها (کد: {r.status_code})."
    except Exception as e:
        return f"خطا در دریافت ایسیوهای گیت‌هاب: {str(e)}"

@register_tool(
    name="github_repo_releases",
    description="مشاهده آخرین ریلیزها و نسخه‌های منتشرشده یک مخزن گیت‌هاب با لینک دانلود",
    category="github"
)
async def github_repo_releases(repo: str, max_results: int = 3) -> str:
    """
    :param repo: نام مخزن (owner/repo)
    :param max_results: تعداد ریلیزها (۱ تا ۵)
    """
    clean_repo = _clean_repo(repo)
    if "/" not in clean_repo:
        return "فرمت مخزن نامعتبر است. مثال: `psf/requests`"
    n = max(1, min(5, max_results))
    cache_key = f"GH_RELEASES_{clean_repo.lower()}_{n}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached
    try:
        url = f"https://api.github.com/repos/{clean_repo}/releases?per_page={n}"
        async with shared_client_ctx("api") as client:
            r = await client.get(url, headers=_get_headers())
            if r.status_code == 200:
                items = r.json()
                if not items:
                    return f"ریلیزی در مخزن {clean_repo} منتشر نشده است."
                lines = [f"🚀 *آخرین ریلیزهای مخزن {clean_repo}:*\n"]
                for rel in items:
                    tag = rel.get("tag_name", "")
                    name = rel.get("name") or tag
                    pub = str(rel.get("published_at", ""))[:10]
                    link = rel.get("html_url")
                    assets = rel.get("assets") or []
                    dl_total = sum(a.get("download_count", 0) for a in assets)
                    lines.append(f"• [{name} ({tag})]({link})\n  📅 `{pub}` | 📥 {dl_total:,} دانلود | 📦 {len(assets)} فایل")
                out = "\n".join(lines)
                await database.kv_set_cache_async(cache_key, out, expiration_ttl=1800)
                return out
            if r.status_code == 404:
                return f"مخزن `{clean_repo}` یافت نشد."
            return f"خطا در دریافت ریلیزها (کد: {r.status_code})."
    except Exception as e:
        return f"خطا در دریافت ریلیزهای گیت‌هاب: {str(e)}"

@register_tool(
    name="github_search_code",
    description="جستجوی عبارت در سورس‌کد تمام مخازن عمومی گیت‌هاب (یافتن نمونه‌کد، توابع و استفاده از کتابخانه‌ها)",
    category="github"
)
async def github_search_code(query: str, max_results: int = 5, language: str = "") -> str:
    """
    :param query: عبارت جستجو در کد (مانند AddHandler telegram bot)
    :param max_results: تعداد نتایج (۱ تا ۱۰)
    :param language: فیلتر زبان (مانند python؛ خالی یعنی همه)
    """
    clean_q = (query or "").strip()
    if not clean_q:
        return "عبارت جستجو خالی است."
    clean_lang = (language or "").strip()
    full_q = clean_q + (f" language:{clean_lang}" if clean_lang else "")
    n = max(1, min(10, max_results))
    cache_key = f"GH_CODE_{full_q.lower()}_{n}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached
    try:
        url = f"https://api.github.com/search/code?q={urllib.parse.quote(full_q)}&per_page={n}"
        async with shared_client_ctx("api") as client:
            r = await client.get(url, headers=_get_headers())
            if r.status_code == 200:
                items = r.json().get("items", [])
                if not items:
                    return f"کدی منطبق با «{clean_q}» یافت نشد."
                lines = [f"💻 *نمونه‌کدهای یافت‌شده برای «{clean_q}»:*\n"]
                for it in items:
                    repo_name = (it.get("repository") or {}).get("full_name", "")
                    path = it.get("path", "")
                    link = it.get("html_url")
                    lines.append(f"• [{repo_name} \u2014 {path}]({link})")
                out = "\n".join(lines)
                await database.kv_set_cache_async(cache_key, out, expiration_ttl=900)
                return out
            if r.status_code in (401, 403, 429):
                # Code search needs login: no token (or capped) -> free web fallback
                # so key-less deploys still get an answer instead of an error.
                fb = await _web_fallback(f"github code {clean_q} {clean_lang} example")
                if fb:
                    note = "بدون توکن گیت‌هاب" if r.status_code == 401 else "محدودیت نرخ API گیت‌هاب"
                    return f"⚠️ *{note} — نتیجه زنده وب:*\n\n{fb}"
                if r.status_code == 401:
                    return "⚠️ جستجوی کد گیت‌هاب نیاز به توکن دارد؛ `GITHUB_TOKEN` را ست کنید (رایگان: github.com/settings/tokens)."
                return "⚠️ محدودیت نرخ جستجوی کد گیت‌هاب؛ دقایقی دیگر تلاش کنید."
            return f"خطا در جستجوی کد گیت‌هاب (کد: {r.status_code})."
    except Exception as e:
        fb = await _web_fallback(f"github code {clean_q} {clean_lang} example")
        if fb:
            return f"⚠️ *ارتباط مستقیم گیت‌هاب برقرار نشد — نتیجه زنده وب:*\n\n{fb}"
        return f"خطا در جستجوی کد گیت‌هاب: {str(e)}"

@register_tool(
    name="github_repo_stats",
    description="آمار تحلیلی مخزن گیت‌هاب: درصد زبان‌های برنامه‌نویسی و فعال‌ترین مشارکت‌کنندگان",
    category="github"
)
async def github_repo_stats(repo: str) -> str:
    """
    :param repo: نام مخزن (owner/repo)
    """
    clean_repo = _clean_repo(repo)
    if "/" not in clean_repo:
        return "فرمت مخزن نامعتبر است. مثال: `psf/requests`"
    cache_key = f"GH_STATS_{clean_repo.lower()}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached
    try:
        async with shared_client_ctx("api") as client:
            import asyncio as _aio
            lr, cr = await _aio.gather(
                client.get(f"https://api.github.com/repos/{clean_repo}/languages", headers=_get_headers()),
                client.get(f"https://api.github.com/repos/{clean_repo}/contributors?per_page=5", headers=_get_headers()),
            )
            if lr.status_code == 404:
                return f"مخزن `{clean_repo}` یافت نشد."
            lines = [f"📊 *آمار تحلیلی مخزن {clean_repo}:*\n"]
            if lr.status_code == 200:
                langs = lr.json()
                total = sum(langs.values()) or 1
                top = sorted(langs.items(), key=lambda x: x[1], reverse=True)[:6]
                lang_lines = "\n".join(f"• `{l}`: *{v * 100 / total:.1f}%*" for l, v in top)
                lines.append(f"💻 *ترکیب زبان‌ها:*\n{lang_lines}")
            if cr.status_code == 200 and isinstance(cr.json(), list) and cr.json():
                contrib = "\n".join(f"• [{c.get('login')}]({c.get('html_url')}) — *{c.get('contributions', 0)}* کامیت" for c in cr.json()[:5])
                lines.append(f"\n👥 *فعال‌ترین مشارکت‌کنندگان:*\n{contrib}")
            out = "\n".join(lines)
            await database.kv_set_cache_async(cache_key, out, expiration_ttl=3600)
            return out
    except Exception as e:
        return f"خطا در دریافت آمار مخزن: {str(e)}"

@register_tool(
    name="github_trending",
    description="مخازن ترند و داغ امروز/هفته/ماه گیت‌هاب در کل سایت یا یک زبان خاص",
    category="github"
)
async def github_trending(language: str = "", since: str = "daily") -> str:
    """
    :param language: زبان برنامه‌نویسی (مانند python؛ خالی یعنی همه زبان‌ها)
    :param since: بازه زمانی (daily, weekly, monthly)
    """
    clean_lang = (language or "").strip().lower()
    clean_since = (since or "daily").lower().strip()
    if clean_since not in ("daily", "weekly", "monthly"):
        clean_since = "daily"
    cache_key = f"GH_TRENDING_{clean_lang or 'all'}_{clean_since}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached
    try:
        path = f"/{urllib.parse.quote(clean_lang)}" if clean_lang else ""
        url = f"https://github.com/trending{path}?since={clean_since}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36"}
        async with shared_client_ctx("web") as client:
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                return f"خطا در دریافت ترندهای گیت‌هاب (کد: {r.status_code})."
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.find_all("article", class_="Box-row")[:8]
            if not cards:
                return "ترندی در این بازه یافت نشد."
            fa = {"daily": "امروز", "weekly": "هفته", "monthly": "ماه"}[clean_since]
            lang_txt = f" (زبان `{clean_lang}`)" if clean_lang else ""
            lines = [f"🔥 *مخازن ترند {fa} گیت‌هاب*{lang_txt}:\n"]
            for card in cards:
                h = card.find("h2")
                a = h.find("a") if h else None
                if not a:
                    continue
                repo_path = a.get("href", "").strip()
                repo_name = "/".join(p for p in repo_path.split("/") if p)
                desc_tag = card.find("p")
                desc = desc_tag.get_text(strip=True)[:120] if desc_tag else ""
                stars_tag = card.find("a", href=re.compile(r"/stargazers"))
                stars = stars_tag.get_text(strip=True).replace(",", "") if stars_tag else "?"
                lang_tag = card.find("span", attrs={"itemprop": "programmingLanguage"})
                lang = lang_tag.get_text(strip=True) if lang_tag else ""
                lines.append(f"• [{repo_name}](https://github.com{repo_path}) — ⭐ *{stars}* {f'`{lang}`' if lang else ''}\n  {desc}")
            out = "\n".join(lines)
            await database.kv_set_cache_async(cache_key, out, expiration_ttl=3600)
            return out
    except Exception as e:
        return f"خطا در دریافت ترندهای گیت‌هاب: {str(e)}"


# =====================================================================
# GitHub Account Control & Automation Tools (Repository Creation, File Writing, PKGBUILD, CMAKE)
# =====================================================================

@register_tool(
    name="github_create_repository",
    description="ساخت مخزن (Repository) جدید بر روی اکانت گیت‌هاب کاربر با نام، توضیحات و تعیین وضعیت عمومی/خصوصی بودن",
    category="github"
)
async def github_create_repository(
    name: str,
    description: str = "",
    private: bool = False,
    auto_init: bool = True
) -> str:
    """
    :param name: نام مخزن جدید (فقط حروف انگلیسی، خط تیره و زیرخط)
    :param description: توضیحات کوتاه درباره پروژه
    :param private: خصوصی بودن مخزن (True = Private, False = Public)
    :param auto_init: ساخت اولیه خودکار به همراه README.md
    """
    clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "-", (name or "").strip()).strip("-")
    if not clean_name:
        return "❌ نام مخزن نامعتبر است. لطفاً یک نام معتبر انگلیسی انتخاب کنید."

    headers = _get_headers()
    if "Authorization" not in headers:
        return "⚠️ برای ساخت مخزن نیاز به `GITHUB_TOKEN` با دسترسی `repo` است. لطفاً توکن خود را با دستور `/set_github <توکن>` ست کنید."

    url = "https://api.github.com/user/repos"
    payload = {
        "name": clean_name,
        "description": description.strip(),
        "private": bool(private),
        "auto_init": bool(auto_init)
    }

    try:
        async with shared_client_ctx("api") as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code in (200, 201):
                d = r.json()
                html_url = d.get("html_url")
                clone_url = d.get("clone_url")
                ssh_url = d.get("ssh_url")
                vis = "🔒 خصوصی (Private)" if d.get("private") else "🌐 عمومی (Public)"
                return (
                    f"🎉 *مخزن جدید با موفقیت روی اکانت گیت‌هاب شما ایجاد گردید!*\n\n"
                    f"• *نام مخزن*: `{d.get('full_name')}`\n"
                    f"• *سطح دسترسی*: {vis}\n"
                    f"• *آدرس وب*: [{html_url}]({html_url})\n"
                    f"• *لینک کلون HTTPS*:\n`git clone {clone_url}`\n"
                    f"• *لینک کلون SSH*:\n`git clone {ssh_url}`\n\n"
                    f"💡 اکنون می‌توانید با ابزار `github_create_or_update_file` فایل‌های پروژه (مانند `PKGBUILD`، `CMakeLists.txt` یا سورس‌کد) را به این مخزن اضافه کنید."
                )
            elif r.status_code == 422:
                return f"❌ مخزن با نام `{clean_name}` احتمالاً از قبل روی اکانت شما وجود دارد."
            elif r.status_code == 401:
                return "❌ توکن گیت‌هاب منقضی شده یا نامعتبر است."
            return f"❌ خطا در ساخت مخزن گیت‌هاب (کد وضعیت: {r.status_code}): {r.text[:200]}"
    except Exception as e:
        return f"❌ خطای سیستمی در ارتباط با گیت‌هاب: {str(e)}"


@register_tool(
    name="github_create_or_update_file",
    description="نوشتن، کامیت و ذخیره مستقیم هر نوع فایل (مانند PKGBUILD, CMakeLists.txt, سورس کد C++/Python, README) درون مخزن گیت‌هاب",
    category="github"
)
async def github_create_or_update_file(
    repo: str,
    path: str,
    content: str,
    commit_message: str = "",
    branch: str = "main"
) -> str:
    """
    :param repo: نام مخزن به صورت owner/repo
    :param path: مسیر و نام فایل در مخزن (مانند PKGBUILD, CMakeLists.txt, src/main.cpp)
    :param content: متن کامل محتوای فایل
    :param commit_message: پیام کامیت (مثلاً 'feat: add PKGBUILD')
    :param branch: شاخه مورد نظر (پیش‌فرض main)
    """
    clean_repo = _clean_repo(repo)
    clean_path = (path or "").strip().lstrip("/")
    if "/" not in clean_repo or not clean_path:
        return "❌ نام مخزن (owner/repo) یا مسیر فایل نامعتبر است."
    if not content:
        return "❌ محتوای فایل نمی‌تواند خالی باشد."

    headers = _get_headers()
    if "Authorization" not in headers:
        return "⚠️ برای کامیت و نوشتن فایل در مخزن نیاز به `GITHUB_TOKEN` با دسترسی `repo` است. لطفاً توکن خود را ست کنید."

    clean_branch = (branch or "main").strip()
    msg = commit_message.strip() or f"chore: update {clean_path} via Prometheus Bot"
    b64_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")

    file_url = f"https://api.github.com/repos/{clean_repo}/contents/{clean_path}"

    try:
        async with shared_client_ctx("api") as client:
            # 1. Check if file already exists to get its SHA (for clean updates)
            sha = None
            check_r = await client.get(f"{file_url}?ref={clean_branch}", headers=headers)
            if check_r.status_code == 200:
                sha = check_r.json().get("sha")

            payload: Dict[str, Any] = {
                "message": msg,
                "content": b64_content,
                "branch": clean_branch
            }
            if sha:
                payload["sha"] = sha

            put_r = await client.put(file_url, headers=headers, json=payload)
            if put_r.status_code in (200, 201):
                d = put_r.json()
                commit_sha = (d.get("commit", {}).get("sha") or "")[:7]
                file_link = d.get("content", {}).get("html_url", f"https://github.com/{clean_repo}/blob/{clean_branch}/{clean_path}")
                action_word = "به‌روزرسانی" if sha else "ایجاد و کامیت"
                return (
                    f"✅ *فایل با موفقیت {action_word} شد!*\n\n"
                    f"• *مخزن*: `{clean_repo}`\n"
                    f"• *مسیر فایل*: `{clean_path}`\n"
                    f"• *شاخه*: `{clean_branch}`\n"
                    f"• *کد کامیت*: `{commit_sha}`\n"
                    f"• *پیام کامیت*: «_{msg}_»\n"
                    f"• *مشاهده در گیت‌هاب*: [مشاهده فایل]({file_link})"
                )
            elif put_r.status_code == 404:
                return f"❌ مخزن `{clean_repo}` یا شاخه `{clean_branch}` یافت نشد."
            elif put_r.status_code == 401:
                return "❌ توکن گیت‌هاب نامعتبر یا بدون دسترسی نوشتن است."
            return f"❌ خطا در نوشتن فایل (کد وضعیت: {put_r.status_code}): {put_r.text[:200]}"
    except Exception as e:
        return f"❌ خطای شبکه در هنگام نوشتن فایل: {str(e)}"


@register_tool(
    name="github_generate_pkgbuild",
    description="تولید یا ثبت خودکار فایل استاندارد آرچ‌لینوکس (PKGBUILD) برای بسته‌بندی در مخازن Arch Linux و AUR با استانداردهای رسمی pacman",
    category="github"
)
def github_generate_pkgbuild(
    pkgname: str,
    pkgver: str = "1.0.0",
    pkgrel: int = 1,
    pkgdesc: str = "",
    url: str = "",
    license_type: str = "MIT",
    depends: str = "",
    makedepends: str = "git cmake",
    source_url: str = "",
    build_type: str = "cmake"
) -> str:
    """
    :param pkgname: نام پکیج (حروف کوچک و خط تیره)
    :param pkgver: نسخه پکیج (مانند 1.0.0)
    :param pkgrel: شماره بیلد پکیج (پیش‌فرض 1)
    :param pkgdesc: توضیحات کوتاه پکیج
    :param url: آدرس صفحه اصلی پروژه یا مخزن گیت‌هاب
    :param license_type: نوع لایسنس (مانند MIT, GPL3, Apache)
    :param depends: بسته‌های پیش‌نیاز اجرا با فاصله (مانند glibc curl)
    :param makedepends: بسته‌های پیش‌نیاز کامپایل با فاصله (مانند git cmake gcc)
    :param source_url: آدرس سورس‌کد یا تاربال (مانند git+https://github.com/... or https://...)
    :param build_type: نوع سیستم بیلد ('cmake', 'python', 'meson', 'make')
    """
    clean_pkgname = re.sub(r"[^a-z0-9_\-\+]", "", (pkgname or "mypackage").lower())
    clean_ver = re.sub(r"[^0-9\.]", "", (pkgver or "1.0.0"))
    clean_desc = (pkgdesc or "Package built for Arch Linux").replace('"', '\\"')
    clean_url = (url or "https://github.com").strip()
    clean_lic = (license_type or "MIT").strip()

    dep_list = " ".join(f"'{x}'" for x in (depends or "glibc").split() if x)
    make_list = " ".join(f"'{x}'" for x in (makedepends or "cmake git").split() if x)
    src_val = source_url.strip() or r'"$pkgname-$pkgver.tar.gz::$url/archive/v$pkgver.tar.gz"'

    b_type = (build_type or "cmake").lower()
    if b_type == "cmake":
        build_func = """build() {
    cmake -B build -S "$pkgname-$pkgver" \\
        -DCMAKE_BUILD_TYPE=Release \\
        -DCMAKE_INSTALL_PREFIX=/usr
    cmake --build build
}

package() {
    DESTDIR="$pkgdir" cmake --install build
}"""
    elif b_type == "python":
        build_func = """build() {
    cd "$pkgname-$pkgver"
    python -m build --wheel --no-isolation
}

package() {
    cd "$pkgname-$pkgver"
    python -m installer --destdir="$pkgdir" dist/*.whl
}"""
    else:
        build_func = """build() {
    cd "$pkgname-$pkgver"
    make
}

package() {
    cd "$pkgname-$pkgver"
    make DESTDIR="$pkgdir" install
}"""

    pkgbuild_content = f"""# Maintainer: Prometheus Agent
pkgname={clean_pkgname}
pkgver={clean_ver}
pkgrel={pkgrel}
pkgdesc="{clean_desc}"
arch=('x86_64' 'aarch64')
url="{clean_url}"
license=('{clean_lic}')
depends=({dep_list})
makedepends=({make_list})
source=({src_val})
sha256sums=('SKIP')

{build_func}
"""

    return (
        f"📦 *فایل استاندارد آرچ‌لینوکس PKGBUILD تولید گردید:*\n\n"
        f"```bash\n{pkgbuild_content.strip()}\n```\n\n"
        f"💡 می‌توانید این فایل را با ابزار `github_create_or_update_file` مستقیماً در مخزن گیت‌هاب خود ذخیره یا برای AUR آماده کنید."
    )


@register_tool(
    name="github_generate_cmake",
    description="تولید فایل استاندارد و مدرن ساخت پروژه CMakeLists.txt با پیکربندی C++20، کتابخانه‌ها، فلگ‌های بهینه‌سازی و تارگت‌های نصب",
    category="github"
)
def github_generate_cmake(
    project_name: str,
    cpp_standard: str = "20",
    project_type: str = "executable",
    src_files: str = "src/main.cpp",
    include_dirs: str = "include",
    libraries: str = ""
) -> str:
    """
    :param project_name: نام پروژه (انگلیسی)
    :param cpp_standard: استاندارد سی‌پلاس‌پلاس ('17', '20', '23')
    :param project_type: نوع خروجی ('executable' فایل اجرایی، 'library' کتابخانه، 'shared' کتابخانه پویا)
    :param src_files: لیست فایل‌های سورس با فاصله (مانند src/main.cpp src/utils.cpp)
    :param include_dirs: مسیر هدرها (مانند include)
    :param libraries: کتابخانه‌های پیوندی با فاصله (مانند pthread OpenSSL::SSL)
    """
    clean_pname = re.sub(r"[^a-zA-Z0-9_\-]", "_", (project_name or "MyProject")).strip("_")
    std_num = "20" if cpp_standard not in ("11", "14", "17", "20", "23") else cpp_standard

    sources = " ".join(src_files.split()) if src_files else "src/main.cpp"
    ptype = (project_type or "executable").lower()

    if ptype in ("library", "static"):
        target_decl = f"add_library({clean_pname} STATIC {sources})"
    elif ptype in ("shared", "so", "dll"):
        target_decl = f"add_library({clean_pname} SHARED {sources})"
    else:
        target_decl = f"add_executable({clean_pname} {sources})"

    libs = libraries.strip()
    link_section = f"\ntarget_link_libraries({clean_pname} PRIVATE {libs})" if libs else ""

    inc_dir = include_dirs.strip() or "include"

    cmake_content = f"""cmake_minimum_required(VERSION 3.20)
project({clean_pname} VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD {std_num})
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Modern compiler hardening flags
if(MSVC)
    add_compile_options(/W4 /permissive-)
else()
    add_compile_options(-Wall -Wextra -Wpedantic -O2)
endif()

{target_decl}

target_include_directories({clean_pname} PUBLIC
    $<BUILD_INTERFACE:${{CMAKE_CURRENT_SOURCE_DIR}}/{inc_dir}>
    $<INSTALL_INTERFACE:include>
){link_section}

# Install configuration
include(GNUInstallDirs)
install(TARGETS {clean_pname}
    RUNTIME DESTINATION ${{CMAKE_INSTALL_BINDIR}}
    LIBRARY DESTINATION ${{CMAKE_INSTALL_LIBDIR}}
    ARCHIVE DESTINATION ${{CMAKE_INSTALL_LIBDIR}}
)
install(DIRECTORY {inc_dir}/ DESTINATION ${{CMAKE_INSTALL_INCLUDEDIR}} OPTIONAL)
"""

    return (
        f"🛠 *فایل مدرن CMakeLists.txt تولید گردید:*\n\n"
        f"```cmake\n{cmake_content.strip()}\n```\n\n"
        f"💡 می‌توانید این فایل را مستقیماً با دستور `github_create_or_update_file` در شاخه ریشه مخزن گیت‌هاب ذخیره کنید."
    )
