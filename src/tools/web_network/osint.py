"""
Advanced OSINT (Open Source Intelligence) & Digital Footprint Reconnaissance Engine.
Collects and correlates 100% public information across platforms, code repositories,
social networks, cryptographic identities, DNS/whois, IP infrastructure, phone carriers,
and deep web footprints.
"""

import asyncio
import hashlib
import html
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


# =========================================================================
# 1. Platform Probes (Asynchronous Zero-API Social & Identity Checks)
# =========================================================================

async def _check_github(username: str, client: Any) -> Optional[Dict[str, Any]]:
    clean = username.lstrip("@").strip()
    try:
        url = f"https://api.github.com/users/{clean}"
        headers = {"User-Agent": "PrometheusOSINT/3.0"}
        from src.core import config as _cfg
        token = getattr(_cfg, "GITHUB_TOKEN", "")
        if token and len(token) > 10:
            headers["Authorization"] = f"Bearer {token}"
        r = await client.get(url, headers=headers, timeout=3.5)
        if r.status_code == 200:
            d = r.json()
            return {
                "platform": "GitHub",
                "exists": True,
                "url": d.get("html_url") or f"https://github.com/{clean}",
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
        logger.debug(f"GitHub OSINT API check error: {e}")

    # Fallback to HTML profile scraping (resilient to API 504/403/rate limits)
    try:
        html_url = f"https://github.com/{clean}"
        h_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        hr = await client.get(html_url, headers=h_headers, timeout=4.0, follow_redirects=True)
        if hr.status_code == 200 and "Not Found" not in hr.text:
            soup = BeautifulSoup(hr.text, "html.parser")
            name_tag = soup.find("span", class_="p-name") or soup.find("span", class_="vcard-fullname")
            name_val = name_tag.get_text(strip=True) if name_tag else clean
            bio_tag = soup.find("div", class_="p-note") or soup.find("div", class_="user-profile-bio")
            bio_val = bio_tag.get_text(strip=True) if bio_tag else ""
            return {
                "platform": "GitHub",
                "exists": True,
                "url": html_url,
                "name": name_val,
                "bio": bio_val
            }
    except Exception as e:
        logger.debug(f"GitHub HTML fallback check error: {e}")
    return None


async def _check_gitlab(username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        url = f"https://gitlab.com/api/v4/users?username={username}"
        r = await client.get(url, headers={"User-Agent": "PrometheusOSINT/3.0"}, timeout=3.0)
        if r.status_code == 200:
            users = r.json()
            if users and isinstance(users, list) and len(users) > 0:
                u = users[0]
                return {
                    "platform": "GitLab",
                    "exists": True,
                    "url": u.get("web_url"),
                    "name": u.get("name") or "",
                    "bio": u.get("bio") or "",
                    "location": u.get("location") or ""
                }
    except Exception as e:
        logger.debug(f"GitLab OSINT check error: {e}")
    return None


async def _check_keybase(username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        url = f"https://keybase.io/_/api/1.0/user/lookup.json?usernames={username}"
        r = await client.get(url, headers={"User-Agent": "PrometheusOSINT/3.0"}, timeout=3.0)
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


async def _check_dockerhub(username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        url = f"https://hub.docker.com/v2/users/{username}/"
        r = await client.get(url, headers={"User-Agent": "PrometheusOSINT/3.0"}, timeout=3.0)
        if r.status_code == 200:
            d = r.json()
            if d.get("id") or d.get("username"):
                return {
                    "platform": "Docker Hub",
                    "exists": True,
                    "url": f"https://hub.docker.com/u/{username}",
                    "full_name": d.get("full_name") or "",
                    "location": d.get("location") or "",
                    "company": d.get("company") or ""
                }
    except Exception as e:
        logger.debug(f"DockerHub OSINT check error: {e}")
    return None


async def _check_devto(username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        url = f"https://dev.to/api/users/by_username?url={username}"
        r = await client.get(url, headers={"User-Agent": "PrometheusOSINT/3.0"}, timeout=3.0)
        if r.status_code == 200:
            d = r.json()
            if d.get("name") or d.get("username"):
                return {
                    "platform": "DEV Community",
                    "exists": True,
                    "url": f"https://dev.to/{username}",
                    "name": d.get("name") or "",
                    "bio": d.get("summary") or "",
                    "location": d.get("location") or ""
                }
    except Exception as e:
        logger.debug(f"DEV Community OSINT check error: {e}")
    return None


async def _check_hackernews(username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        url = f"https://hacker-news.firebaseio.com/v0/user/{username}.json"
        r = await client.get(url, headers={"User-Agent": "PrometheusOSINT/3.0"}, timeout=3.0)
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
    except Exception as e:
        logger.debug(f"HackerNews OSINT check error: {e}")
    return None


async def _check_telegram(username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        clean = username.lstrip("@")
        url = f"https://t.me/{clean}"
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3.0)
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
    except Exception as e:
        logger.debug(f"Telegram OSINT check error: {e}")
    return None


async def _check_reddit(username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        url = f"https://www.reddit.com/user/{username}/about.json"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PrometheusOSINT/3.0"}
        r = await client.get(url, headers=headers, timeout=3.0)
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
    except Exception as e:
        logger.debug(f"Reddit OSINT check error: {e}")
    return None


async def _check_twitter(username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        clean = username.lstrip("@").strip()
        url = f"https://x.com/{clean}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = await client.get(url, headers=headers, timeout=3.0, follow_redirects=True)
        if r.status_code == 200:
            m_title = re.search(r'<meta [^>]*property=[\"\']og:title[\"\'] [^>]*content=[\"\']([^\"\']+)[\"\']', r.text)
            if m_title and clean.lower() in m_title.group(1).lower():
                raw_title = html.unescape(m_title.group(1))
                name_match = re.search(r'^(.*?)\s*\(@' + re.escape(clean) + r'\)', raw_title, re.IGNORECASE)
                display_name = name_match.group(1).strip() if name_match else clean
                m_desc = re.search(r'<meta [^>]*property=[\"\']og:description[\"\'] [^>]*content=[\"\']([^\"\']+)[\"\']', r.text)
                bio = html.unescape(m_desc.group(1)).strip() if m_desc else ""
                return {
                    "platform": "Twitter / X",
                    "exists": True,
                    "url": f"https://x.com/{clean}",
                    "name": display_name,
                    "bio": bio[:150]
                }
    except Exception as e:
        logger.debug(f"Twitter OSINT check error: {e}")
    return None


async def _check_gravatar(email_or_username: str, client: Any) -> Optional[Dict[str, Any]]:
    try:
        email_clean = email_or_username.lower().strip()
        h = hashlib.md5(email_clean.encode("utf-8")).hexdigest()
        url = f"https://en.gravatar.com/{h}.json"
        r = await client.get(url, headers={"User-Agent": "PrometheusOSINT/3.0"}, timeout=3.0)
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
    except Exception as e:
        logger.debug(f"Gravatar OSINT check error: {e}")
    return None


# =========================================================================
# 2. IP & Network Infrastructure OSINT
# =========================================================================

@register_tool(
    name="osint_ip_intelligence",
    description="استعلام فوق‌پیشرفته و هوشمند IP، موقعیت جغرافیایی دقیق، ارائه‌دهنده (ISP)، سازمان، شماره AS، تشخیص سرور/دیتاسنتر/پروکسی/VPN و رکوردهای معکوس",
    category="network"
)
async def osint_ip_intelligence(ip: str) -> str:
    """
    :param ip: آدرس آی‌پی نسخه ۴ یا ۶ مورد نظر برای استعلام (مانند: '1.1.1.1', '185.143.232.1')
    """
    clean_ip = (ip or "").strip()
    # Extract IP if surrounded by text or URL
    ip_m = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", clean_ip)
    if ip_m:
        clean_ip = ip_m.group(0)

    if not clean_ip:
        return "❌ آدرس IP معتبری برای استعلام وارد نشده است."

    cache_key = f"OSINT_IP_{clean_ip}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached

    url = f"http://ip-api.com/json/{clean_ip}?fields=status,message,country,countryCode,regionName,city,zip,lat,lon,timezone,isp,org,as,hosting,proxy,query"
    try:
        async with shared_client_ctx("web") as client:
            r = await client.get(url, timeout=7.0)
            if r.status_code == 200:
                d = r.json()
                if d.get("status") == "success":
                    is_hosting = "بله (Datacenter / Cloud Server)" if d.get("hosting") else "خیر (Residential / Mobile)"
                    is_proxy = "بله (Proxy / VPN detected)" if d.get("proxy") else "خیر (Direct)"

                    # Reverse DNS PTR check
                    reverse_host = "نامشخص"
                    try:
                        import socket
                        reverse_host = socket.gethostbyaddr(clean_ip)[0]
                    except Exception:
                        pass

                    res = (
                        f"🌐 *شناسنامه امنیتی و اطلاعاتی آی‌پی (IP Intelligence)*\n"
                        f"• *آدرس آی‌پی*: `{d.get('query', clean_ip)}`\n"
                        f"• *کشور*: `{d.get('country', '—')}` (`{d.get('countryCode', '')}`)\n"
                        f"• *استان / شهر*: `{d.get('regionName', '—')}` / `{d.get('city', '—')}`\n"
                        f"• *منطقه زمانی*: `{d.get('timezone', '—')}` | مختصات: `{d.get('lat')}, {d.get('lon')}`\n"
                        f"• *ارائه‌دهنده (ISP)*: `{d.get('isp', '—')}`\n"
                        f"• *سازمان*: `{d.get('org', '—')}`\n"
                        f"• *سیستم خودمختار (ASN)*: `{d.get('as', '—')}`\n"
                        f"• *هاستینگ / سرور ابری*: `{is_hosting}`\n"
                        f"• *پروکسی / فیلترشکن*: `{is_proxy}`\n"
                        f"• *نام هاست معکوس (PTR)*: `{reverse_host}`"
                    )
                    await database.kv_set_cache_async(cache_key, res, expiration_ttl=3600)
                    return res
                else:
                    return f"❌ استعلام IP با شکست مواجه شد: {d.get('message', 'آدرس نامعتبر')}"
    except Exception as e:
        logger.debug(f"IP intelligence error: {e}")

    return f"❌ خطای شبکه در دریافت اطلاعات آی‌پی {clean_ip}."


# =========================================================================
# 3. Domain & DNS Intelligence
# =========================================================================

@register_tool(
    name="osint_domain_dns",
    description="استعلام عمیق دامنه و سرور: رکوردهای DNS (شامل A, AAAA, MX, TXT/SPF/DMARC, NS) و رجیسترار از طریق پروتکل امن DoH و RDAP",
    category="network"
)
async def osint_domain_dns(domain: str) -> str:
    """
    :param domain: نام دامنه یا آدرس اینترنتی (مانند: 'telegram.org', 'google.com', 'digikala.com')
    """
    raw_d = (domain or "").strip()
    clean_d = re.sub(r"^https?://", "", raw_d).split("/")[0].split(":")[0].strip()
    if not clean_d or "." not in clean_d:
        return "❌ لطفاً یک نام دامنه معتبر وارد فرمایید."

    cache_key = f"OSINT_DNS_{clean_d.lower()}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached

    records: Dict[str, List[str]] = {}
    try:
        async with shared_client_ctx("web") as client:
            # Cloudflare DoH (DNS-over-HTTPS)
            for rtype in ["A", "AAAA", "MX", "NS", "TXT"]:
                try:
                    doh_url = f"https://cloudflare-dns.com/dns-query?name={clean_d}&type={rtype}"
                    r = await client.get(doh_url, headers={"accept": "application/dns-json"}, timeout=5.0)
                    if r.status_code == 200:
                        ans = r.json().get("Answer", [])
                        records[rtype] = [a.get("data", "").strip() for a in ans if a.get("data")]
                except Exception:
                    pass

            # RDAP lookup for registration info
            registrar = "نامشخص"
            events = {}
            try:
                r_rdap = await client.get(f"https://rdap.org/domain/{clean_d}", headers={"accept": "application/json"}, timeout=5.0)
                if r_rdap.status_code == 200:
                    rdap_data = r_rdap.json()
                    for ent in rdap_data.get("entities", []):
                        if "registrar" in ent.get("roles", []):
                            vcard = ent.get("vcardArray", [])
                            if len(vcard) > 1:
                                for item in vcard[1]:
                                    if item[0] == "fn":
                                        registrar = item[3]
                    for ev in rdap_data.get("events", []):
                        action = ev.get("eventAction")
                        date_val = (ev.get("eventDate") or "")[:10]
                        if action and date_val:
                            events[action] = date_val
            except Exception:
                pass

        lines = [
            f"🔎 *شناسنامه فنی و رکوردهای دامنه (Domain OSINT)*",
            f"• *دامنه*: `{clean_d}`",
            f"• *ثبت‌کننده (Registrar)*: `{registrar}`"
        ]
        if events.get("registration"):
            lines.append(f"• *تاریخ ثبت اولیه*: `{events['registration']}`")
        if events.get("expiration"):
            lines.append(f"• *تاریخ انقضا*: `{events['expiration']}`")

        lines.append("\n📡 *رکوردهای DNS فعال:*")
        if records.get("A"):
            lines.append(f"• *IPv4 (A)*: " + ", ".join(f"`{ip}`" for ip in records["A"][:4]))
        if records.get("AAAA"):
            lines.append(f"• *IPv6 (AAAA)*: " + ", ".join(f"`{ip}`" for ip in records["AAAA"][:2]))
        if records.get("MX"):
            lines.append(f"• *سرورهای ایمیل (MX)*: " + ", ".join(f"`{mx}`" for mx in records["MX"][:3]))
        if records.get("NS"):
            lines.append(f"• *نیم‌سرورها (NS)*: " + ", ".join(f"`{ns}`" for ns in records["NS"][:3]))
        if records.get("TXT"):
            # Filter SPF/DMARC/Verification records
            sec_txt = [t for t in records["TXT"] if any(k in t.lower() for k in ["v=spf", "v=dmarc", "google-site", "verify"])]
            chosen_txt = sec_txt if sec_txt else records["TXT"]
            for t in chosen_txt[:3]:
                clean_t = t.replace('"', '')[:80]
                lines.append(f"• *رکورد امنیتی*: `{clean_t}`")

        out = "\n".join(lines)
        await database.kv_set_cache_async(cache_key, out, expiration_ttl=3600)
        return out
    except Exception as e:
        logger.error(f"Domain DNS OSINT error: {e}")

    return f"❌ خطای شبکه در استعلام دامنه {clean_d}."


# =========================================================================
# 4. Phone Number & Carrier Intelligence
# =========================================================================

@register_tool(
    name="osint_phone_intelligence",
    description="تحلیل و شناسایی شماره تلفن همراه و ثابت، تشخیص اپراتور (همراه اول، ایرانسل، رایتل، شاتل)، استان و فرمت استاندارد بین‌المللی E.164",
    category="network"
)
async def osint_phone_intelligence(phone: str) -> str:
    """
    :param phone: شماره تلفن یا موبایل با پیش‌شماره یا بدون آن (مانند: '09121234567', '+989351234567', '+14155552671')
    """
    raw_p = (phone or "").strip()
    digits = re.sub(r"[^\d+]", "", raw_p)
    if not digits:
        return "❌ شماره تلفن معتبری وارد نشده است."

    # Standardize Iranian phone format
    is_iranian = False
    clean_ir = digits
    if clean_ir.startswith("+98"):
        clean_ir = "0" + clean_ir[3:]
        is_iranian = True
    elif clean_ir.startswith("0098"):
        clean_ir = "0" + clean_ir[4:]
        is_iranian = True
    elif clean_ir.startswith("98"):
        clean_ir = "0" + clean_ir[2:]
        is_iranian = True
    elif clean_ir.startswith("09") and len(clean_ir) == 11:
        is_iranian = True

    if is_iranian and len(clean_ir) == 11 and clean_ir.startswith("09"):
        prefix = clean_ir[:4]
        operator_info = {
            # MCI (Hamrah-e Avval)
            "0910": ("همراه اول (MCI)", "دائمی و اعتباری سراسری"),
            "0911": ("همراه اول (MCI)", "استان‌های شمالی (مازندران، گلستان، گیلان)"),
            "0912": ("همراه اول (MCI)", "تهران، البرز، قزوین، زنجان، سمنان، قم"),
            "0913": ("همراه اول (MCI)", "اصفهان، یزد، چهارمحال و بختیاری، کرمان"),
            "0914": ("همراه اول (MCI)", "آذربایجان شرقی، آذربایجان غربی، اردبیل"),
            "0915": ("همراه اول (MCI)", "خراسان رضوی، خراسان شمالی، خراسان جنوبی، سیستان و بلوچستان"),
            "0916": ("همراه اول (MCI)", "خوزستان، لرستان، فارس"),
            "0917": ("همراه اول (MCI)", "فارس، کهگیلویه و بویراحمد، بوشهر، هرمزگان"),
            "0918": ("همراه اول (MCI)", "همدان، کرمانشاه، کردستان، ایلام"),
            "0919": ("همراه اول (MCI)", "تهران، البرز، قم، سمنان، قزوین (اعتباری)"),
            "0990": ("همراه اول (MCI)", "اعتباری سراسری"),
            "0991": ("همراه اول (MCI)", "اعتباری و دائمی سراسری"),
            "0992": ("همراه اول (MCI)", "اعتباری سراسری"),
            "0993": ("همراه اول (MCI)", "اعتباری سراسری"),
            "0994": ("همراه اول (MCI)", "اعتباری سراسری"),
            # Irancell
            "0930": ("ایرانسل (MTN Irancell)", "اعتباری و دائمی سراسری"),
            "0933": ("ایرانسل (MTN Irancell)", "اعتباری و دائمی سراسری"),
            "0935": ("ایرانسل (MTN Irancell)", "اعتباری و دائمی سراسری"),
            "0936": ("ایرانسل (MTN Irancell)", "اعتباری و دائمی سراسری"),
            "0937": ("ایرانسل (MTN Irancell)", "اعتباری و دائمی سراسری"),
            "0938": ("ایرانسل (MTN Irancell)", "اعتباری و دائمی سراسری"),
            "0939": ("ایرانسل (MTN Irancell)", "اعتباری و دائمی سراسری"),
            "0901": ("ایرانسل (MTN Irancell)", "سراسری"),
            "0902": ("ایرانسل (MTN Irancell)", "سراسری"),
            "0903": ("ایرانسل (MTN Irancell)", "سراسری"),
            "0904": ("ایرانسل (MTN Irancell)", "سیم‌کارت کودک و نوجوان"),
            "0905": ("ایرانسل (MTN Irancell)", "سراسری"),
            # RighTel
            "0920": ("رایتل (RighTel)", "دائمی سراسری"),
            "0921": ("رایتل (RighTel)", "اعتباری و دائمی"),
            "0922": ("رایتل (RighTel)", "اعتباری"),
            "0923": ("رایتل (RighTel)", "اعتباری"),
            # Shatel Mobile
            "0998": ("شاتل موبایل (Shatel Mobile)", "اپراتور مجازی MVNO نسل ۴"),
            # Taliya
            "0932": ("تالیا (Taliya)", "اعتباری سراسری"),
            # Samantel
            "0999": ("سامانتل (Samantel)", "اپراتور مجازی MVNO"),
        }
        op_data = operator_info.get(prefix) or ("اپراتور ایرانی معتبر", "سراسری")
        e164_fmt = "+98" + clean_ir[1:]

        return (
            f"📱 *تحلیل و اطلاعات شماره تلفن (Phone Intelligence)*\n"
            f"• *شماره ورودی*: `{raw_p}`\n"
            f"• *فرمت استاندارد بین‌المللی (E.164)*: `{e164_fmt}`\n"
            f"• *کشور*: `ایران (Iran)` 🇮🇷\n"
            f"• *اپراتور مخابراتی*: `{op_data[0]}`\n"
            f"• *نوع خط و توزیع منطقه‌ای*: `{op_data[1]}`\n"
            f"• *وضعیت اعتبار ساختاری*: `تأیید شده (Valid Structure)`"
        )

    # General International Analysis
    return (
        f"📱 *اطلاعات شماره بین‌المللی*\n"
        f"• *شماره*: `{digits}`\n"
        f"• *طول ارقام*: `{len(digits)} رقم`\n"
        f"• *وضعیت ساختاری*: `شماره خط خارجی یا ثابت`"
    )


# =========================================================================
# 5. Master Person & Social Dossier Engine
# =========================================================================

@register_tool(
    name="osint_person_dossier",
    description="موتور جامع شناسایی هویت (OSINT): استعلام چندبعدی اشخاص، یوزرنیم، ایمیل، آی‌پی، دامنه و تلفن در کلیه پلتفرم‌های عمومی و فضای وب",
    category="network"
)
async def osint_person_dossier(
    target: str,
    target_type: str = "auto",
    context_hint: str = ""
) -> str:
    """
    :param target: شناسه، نام کاربری (یوزرنیم)، نام و نام‌خانوادگی، ایمیل، شماره تلفن یا آی‌پی
    :param target_type: نوع هدف ('username', 'name', 'email', 'ip', 'domain', 'phone', 'auto')
    :param context_hint: اطلاعات زمینه، تخصص، شرکت یا شهر برای جستجوی دقیق‌تر
    """
    raw_target = str(target or "").strip()
    if not raw_target:
        return "❌ لطفاً نام، نام کاربری، ایمیل یا نشانی هدف را وارد کنید."

    ttype = (target_type or "auto").lower()

    # Smart Auto-Detection & Cross-Delegation
    if ttype == "auto":
        if re.search(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", raw_target):
            return await osint_ip_intelligence(raw_target)
        if re.search(r"^(?:\+?98|0)9\d{9}$", raw_target):
            return await osint_phone_intelligence(raw_target)
        if re.search(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", raw_target) and "@" not in raw_target:
            return await osint_domain_dns(raw_target)
        if "@" in raw_target and "." in raw_target.split("@")[-1]:
            ttype = "email"
        elif " " in raw_target:
            ttype = "name"
        else:
            ttype = "username"

    clean_uname = raw_target.lstrip("@").strip()
    cache_key = f"OSINT_DOSSIER_V2_{clean_uname.lower()}_{ttype}"
    cached = await database.kv_get_cache_async(cache_key)
    if cached:
        return cached

    # Parallel Probing Across Developer, Social & Security Networks
    probe_results = []
    try:
        async with shared_client_ctx("api") as client:
            tasks = [
                _check_github(clean_uname, client),
                _check_reddit(clean_uname, client),
                _check_twitter(clean_uname, client),
                _check_hackernews(clean_uname, client),
                _check_gravatar(raw_target if ttype == "email" else clean_uname, client),
                _check_gitlab(clean_uname, client),
                _check_keybase(clean_uname, client),
                _check_dockerhub(clean_uname, client),
                _check_devto(clean_uname, client),
                _check_telegram(clean_uname, client),
            ]

            done = await asyncio.gather(*tasks, return_exceptions=True)
            for res in done:
                if isinstance(res, dict) and res.get("exists"):
                    probe_results.append(res)
    except Exception as e:
        logger.warning(f"OSINT probe error: {e}")

    # Deep Web Footprint & Public Mentions
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

    # Synthesis of Dossier Report
    sections = [
        f"🕵️‍♂️ *پرونده شناسایی هویت دیجیتال (Supercharged OSINT Dossier)*",
        f"• *هدف مورد کاوش*: `{raw_target}`",
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
        sections.append("\n⚠️ *حساب مستقیمی با این شناسه در پلتفرم‌های اصلی برنامه‌نویسی و شبکه‌های عمومی یافت نشد.*")

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
    if probe_results or web_findings:
        await database.kv_set_cache_async(cache_key, final_report, expiration_ttl=1800)
    return final_report
