import asyncio
import datetime
import json
import logging
import re
import time
from typing import Dict, Any, List, Optional, Tuple

try:
    import pytz
    TEHRAN_TZ = pytz.timezone("Asia/Tehran")
except Exception:
    pytz = None
    TEHRAN_TZ = datetime.timezone(datetime.timedelta(hours=3, minutes=30))

try:
    import jdatetime
except Exception:
    jdatetime = None

from src.core import database
from src.core.config import ADMIN_ID
from src.core.security import sanitize_output
from src.utils import telegram_formatter

logger = logging.getLogger(__name__)

# Global Background Task Handle
_SCHEDULER_TASK: Optional[asyncio.Task] = None


# ==========================================
# 0. International Timezone Recognition & Mapping
# ==========================================

TIMEZONE_ALIASES: Dict[str, str] = {
    # Iran
    "tehran": "Asia/Tehran", "تهران": "Asia/Tehran", "iran": "Asia/Tehran", "ایران": "Asia/Tehran",
    "irst": "Asia/Tehran", "irdt": "Asia/Tehran",
    # UK & Ireland
    "london": "Europe/London", "لندن": "Europe/London", "uk": "Europe/London",
    "انگلیس": "Europe/London", "بریتانیا": "Europe/London",
    "gmt": "UTC", "utc": "UTC", "bst": "Europe/London",
    "dublin": "Europe/Dublin", "دوبلین": "Europe/Dublin",
    # Central & Western Europe
    "paris": "Europe/Paris", "پاریس": "Europe/Paris", "france": "Europe/Paris", "فرانسه": "Europe/Paris",
    "berlin": "Europe/Berlin", "برلین": "Europe/Berlin", "germany": "Europe/Berlin", "آلمان": "Europe/Berlin",
    "frankfurt": "Europe/Berlin", "فرانکفورت": "Europe/Berlin",
    "amsterdam": "Europe/Amsterdam", "آمستردام": "Europe/Amsterdam",
    "rome": "Europe/Rome", "رم": "Europe/Rome", "italy": "Europe/Rome", "ایتالیا": "Europe/Rome",
    "madrid": "Europe/Madrid", "مادرید": "Europe/Madrid", "spain": "Europe/Madrid", "اسپانیا": "Europe/Madrid",
    "vienna": "Europe/Vienna", "وین": "Europe/Vienna", "austria": "Europe/Vienna", "اتریش": "Europe/Vienna",
    "brussels": "Europe/Brussels", "بروکسل": "Europe/Brussels",
    "zurich": "Europe/Zurich", "زوریخ": "Europe/Zurich", "switzerland": "Europe/Zurich", "سوئیس": "Europe/Zurich",
    "cet": "Europe/Berlin", "cest": "Europe/Berlin",
    # Eastern Europe & Turkey
    "istanbul": "Europe/Istanbul", "استانبول": "Europe/Istanbul", "turkey": "Europe/Istanbul", "ترکیه": "Europe/Istanbul",
    "moscow": "Europe/Moscow", "مسکو": "Europe/Moscow", "russia": "Europe/Moscow", "روسیه": "Europe/Moscow",
    "kyiv": "Europe/Kyiv", "کیف": "Europe/Kyiv", "warsaw": "Europe/Warsaw", "ورشو": "Europe/Warsaw",
    # Middle East
    "dubai": "Asia/Dubai", "دبی": "Asia/Dubai", "دوبی": "Asia/Dubai", "uae": "Asia/Dubai", "امارات": "Asia/Dubai",
    "abu dhabi": "Asia/Dubai", "ابوظبی": "Asia/Dubai",
    "riyadh": "Asia/Riyadh", "ریاض": "Asia/Riyadh", "saudi": "Asia/Riyadh", "عربستان": "Asia/Riyadh",
    "doha": "Asia/Qatar", "دوحه": "Asia/Qatar", "qatar": "Asia/Qatar", "قطر": "Asia/Qatar",
    "kuwait": "Asia/Kuwait", "کویت": "Asia/Kuwait",
    "muscat": "Asia/Muscat", "مسقط": "Asia/Muscat", "oman": "Asia/Muscat", "عمان": "Asia/Muscat",
    "baghdad": "Asia/Baghdad", "بغداد": "Asia/Baghdad", "iraq": "Asia/Baghdad", "عراق": "Asia/Baghdad",
    "beirut": "Asia/Beirut", "بیروت": "Asia/Beirut", "lebanon": "Asia/Beirut", "لبنان": "Asia/Beirut",
    # North America
    "new york": "America/New_York", "newyork": "America/New_York", "نیویورک": "America/New_York",
    "ny": "America/New_York", "est": "America/New_York", "edt": "America/New_York",
    "eastern": "America/New_York", "washington": "America/New_York", "واشنگتن": "America/New_York",
    "los angeles": "America/Los_Angeles", "losangeles": "America/Los_Angeles", "لس آنجلس": "America/Los_Angeles",
    "la": "America/Los_Angeles", "pst": "America/Los_Angeles", "pdt": "America/Los_Angeles",
    "pacific": "America/Los_Angeles", "san francisco": "America/Los_Angeles", "سانفرانسیسکو": "America/Los_Angeles",
    "chicago": "America/Chicago", "شیکاگو": "America/Chicago", "cst": "America/Chicago", "cdt": "America/Chicago",
    "central": "America/Chicago", "denver": "America/Denver", "دنور": "America/Denver",
    "toronto": "America/Toronto", "تورنتو": "America/Toronto", "vancouver": "America/Vancouver", "ونکوور": "America/Vancouver",
    "canada": "America/Toronto", "کانادا": "America/Toronto",
    # Asia & Pacific
    "tokyo": "Asia/Tokyo", "توکیو": "Asia/Tokyo", "japan": "Asia/Tokyo", "ژاپن": "Asia/Tokyo", "jst": "Asia/Tokyo",
    "seoul": "Asia/Seoul", "سئول": "Asia/Seoul", "korea": "Asia/Seoul", "کره": "Asia/Seoul",
    "shanghai": "Asia/Shanghai", "شانگهای": "Asia/Shanghai", "beijing": "Asia/Shanghai", "پکن": "Asia/Shanghai",
    "china": "Asia/Shanghai", "چین": "Asia/Shanghai",
    "hong kong": "Asia/Hong_Kong", "هنگ کنگ": "Asia/Hong_Kong",
    "singapore": "Asia/Singapore", "سنگاپور": "Asia/Singapore",
    "bangkok": "Asia/Bangkok", "بانکوک": "Asia/Bangkok", "thailand": "Asia/Bangkok", "تایلند": "Asia/Bangkok",
    "delhi": "Asia/Kolkata", "دهلی": "Asia/Kolkata", "mumbai": "Asia/Kolkata", "بمبئی": "Asia/Kolkata",
    "india": "Asia/Kolkata", "هند": "Asia/Kolkata", "ist": "Asia/Kolkata",
    "sydney": "Australia/Sydney", "سیدنی": "Australia/Sydney", "melbourne": "Australia/Melbourne", "ملبورن": "Australia/Melbourne",
    "australia": "Australia/Sydney", "استرالیا": "Australia/Sydney",
    "auckland": "Pacific/Auckland", "اوکلند": "Pacific/Auckland", "new zealand": "Pacific/Auckland",
}


class ScheduleResult(tuple):
    """
    Subclass of 5-element tuple for 100% backward compatibility:
    (next_run_ts, is_recurring, cron_expr, interval_seconds, human_desc)
    plus .timezone property.
    """
    def __new__(cls, next_run_ts: float, is_recurring: bool, cron_expr: str, interval_sec: int, human_desc: str, timezone: str = "UTC"):
        return super().__new__(cls, (next_run_ts, is_recurring, cron_expr, interval_sec, human_desc))

    def __init__(self, next_run_ts: float, is_recurring: bool, cron_expr: str, interval_sec: int, human_desc: str, timezone: str = "UTC"):
        self.next_run_ts = next_run_ts
        self.is_recurring = is_recurring
        self.cron_expr = cron_expr
        self.interval_sec = interval_sec
        self.human_desc = human_desc
        self.timezone = timezone


def detect_timezone_in_text(text: str) -> Optional[str]:
    """Detects explicit city, country, or timezone abbreviation inside schedule text."""
    if not text:
        return None
    clean = text.lower()
    # 1. Phrases like "به وقت لندن", "به افق تهران", "London time", "UTC"
    sorted_aliases = sorted(TIMEZONE_ALIASES.keys(), key=len, reverse=True)
    for alias in sorted_aliases:
        if f"به وقت {alias}" in clean or f"به افق {alias}" in clean or f"{alias} time" in clean or f"{alias} tz" in clean:
            return TIMEZONE_ALIASES[alias]
    # 2. Standalone word / boundary matching
    for alias in sorted_aliases:
        if re.search(r"(?:^|[\s_,\(])" + re.escape(alias) + r"(?:$|[\s_,\)])", clean):
            return TIMEZONE_ALIASES[alias]
    return None


def resolve_user_timezone(tz_hint: str = "", user_lang: str = "fa") -> Tuple[datetime.tzinfo, str]:
    """Resolves timezone name to datetime tzinfo object and canonical IANA name."""
    target_name = ""
    if tz_hint:
        clean_hint = tz_hint.strip().lower()
        target_name = TIMEZONE_ALIASES.get(clean_hint, tz_hint.strip())

    if not target_name:
        lang_map = {
            "fa": "Asia/Tehran",
            "ar": "Asia/Dubai",
            "tr": "Europe/Istanbul",
            "de": "Europe/Berlin",
            "fr": "Europe/Paris",
            "es": "Europe/Madrid",
            "it": "Europe/Rome",
            "ru": "Europe/Moscow",
            "zh": "Asia/Shanghai",
            "ja": "Asia/Tokyo",
            "ko": "Asia/Seoul",
            "hi": "Asia/Kolkata",
        }
        target_name = lang_map.get((user_lang or "").lower().strip()[:2], "UTC")

    if pytz:
        try:
            return pytz.timezone(target_name), target_name
        except Exception:
            pass

    # Standard library fallback offsets
    offsets = {
        "Asia/Tehran": datetime.timedelta(hours=3, minutes=30),
        "Asia/Dubai": datetime.timedelta(hours=4),
        "Asia/Riyadh": datetime.timedelta(hours=3),
        "Asia/Qatar": datetime.timedelta(hours=3),
        "Europe/London": datetime.timedelta(0),
        "UTC": datetime.timedelta(0),
        "Europe/Paris": datetime.timedelta(hours=1),
        "Europe/Berlin": datetime.timedelta(hours=1),
        "Europe/Rome": datetime.timedelta(hours=1),
        "Europe/Madrid": datetime.timedelta(hours=1),
        "Europe/Amsterdam": datetime.timedelta(hours=1),
        "Europe/Istanbul": datetime.timedelta(hours=3),
        "Europe/Moscow": datetime.timedelta(hours=3),
        "America/New_York": datetime.timedelta(hours=-5),
        "America/Chicago": datetime.timedelta(hours=-6),
        "America/Denver": datetime.timedelta(hours=-7),
        "America/Los_Angeles": datetime.timedelta(hours=-8),
        "America/Toronto": datetime.timedelta(hours=-5),
        "Asia/Tokyo": datetime.timedelta(hours=9),
        "Asia/Seoul": datetime.timedelta(hours=9),
        "Asia/Shanghai": datetime.timedelta(hours=8),
        "Asia/Singapore": datetime.timedelta(hours=8),
        "Asia/Kolkata": datetime.timedelta(hours=5, minutes=30),
        "Australia/Sydney": datetime.timedelta(hours=10),
        "Pacific/Auckland": datetime.timedelta(hours=12),
    }
    offset = offsets.get(target_name, datetime.timedelta(0))
    return datetime.timezone(offset), target_name


def get_tehran_now() -> datetime.datetime:
    return datetime.datetime.now(TEHRAN_TZ)


# ==========================================
# 1. Zero-Dependency Cron & Natural Time Parser
# ==========================================

def _cron_match_field(val: int, expr: str, min_v: int, max_v: int) -> bool:
    if expr == "*":
        return True
    if "/" in expr:
        parts = expr.split("/")
        step = int(parts[1])
        start = min_v if parts[0] == "*" else int(parts[0])
        return (val >= start) and ((val - start) % step == 0)
    if "," in expr:
        return any(_cron_match_field(val, sub, min_v, max_v) for sub in expr.split(","))
    if "-" in expr:
        start, end = map(int, expr.split("-"))
        return start <= val <= end
    try:
        return int(expr) == val
    except ValueError:
        return False


def get_next_cron_run(cron_expr: str, from_dt: Optional[datetime.datetime] = None) -> datetime.datetime:
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError("Cron expression must have exactly 5 parts: minute hour day month weekday")
    m_exp, h_exp, dom_exp, mon_exp, dow_exp = parts

    base_dt = from_dt or get_tehran_now()
    cur = base_dt.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)

    for _ in range(10_000):
        if not _cron_match_field(cur.month, mon_exp, 1, 12):
            cur = (cur.replace(day=1, hour=0, minute=0) + datetime.timedelta(days=32)).replace(day=1)
            continue
        if not _cron_match_field(cur.day, dom_exp, 1, 31):
            cur = (cur + datetime.timedelta(days=1)).replace(hour=0, minute=0)
            continue
        cron_dow = (cur.weekday() + 1) % 7
        if not _cron_match_field(cron_dow, dow_exp, 0, 6):
            cur = (cur + datetime.timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if not _cron_match_field(cur.hour, h_exp, 0, 23):
            cur = (cur + datetime.timedelta(hours=1)).replace(minute=0)
            continue
        if not _cron_match_field(cur.minute, m_exp, 0, 59):
            cur += datetime.timedelta(minutes=1)
            continue
        return cur
    raise ValueError("No matching cron run found within 1 year")


def parse_schedule_expression(
    expr: str,
    base_now: Optional[datetime.datetime] = None,
    user_timezone: str = "",
    user_lang: str = "fa"
) -> ScheduleResult:
    """
    Parses natural language (Persian / English), relative intervals, fixed clock times,
    or standard cron syntax into execution parameters across international timezones.

    Returns:
        ScheduleResult: (next_run_ts, is_recurring, cron_expr, interval_seconds, human_desc)
        with .timezone property.
    """
    s = (expr or "").strip().lower()

    # Convert Persian digits
    fa_nums = "۰۱۲۳۴۵۶۷۸۹"
    for i, f in enumerate(fa_nums):
        s = s.replace(f, str(i))

    # Timezone Detection & Resolution
    detected_tz = detect_timezone_in_text(s)
    if detected_tz:
        chosen_tz = detected_tz
        # Strip timezone keywords from s to prevent interfering with clock numbers
        for alias in sorted(TIMEZONE_ALIASES.keys(), key=len, reverse=True):
            if TIMEZONE_ALIASES[alias] == detected_tz:
                s = re.sub(rf"به\s*(?:وقت|افق)\s+{re.escape(alias)}", "", s)
                s = re.sub(rf"{re.escape(alias)}\s*(?:time|tz)", "", s)
                s = re.sub(rf"(?:^|[\s_,\(]){re.escape(alias)}(?:$|[\s_,\)])", " ", s)
        s = s.strip()
    elif user_timezone:
        chosen_tz = user_timezone
    else:
        chosen_tz = "Asia/Tehran" if (user_lang or "").startswith("fa") else "UTC"

    tz_obj, canonical_tz = resolve_user_timezone(chosen_tz, user_lang)
    now = base_now or datetime.datetime.now(tz_obj)

    # A. 5-Part Cron Syntax
    cron_parts = s.split()
    if len(cron_parts) == 5 and all(re.match(r"^[\d\*\/\,\-]+$", p) for p in cron_parts):
        try:
            next_dt = get_next_cron_run(s, now)
            tz_tag = f" ({canonical_tz})" if canonical_tz != "Asia/Tehran" else ""
            return ScheduleResult(
                next_dt.timestamp(), True, s, 0,
                f"الگوی کرون `{s}` (اجرای بعدی: {next_dt.strftime('%H:%M %Y/%m/%d')}{tz_tag})",
                timezone=canonical_tz
            )
        except Exception:
            pass

    # B. Specific clock time (with optional daily recurrence): "ساعت 14:00", "18:30", "هر روز ساعت ۱۲:۰۰", "ساعت ۵ عصر"
    has_clock_signal = (
        bool(re.search(r"\b\d{1,2}:\d{2}\b", s))
        or bool(re.search(r"ساعت\s*\d{1,2}", s))
        or bool(re.search(r"\b\d{1,2}\s*(صبح|عصر|شب|ظهر|am|pm)\b", s))
    )
    if has_clock_signal:
        is_recurring_daily = any(kw in s for kw in ["هر روز", "روزانه", "daily", "every day", "هرروز"])
        m_clock = re.search(r"(?:ساعت\s*)?(\d{1,2})(?::(\d{2}))?\s*(صبح|عصر|شب|ظهر|am|pm)?", s)
        if m_clock:
            hour = int(m_clock.group(1))
            minute = int(m_clock.group(2) or 0)
            period = m_clock.group(3) or ""

            if period in ("عصر", "شب", "pm") and hour < 12:
                hour += 12
            elif period in ("صبح", "am") and hour == 12:
                hour = 0

            target_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if "فردا" in s or "tomorrow" in s:
                target = target_today + datetime.timedelta(days=1)
            elif "پس فردا" in s:
                target = target_today + datetime.timedelta(days=2)
            else:
                if target_today <= now:
                    target = target_today + datetime.timedelta(days=1)
                else:
                    target = target_today

            cron_equiv = f"{minute} {hour} * * *" if is_recurring_daily else ""
            if canonical_tz == "Asia/Tehran":
                desc = f"{'هر روز ' if is_recurring_daily else ''}ساعت {hour:02d}:{minute:02d}"
            else:
                desc = f"{'Daily ' if is_recurring_daily else ''}at {hour:02d}:{minute:02d} ({canonical_tz})"
            return ScheduleResult(
                target.timestamp(), is_recurring_daily, cron_equiv,
                (86400 if is_recurring_daily else 0), desc,
                timezone=canonical_tz
            )

    # C. Recurring intervals: "هر ۳۰ دقیقه", "هر ۲ ساعت", "every 2 hours", "every 30m"
    m_every_fa = re.search(r"هر\s*(\d+)?\s*(دقیقه|ساعت|روز)", s)
    if m_every_fa:
        val = int(m_every_fa.group(1) or 1)
        unit = m_every_fa.group(2)
        sec = (val * 60 if unit == "دقیقه" else (val * 3600 if unit == "ساعت" else val * 86400))
        target = now + datetime.timedelta(seconds=sec)
        return ScheduleResult(target.timestamp(), True, "", sec, f"تکرارشونده هر {val} {unit}", timezone=canonical_tz)

    m_every_en = re.search(r"every\s*(\d+)?\s*(m|min|minute|minutes|h|hr|hour|hours|d|day|days)", s)
    if m_every_en:
        val = int(m_every_en.group(1) or 1)
        unit = m_every_en.group(2)
        sec = val * 60 if unit.startswith("m") else (val * 3600 if unit.startswith("h") else val * 86400)
        target = now + datetime.timedelta(seconds=sec)
        return ScheduleResult(target.timestamp(), True, "", sec, f"recurring every {val} {unit}", timezone=canonical_tz)

    # D. Relative delay: "10m", "2h", "1d", "30s", "10 دقیقه", "۲ ساعت بعد"
    m_rel_en = re.match(r"^(\d+)\s*(s|sec|m|min|minute|minutes|h|hr|hour|hours|d|day|days)$", s)
    if m_rel_en:
        val = int(m_rel_en.group(1))
        unit = m_rel_en.group(2)
        sec = val if unit.startswith("s") else (val * 60 if unit.startswith("m") else (val * 3600 if unit.startswith("h") else val * 86400))
        target = now + datetime.timedelta(seconds=sec)
        return ScheduleResult(target.timestamp(), False, "", sec, f"{val} {unit} بعد", timezone=canonical_tz)

    m_rel_fa = re.search(r"(\d+)\s*(ثانیه|دقیقه|ساعت|روز)\s*(دیگه|بعد)?", s)
    if m_rel_fa:
        val = int(m_rel_fa.group(1))
        unit = m_rel_fa.group(2)
        sec = val if unit == "ثانیه" else (val * 60 if unit == "دقیقه" else (val * 3600 if unit == "ساعت" else val * 86400))
        target = now + datetime.timedelta(seconds=sec)
        return ScheduleResult(target.timestamp(), False, "", sec, f"{val} {unit} بعد", timezone=canonical_tz)

    # Fallback: 1 hour default
    target = now + datetime.timedelta(hours=1)
    return ScheduleResult(target.timestamp(), False, "", 3600, "۱ ساعت بعد (پیش‌فرض)", timezone=canonical_tz)


# ==========================================
# 2. Database Persistence & Management
# ==========================================

async def create_scheduled_job_async(
    chat_id: int,
    user_id: int,
    title: str,
    time_expression: str,
    action_type: str = "reminder",
    payload: str = "",
    user_name: str = "",
    username: str = "",
    user_timezone: str = "",
    user_lang: str = "fa",
) -> Dict[str, Any]:
    """
    Creates and schedules a job with strict D1 persistence, international timezone awareness,
    and sub-second activation.
    """
    clean_uid = int(user_id)
    is_admin = (clean_uid == ADMIN_ID)

    # Quota check: max 5 active jobs per non-admin
    if not is_admin:
        active_count_res = await database.execute_d1_query(
            "SELECT COUNT(*) as cnt FROM scheduled_jobs WHERE user_id = ? AND status = 'active'",
            [clean_uid]
        )
        if active_count_res.get("success") and active_count_res.get("results"):
            cnt = active_count_res["results"][0].get("cnt", 0)
            if cnt >= 5:
                return {
                    "success": False,
                    "error": "⚠️ سقف تسک‌های زمان‌بندی‌شده فعال شما (۵ تسک) تکمیل است. ابتدا تسک‌های قبلی را با /cancel_schedule لغو کنید."
                }

    if not user_timezone:
        user_timezone = await database.get_user_timezone_async(clean_uid, fallback_lang=user_lang)

    sched_res = parse_schedule_expression(
        time_expression,
        user_timezone=user_timezone,
        user_lang=user_lang
    )
    next_ts, is_recurring, cron_exp, interval_sec, human_desc = sched_res
    canonical_tz = getattr(sched_res, "timezone", user_timezone) or "UTC"

    sql = """
    INSERT INTO scheduled_jobs (
        chat_id, user_id, user_name, username, title,
        action_type, payload, schedule_type, interval_seconds,
        cron_expr, next_run_ts, is_recurring, status, timezone
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
    """
    sched_type = "cron" if cron_exp else ("interval" if interval_sec > 0 and is_recurring else "once")
    res = await database.execute_d1_query(
        sql,
        [
            int(chat_id), clean_uid, user_name, username, title.strip(),
            action_type, payload or title, sched_type, interval_sec,
            cron_exp, next_ts, int(is_recurring), canonical_tz
        ]
    )

    if not res.get("success"):
        return {"success": False, "error": "خطا در ثبت تسک در پایگاه داده D1."}

    # Fetch inserted row ID
    job_id = 0
    id_res = await database.execute_d1_query("SELECT last_insert_rowid() as id")
    if id_res.get("success") and id_res.get("results"):
        job_id = id_res["results"][0].get("id", 0)

    # Format human dates in target timezone
    tz_obj, _ = resolve_user_timezone(canonical_tz, user_lang)
    dt_obj = datetime.datetime.fromtimestamp(next_ts, tz=tz_obj)
    if canonical_tz == "Asia/Tehran" and jdatetime:
        try:
            j_dt = jdatetime.datetime.fromgregorian(datetime=dt_obj)
            formatted_date_str = j_dt.strftime("%Y/%m/%d ساعت %H:%M")
        except Exception:
            formatted_date_str = dt_obj.strftime("%Y-%m-%d %H:%M")
    else:
        formatted_date_str = f"{dt_obj.strftime('%Y-%m-%d %H:%M')} ({canonical_tz})"

    tip = ""
    if canonical_tz == "UTC" and not user_lang.startswith("fa"):
        tip = "💡 Tip: Scheduled in UTC. To use your local time, specify your city (e.g. 'at 14:00 London') or set with /timezone <City>."

    notify_scheduler_new_job()
    return {
        "success": True,
        "job_id": job_id,
        "title": title,
        "human_desc": human_desc,
        "next_run_formatted": formatted_date_str,
        "is_recurring": is_recurring,
        "action_type": action_type,
        "timezone": canonical_tz,
        "tip": tip,
    }


async def list_scheduled_jobs_async(
    chat_id: int = 0,
    user_id: int = 0,
    is_admin: bool = False
) -> List[Dict[str, Any]]:
    """Lists active scheduled jobs for the chat/user with localized timezone formatting."""
    if is_admin and chat_id == 0:
        sql = "SELECT * FROM scheduled_jobs WHERE status = 'active' ORDER BY next_run_ts ASC LIMIT 30"
        params = []
    elif is_admin:
        sql = "SELECT * FROM scheduled_jobs WHERE chat_id = ? AND status = 'active' ORDER BY next_run_ts ASC LIMIT 30"
        params = [int(chat_id)]
    else:
        sql = "SELECT * FROM scheduled_jobs WHERE user_id = ? AND status = 'active' ORDER BY next_run_ts ASC LIMIT 15"
        params = [int(user_id)]

    res = await database.execute_d1_query(sql, params)
    if res.get("success") and res.get("results"):
        records = res["results"]
        for r in records:
            ts = r.get("next_run_ts", 0)
            job_tz = r.get("timezone") or "Asia/Tehran"
            tz_obj, canon_tz = resolve_user_timezone(job_tz)
            if ts:
                dt_obj = datetime.datetime.fromtimestamp(ts, tz=tz_obj)
                if canon_tz == "Asia/Tehran" and jdatetime:
                    try:
                        j_dt = jdatetime.datetime.fromgregorian(datetime=dt_obj)
                        r["next_run_formatted"] = j_dt.strftime("%Y/%m/%d %H:%M")
                    except Exception:
                        r["next_run_formatted"] = dt_obj.strftime("%Y-%m-%d %H:%M")
                else:
                    r["next_run_formatted"] = f"{dt_obj.strftime('%Y-%m-%d %H:%M')} ({canon_tz})"
                r["next_run_jalali"] = r["next_run_formatted"]
        return records
    return []


async def cancel_scheduled_job_async(job_id: int, caller_id: int) -> Tuple[bool, str]:
    """Cancels a scheduled job if caller is the owner or Master Admin."""
    clean_jid = int(job_id)
    clean_cid = int(caller_id)
    is_admin = (clean_cid == ADMIN_ID)

    probe = await database.execute_d1_query(
        "SELECT id, user_id, title FROM scheduled_jobs WHERE id = ?",
        [clean_jid]
    )
    if not probe.get("success") or not probe.get("results"):
        return False, "تسک با این شناسه یافت نشد."

    job = probe["results"][0]
    if not is_admin and int(job.get("user_id", 0)) != clean_cid:
        return False, "شما مجاز به لغو این تسک نیستید."

    res = await database.execute_d1_query(
        "UPDATE scheduled_jobs SET status = 'cancelled' WHERE id = ?",
        [clean_jid]
    )
    if res.get("success"):
        notify_scheduler_new_job()
        return True, f"تسک «{job.get('title')}» با شناسه #{clean_jid} با موفقیت لغو شد."
    return False, "خطا در لغو تسک در دیتابیس."


_SCHEDULER_WAKEUP_EVENT: Optional[asyncio.Event] = None

def notify_scheduler_new_job():
    """Wakes up the scheduler worker immediately when a new task is created or modified."""
    global _SCHEDULER_WAKEUP_EVENT
    if _SCHEDULER_WAKEUP_EVENT is not None:
        try:
            _SCHEDULER_WAKEUP_EVENT.set()
        except Exception:
            pass

# ==========================================
# 3. Autonomous Background Dispatcher Loop
# ==========================================

async def _scheduler_worker_loop(bot):
    """
    Continuous Background Scheduler Loop.
    Executes due tasks at their exact scheduled second, supports market reports,
    custom reminders, and recurring cron patterns with localized timezone support.
    Adaptive event-driven sleep eliminates 95% of background D1 polling.
    """
    global _SCHEDULER_WAKEUP_EVENT
    _SCHEDULER_WAKEUP_EVENT = asyncio.Event()
    logger.info("Prometheus Cron & Task Scheduler Engine started successfully.")
    while True:
        try:
            now_ts = time.time()
            # Query active jobs ordered by next_run_ts
            due_res = await database.execute_d1_query(
                "SELECT * FROM scheduled_jobs WHERE status = 'active' ORDER BY next_run_ts ASC LIMIT 10"
            )
            all_active = due_res.get("results", []) if due_res.get("success") else []
            due_jobs = [j for j in all_active if (j.get("next_run_ts") or 0) <= now_ts]
            future_jobs = [j for j in all_active if (j.get("next_run_ts") or 0) > now_ts]

            for job in due_jobs:
                jid = job.get("id")
                chat_id = job.get("chat_id")
                user_id = job.get("user_id")
                user_name = job.get("user_name") or ""
                username = job.get("username") or ""
                action_type = job.get("action_type") or "reminder"
                payload = job.get("payload") or job.get("title") or ""
                is_recurring = bool(job.get("is_recurring", 0))
                cron_expr = job.get("cron_expr") or ""
                interval_sec = job.get("interval_seconds") or 0
                job_tz = job.get("timezone") or "Asia/Tehran"

                # Execute Action
                try:
                    await _execute_scheduled_action(bot, chat_id, user_id, user_name, username, action_type, payload)
                except Exception as ex:
                    logger.error(f"Error executing scheduled job #{jid}: {ex}")

                # Update state: recurring vs once
                if is_recurring:
                    tz_obj, _ = resolve_user_timezone(job_tz)
                    now_dt = datetime.datetime.fromtimestamp(now_ts, tz=tz_obj)
                    if cron_expr:
                        try:
                            next_dt = get_next_cron_run(cron_expr, now_dt)
                            next_ts = next_dt.timestamp()
                        except Exception:
                            next_ts = now_ts + (interval_sec or 86400)
                    elif interval_sec > 0:
                        next_ts = now_ts + interval_sec
                    else:
                        next_ts = now_ts + 86400

                    await database.execute_d1_query(
                        "UPDATE scheduled_jobs SET next_run_ts = ?, last_run_at = CURRENT_TIMESTAMP WHERE id = ?",
                        [next_ts, jid]
                    )
                else:
                    await database.execute_d1_query(
                        "UPDATE scheduled_jobs SET status = 'completed', last_run_at = CURRENT_TIMESTAMP WHERE id = ?",
                        [jid]
                    )

            # Adaptive sleep: sleep until next job is due, or up to 60s, or wake up instantly on new job
            earliest_next = future_jobs[0].get("next_run_ts", now_ts + 60.0) if future_jobs else (now_ts + 60.0)
            sleep_duration = max(1.0, min(60.0, earliest_next - time.time()))

            try:
                await asyncio.wait_for(_SCHEDULER_WAKEUP_EVENT.wait(), timeout=sleep_duration)
                _SCHEDULER_WAKEUP_EVENT.clear()
            except asyncio.TimeoutError:
                pass

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Scheduler worker tick exception: {e}")
            await asyncio.sleep(15.0)


async def _execute_scheduled_action(
    bot,
    chat_id: int,
    user_id: int,
    user_name: str,
    username: str,
    action_type: str,
    payload: str
):
    """Executes a single scheduled task and safely delivers message to chat."""
    mention = f"@{username}" if username else (f"[{user_name}](tg://user?id={user_id})" if user_name else "")

    if action_type in ("market_report", "price_report"):
        from src.tools import financial
        board = await financial.get_fiat_overview()
        text = f"📊 *گزارش خودکار بازارهای مالی پرومته*:\n\n{board}"

    elif action_type == "tool_exec":
        from src.tools.registry import execute_registered_tool
        tool_name = payload.strip()
        tool_out = await execute_registered_tool(tool_name, {}, caller_id=user_id)
        text = f"⚙️ *نتیجه اجرای زمان‌بندی‌شده ابزار `{tool_name}`*:\n\n{tool_out}"

    else:
        # Default reminder
        prefix = f"⏰ {mention}\n\n" if mention else "⏰ *یادآوری زمان‌بندی‌شده*:\n\n"
        text = f"{prefix}📌 {payload}"

    clean_text = sanitize_output(text)
    html_text = telegram_formatter.markdown_to_telegram_html(clean_text)

    try:
        from telegram.constants import ParseMode
        await bot.send_message(chat_id=chat_id, text=html_text, parse_mode=ParseMode.HTML)
    except Exception:
        # Fallback to plain text
        await bot.send_message(chat_id=chat_id, text=clean_text)


def start_scheduler(bot):
    """Launches the background scheduler task."""
    global _SCHEDULER_TASK
    if _SCHEDULER_TASK is None or _SCHEDULER_TASK.done():
        try:
            loop = asyncio.get_running_loop()
            _SCHEDULER_TASK = loop.create_task(_scheduler_worker_loop(bot))
        except RuntimeError:
            pass
