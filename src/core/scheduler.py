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

    for _ in range(60 * 24 * 366):
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
    base_now: Optional[datetime.datetime] = None
) -> Tuple[float, bool, str, int, str]:
    """
    Parses natural language (Persian / English), relative intervals, fixed times,
    or standard cron syntax into execution parameters.

    Returns:
        (next_run_ts, is_recurring, cron_expr, interval_seconds, human_desc)
    """
    now = base_now or get_tehran_now()
    s = (expr or "").strip().lower()

    # Convert Persian digits
    fa_nums = "۰۱۲۳۴۵۶۷۸۹"
    for i, f in enumerate(fa_nums):
        s = s.replace(f, str(i))

    # A. 5-Part Cron Syntax
    cron_parts = s.split()
    if len(cron_parts) == 5 and all(re.match(r"^[\d\*\/\,\-]+$", p) for p in cron_parts):
        try:
            next_dt = get_next_cron_run(s, now)
            return next_dt.timestamp(), True, s, 0, f"الگوی کرون `{s}` (اجرای بعدی: {next_dt.strftime('%H:%M %Y/%m/%d')})"
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
            desc = f"{'هر روز ' if is_recurring_daily else ''}ساعت {hour:02d}:{minute:02d}"
            return target.timestamp(), is_recurring_daily, cron_equiv, (86400 if is_recurring_daily else 0), desc

    # C. Recurring intervals: "هر ۳۰ دقیقه", "هر ۲ ساعت", "every 2 hours", "every 30m"
    m_every_fa = re.search(r"هر\s*(\d+)?\s*(دقیقه|ساعت|روز)", s)
    if m_every_fa:
        val = int(m_every_fa.group(1) or 1)
        unit = m_every_fa.group(2)
        sec = (val * 60 if unit == "دقیقه" else (val * 3600 if unit == "ساعت" else val * 86400))
        target = now + datetime.timedelta(seconds=sec)
        return target.timestamp(), True, "", sec, f"تکرارشونده هر {val} {unit}"

    m_every_en = re.search(r"every\s*(\d+)?\s*(m|min|minute|minutes|h|hr|hour|hours|d|day|days)", s)
    if m_every_en:
        val = int(m_every_en.group(1) or 1)
        unit = m_every_en.group(2)
        sec = val * 60 if unit.startswith("m") else (val * 3600 if unit.startswith("h") else val * 86400)
        target = now + datetime.timedelta(seconds=sec)
        return target.timestamp(), True, "", sec, f"recurring every {val} {unit}"

    # D. Relative delay: "10m", "2h", "1d", "30s", "10 دقیقه", "۲ ساعت بعد"
    # Special Persian phrases
    if "نیم ساعت" in s:
        target = now + datetime.timedelta(minutes=30)
        return target.timestamp(), False, "", 1800, "۳۰ دقیقه بعد"
    if "یک ربع" in s or "۱ ربع" in s:
        target = now + datetime.timedelta(minutes=15)
        return target.timestamp(), False, "", 900, "۱۵ دقیقه بعد"

    m_rel_en = re.match(r"^(\d+)\s*(s|sec|m|min|minute|minutes|h|hr|hour|hours|d|day|days)$", s)
    if m_rel_en:
        val = int(m_rel_en.group(1))
        unit = m_rel_en.group(2)
        sec = val if unit.startswith("s") else (val * 60 if unit.startswith("m") else (val * 3600 if unit.startswith("h") else val * 86400))
        target = now + datetime.timedelta(seconds=sec)
        return target.timestamp(), False, "", sec, f"{val} {unit} بعد"

    m_rel_fa = re.search(r"(\d+)\s*(دقیقه|ساعت|ثانیه|روز)", s)
    if m_rel_fa and ("دیگه" in s or "بعد" in s or "آینده" in s or not ("ساعت" in s and ":" in s)):
        val = int(m_rel_fa.group(1))
        unit = m_rel_fa.group(2)
        sec = val if unit == "ثانیه" else (val * 60 if unit == "دقیقه" else (val * 3600 if unit == "ساعت" else val * 86400))
        target = now + datetime.timedelta(seconds=sec)
        return target.timestamp(), False, "", sec, f"{val} {unit} بعد"

    # D. Daily clock time: "ساعت 14:00", "18:30", "هر روز ساعت ۱۲:۰۰", "ساعت ۵ عصر"
    is_recurring_daily = any(kw in s for kw in ["هر روز", "روزانه", "daily", "every day"])
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
        desc = f"{'هر روز ' if is_recurring_daily else ''}ساعت {hour:02d}:{minute:02d}"
        return target.timestamp(), is_recurring_daily, cron_equiv, (86400 if is_recurring_daily else 0), desc

    # Fallback: 1 hour default
    target = now + datetime.timedelta(hours=1)
    return target.timestamp(), False, "", 3600, "۱ ساعت بعد (پیش‌فرض)"


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
) -> Dict[str, Any]:
    """
    Creates and schedules a job with strict D1 persistence and sub-second activation.
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

    next_ts, is_recurring, cron_exp, interval_sec, human_desc = parse_schedule_expression(time_expression)

    sql = """
    INSERT INTO scheduled_jobs (
        chat_id, user_id, user_name, username, title,
        action_type, payload, schedule_type, interval_seconds,
        cron_expr, next_run_ts, is_recurring, status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
    """
    sched_type = "cron" if cron_exp else ("interval" if interval_sec > 0 and is_recurring else "once")
    res = await database.execute_d1_query(
        sql,
        [
            int(chat_id), clean_uid, user_name, username, title.strip(),
            action_type, payload or title, sched_type, interval_sec,
            cron_exp, next_ts, int(is_recurring)
        ]
    )

    if not res.get("success"):
        return {"success": False, "error": "خطا در ثبت تسک در پایگاه داده D1."}

    # Fetch inserted row ID
    job_id = 0
    id_res = await database.execute_d1_query("SELECT last_insert_rowid() as id")
    if id_res.get("success") and id_res.get("results"):
        job_id = id_res["results"][0].get("id", 0)

    # Format human dates
    dt_obj = datetime.datetime.fromtimestamp(next_ts, tz=TEHRAN_TZ)
    if jdatetime:
        try:
            j_dt = jdatetime.datetime.fromgregorian(datetime=dt_obj)
            j_date_str = j_dt.strftime("%Y/%m/%d ساعت %H:%M")
        except Exception:
            j_date_str = dt_obj.strftime("%Y-%m-%d %H:%M")
    else:
        j_date_str = dt_obj.strftime("%Y-%m-%d %H:%M")

    return {
        "success": True,
        "job_id": job_id,
        "title": title,
        "human_desc": human_desc,
        "next_run_formatted": j_date_str,
        "is_recurring": is_recurring,
        "action_type": action_type,
    }


async def list_scheduled_jobs_async(
    chat_id: int = 0,
    user_id: int = 0,
    is_admin: bool = False
) -> List[Dict[str, Any]]:
    """Lists active scheduled jobs for the chat/user."""
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
            if ts:
                dt_obj = datetime.datetime.fromtimestamp(ts, tz=TEHRAN_TZ)
                if jdatetime:
                    try:
                        j_dt = jdatetime.datetime.fromgregorian(datetime=dt_obj)
                        r["next_run_jalali"] = j_dt.strftime("%Y/%m/%d %H:%M")
                    except Exception:
                        r["next_run_jalali"] = dt_obj.strftime("%Y-%m-%d %H:%M")
                else:
                    r["next_run_jalali"] = dt_obj.strftime("%Y-%m-%d %H:%M")
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
        return True, f"تسک «{job.get('title')}» با شناسه #{clean_jid} با موفقیت لغو شد."
    return False, "خطا در لغو تسک در دیتابیس."


# ==========================================
# 3. Autonomous Background Dispatcher Loop
# ==========================================

async def _scheduler_worker_loop(bot):
    """
    Continuous Background Scheduler Loop.
    Executes due tasks at their exact scheduled second, supports market reports,
    custom reminders, and recurring cron patterns with zero CPU starvation.
    """
    logger.info("Prometheus Cron & Task Scheduler Engine started successfully.")
    while True:
        try:
            now_ts = time.time()
            # Query due active jobs
            due_res = await database.execute_d1_query(
                "SELECT * FROM scheduled_jobs WHERE status = 'active' AND next_run_ts <= ? ORDER BY next_run_ts ASC LIMIT 10",
                [now_ts]
            )
            due_jobs = due_res.get("results", []) if due_res.get("success") else []

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

                # Execute Action
                try:
                    await _execute_scheduled_action(bot, chat_id, user_id, user_name, username, action_type, payload)
                except Exception as ex:
                    logger.error(f"Error executing scheduled job #{jid}: {ex}")

                # Update state: recurring vs once
                now_dt = get_tehran_now()
                if is_recurring:
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

            await asyncio.sleep(5.0)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Scheduler worker tick exception: {e}")
            await asyncio.sleep(5.0)


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
