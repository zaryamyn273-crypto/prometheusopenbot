"""
Advanced OSINT (Open Source Intelligence) & Digital Footprint Reconnaissance Engine.
Collects and correlates 100% public information across platforms, code repositories,
social networks, cryptographic identities, and deep web footprints.
"""

import asyncio
import hashlib
import json
import logging
import re
import urllib.parse
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup
from src.core import database
from src.core.http import shared_client_ctx
from src.tools.registry import register_tool

logger = logging.getLogger(__name__)


async def _check_github(username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        url = f"https://api.github.com/users/{username}"
        headers = {"User-Agent": "PrometheusOSINT/1.0"}
        from src.core import config as _cfg
        token = getattr(_cfg, "GITHUB_TOKEN", "")
        if token and len(token) > 10:
            headers["Authorization"] = f"Bearer {token}"
        r = await client.get(url, headers=headers, timeout=6.0)
        if r.status_code == 200:
            d = r.json()
            return {
                "platform": "GitHub",
                "exists": True,
                "url": d.get("html_url"),
                "name": d.get("name") or "",
                "bio": d.get("bio") or "",
                "company": d.get("company") or "",
                "blog": d.get("blog") or "",
                "location": d.get("location") or "",
                "email": d.get("email") or "",
                "public_repos": d.get("public_repos", 0),
                "followers": d.get("followers", 0),
                "created_at": (d.get("created_at") or "")[:10]
            }
    except Exception as e:
        logger.debug(f"GitHub OSINT check error: {e}")
    return None


async def _check_keybase(username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        url = f"https://keybase.io/_/api/1.0/user/lookup.json?usernames={username}"
        r = await client.get(url, headers={"User-Agent": "PrometheusOSINT/1.0"}, timeout=6.0)
        if r.status_code == 200:
            d = r.json()
            them = (d.get("them") or [])
            if them and them[0]:
                user_obj = them[0]
                profile = user_obj.get("profile") or {}
                proofs = user_obj.get("proofs_summary", {}).get("all", [])
                verified_services = []
                for p in proofs:
                    stype = p.get("proof_type")
                    sval = p.get("nametag")
                    if stype and sval:
                        verified_services.append(f"{stype}: {sval}")
                return {
                    "platform": "Keybase (هویت رمزنگاری‌شده)",
                    "exists": True,
                    "url": f"https://keybase.io/{username}",
                    "full_name": profile.get("full_name") or "",
                    "bio": profile.get("bio") or "",
                    "location": profile.get("location") or "",
                    "verified_services": verified_services
                }
    except Exception as e:
        logger.debug(f"Keybase check error: {e}")
    return None


async def _check_hackernews(username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        url = f"https://hacker-news.firebaseio.com/v0/user/{username}.json"
        r = await client.get(url, headers={"User-Agent": "PrometheusOSINT/1.0"}, timeout=5.0)
        if r.status_code == 200:
            d = r.json()
            if d and isinstance(d, dict) and d.get("id"):
                return {
                    "platform": "HackerNews",
                    "exists": True,
                    "url": f"https://news.ycombinator.com/user?id={username}",
                    "karma": d.get("karma", 0),
                    "about": re.sub(r"<[^>]+>", " ", d.get("about") or "")[:150].strip()
                }
    except Exception:
        pass
    return None


async def _check_telegram(username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        clean = username.lstrip("@")
        url = f"https://t.me/{clean}"
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5.0)
        if r.status_code == 200 and "tgme_page" in r.text:
            soup = BeautifulSoup(r.text, "html.parser")
            title_tag = soup.find("div", class_="tgme_page_title")
            desc_tag = soup.find("div", class_="tgme_page_description")
            if title_tag and title_tag.get_text(strip=True):
                title = title_tag.get_text(strip=True)
                desc = desc_tag.get_text(strip=True) if desc_tag else ""
                return {
                    "platform": "Telegram",
                    "exists": True,
                    "url": f"https://t.me/{clean}",
                    "title": title,
                    "description": desc[:200]
                }
    except Exception:
        pass
    return None


async def _check_reddit(username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        url = f"https://www.reddit.com/user/{username}/about.json"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = await client.get(url, headers=headers, timeout=5.0)
        if r.status_code == 200:
            data = r.json().get("data", {})
            if data and data.get("name"):
                return {
                    "platform": "Reddit",
                    "exists": True,
                    "url": f"https://reddit.com/user/{username}",
                    "total_karma": data.get("total_karma", 0),
                    "link_karma": data.get("link_karma", 0),
                    "comment_karma": data.get("comment_karma", 0)
                }
    except Exception:
        pass
    return None


async def _check_gravatar(email_or_username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        email_clean = email_or_username.lower().strip()
        h = hashlib.md5(email_clean.encode("utf-8")).hexdigest()
        url = f"https://en.gravatar.com/{h}.json"
        r = await client.get(url, headers={"User-Agent": "PrometheusOSINT/1.0"}, timeout=5.0)
        if r.status_code == 200:
            entries = r.json().get("entry", [])
            if entries:
                e = entries[0]
                return {
                    "platform": "Gravatar",
                    "exists": True,
                    "url": e.get("profileUrl", f"https://gravatar.com/{h}"),
                    "display_name": e.get("displayName") or "",
                    "location": e.get("currentLocation") or "",
                    "about": e.get("aboutMe") or ""
                }
    except Exception:
        pass
    return None


@register_tool(
    name="osint_person_dossier",
    description="جستجوی عمیق و جمع‌آوری پرونده شناسایی هویت (OSINT) بر اساس نام، نام‌کاربری، ایمیل یا ردپای دیجیتال در شبکه‌های اجتماعی، گیت‌هاب، سرویس‌های رمزنگاری، ردیت و صفحات وب",
    category="network"
)
async def osint_person_dossier(
    target: str,
    target_type: str = "auto",
    context_hint: str = ""
) -> str:
    """
    :param target: شناسه، نام کاربری (یوزرنیم)، نام و نام‌خانوادگی، ایمیل یا آیدی مورد نظر
    :param target_type: نوع هدف ('username', 'name', 'email', 'auto')
    :param context_hint: اطلاعات زمینه، شهر، تخصص یا شرکت برای تطبیق دقیق‌تر نتایج
    """
    raw_target = str(target or "").strip()
    if not raw_target:
        return "❌ لطفاً نام، نام کاربری یا ایمیل هدف را وارد کنید."

    clean_uname = raw_target.lstrip("@").strip()
    cache_key = f"OSINT_DOSSIER_{clean_uname.lower()}_{target_type}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached

    ttype = (target_type or "auto").lower()
    is_email = "@" in raw_target and "." in raw_target.split("@")[-1]
    if is_email and ttype == "auto":
        ttype = "email"
    elif " " in raw_target and ttype == "auto":
        ttype = "name"
    elif ttype == "auto":
        ttype = "username"

    # Step 1: Parallel Social & Identity Probing (Fast Async Checks)
    probe_results = []
    try:
        async with shared_client_ctx("api") as client:
            tasks = [
                _check_github(clean_uname, client),
                _check_keybase(clean_uname, client),
                _check_telegram(clean_uname, client),
                _check_reddit(clean_uname, client),
                _check_hackernews(clean_uname, client),
            ]
            if is_email:
                tasks.append(_check_gravatar(raw_target, client))
            else:
                tasks.append(_check_gravatar(clean_uname, client))

            done = await asyncio.gather(*tasks, return_exceptions=True)
            for res in done:
                if isinstance(res, dict) and res.get("exists"):
                    probe_results.append(res)
    except Exception as e:
        logger.warning(f"OSINT probe error: {e}")

    # Step 2: Deep Targeted Web Dorking via Tavily / Web Search
    web_findings = []
    try:
        from src.tools.web_network import tavily_search_raw, web_search
        dork_query = f"\"{raw_target}\""
        if context_hint:
            dork_query += f" {context_hint}"
        dork_query += " (developer OR linkedin OR portfolio OR github OR twitter OR engineer)"

        tv_res = await tavily_search_raw(dork_query, max_results=4, search_depth="advanced")
        if tv_res and tv_res.get("results"):
            for it in tv_res["results"][:4]:
                title = it.get("title", "")
                url = it.get("url", "")
                content = (it.get("content") or "")[:200]
                web_findings.append(f"• [{title}]({url}):\n  _{content}_")
        else:
            fb = await web_search(dork_query, max_results=4)
            if fb and "یافت نشد" not in fb:
                web_findings.append(fb[:1200])
    except Exception as e:
        logger.debug(f"OSINT web dorking error: {e}")

    # Step 3: Synthesis of Dossier Report
    sections = [
        f"🕵️‍♂️ *پرونده شناسایی هویت عمومی (OSINT Dossier)*",
        f"• *هدف*: `{raw_target}`",
        f"• *دسته‌بندی تحلیل*: `{ttype.upper()}`" + (f" (زمینه: {context_hint})" if context_hint else "")
    ]

    # Verified Platform Profiles
    if probe_results:
        sections.append("\n🌐 *حساب‌های عمومی و پلتفرم‌های تأییدشده:*")
        for p in probe_results:
            p_name = p.get("platform")
            p_url = p.get("url")
            extra_bits = []
            if p.get("name") or p.get("full_name") or p.get("display_name"):
                extra_bits.append(f"نام: `{p.get('name') or p.get('full_name') or p.get('display_name')}`")
            if p.get("bio") or p.get("about") or p.get("description"):
                desc = (p.get("bio") or p.get("about") or p.get("description") or "").replace("\n", " ")[:120]
                extra_bits.append(f"بیو: «{desc}»")
            if p.get("company"):
                extra_bits.append(f"شرکت: `{p.get('company')}`")
            if p.get("location"):
                extra_bits.append(f"موقعیت: `{p.get('location')}`")
            if p.get("public_repos") is not None:
                extra_bits.append(f"مخازن گیت: *{p.get('public_repos')}*")
            if p.get("followers"):
                extra_bits.append(f"دنبال‌کنندگان: *{p.get('followers'):,}*")
            if p.get("karma") is not None:
                extra_bits.append(f"کارما: *{p.get('karma'):,}*")
            if p.get("verified_services"):
                extra_bits.append("سرویس‌های متصل: " + ", ".join(f"`{s}`" for s in p["verified_services"][:3]))

            details_str = " | ".join(extra_bits) if extra_bits else "حساب فعال عمومی"
            sections.append(f"• [{p_name}]({p_url}): {details_str}")
    else:
        sections.append("\n⚠️ *حساب مستقیمی با این شناسه در پلتفرم‌های کلیدی یافت نشد.*")

    # Deep Web Footprint & Public Mentions
    if web_findings:
        sections.append("\n🔍 *ردپای عمومی و صفحات مرتبط در وب:*")
        sections.extend(web_findings)

    # Footprint Exposure Level
    total_signals = len(probe_results) + len(web_findings)
    if total_signals >= 5:
        risk_label = "🔴 گسترده و عمومی (High Visibility)"
    elif total_signals >= 2:
        risk_label = "🟡 متوسط (Moderate Visibility)"
    else:
        risk_label = "🟢 محدود (Low Footprint)"
    sections.append(f"\n📊 *سطح ردپای دیجیتال عمومی*: {risk_label}")

    final_report = "\n".join(sections)
    await database.kv_set_cache_async(cache_key, final_report, expiration_ttl=1800)
    return final_report
