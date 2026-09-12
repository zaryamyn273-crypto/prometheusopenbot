import os
import re
import ast
import platform
import psutil
import logging
from typing import Optional

from src.tools.registry import register_tool
from src.core import database
from src.core.config import ADMIN_ID
from src.core.security import validate_python_code

# E2B cloud sandbox tools (e2b_run_code / e2b_run_command / e2b_status).
# Imported for side-effect registration only; module itself is fully lazy
# (no E2B import at startup, safe on Railway without the key/package).
try:
    from src.tools.system import e2b_sandbox as _e2b_mod  # noqa: F401
except Exception:
    _e2b_mod = None  # type: ignore

# Commands matching any of these patterns are destructive/sensitive shell and
# are NEVER executed — even for the Master Admin. Everything else stays open.
DESTRUCTIVE_SHELL_PATTERNS = [
    r"rm\s+.*-[a-z]*r[a-z]*f", r"rm\s+-rf\s+/(\s|$)", r"rm\s+--no-preserve-root",
    r"\bmkfs(\.|\s)", r"\bdd\s+.*of=\s*/dev/", r":\(\)\s*\{\s*:\|:\s*&\s*\};:",
    r"\bshutdown\b", r"\breboot\b", r"\bhalt\b", r"\bpoweroff\b",
    r"\bfdisk\b", r"\bparted\b", r"\bgdisk\b", r"wipefs", r"\bshred\b.*\/dev\/",
    r">\s*/dev/sd[a-z]", r">\s*/dev/nvme", r"chmod\s+-R\s+777\s+/",
    r"chown\s+-R\s+\S+\s+/\s",
    # exfil / reverse-shell / env-dump: blocked even for the admin
    r"\bcurl\b.*\b(bash|sh)\b", r"\bwget\b.*\b(bash|sh)\b",
    r"\bnc\s+-[a-z]*e\b", r"\bncat\s+.*--exec\b", r"\bsocat\b",
    r"/dev/tcp/", r"/dev/udp/",
    r"\benv\b", r"\bprintenv\b", r"\bset\b\s*$",
    r"\bcat\b\s+.*\.env\b", r"\bcat\b\s+/proc/self/environ",
]


def is_destructive_shell_command(cmd: str) -> bool:
    try:
        _c = (cmd or "").lower()
        return any(re.search(_p, _c) for _p in DESTRUCTIVE_SHELL_PATTERNS)
    except Exception:
        return False

logger = logging.getLogger(__name__)

# ==========================================
# 1. AST-Safe Python Sandbox Execution
# ==========================================

FORBIDDEN_CALLS = {
    'open', 'compile', 'eval', 'exec', '__import__',
    'os', 'sys', 'subprocess', 'shutil', 'socket', 'urllib',
    'requests', 'httpx', 'builtins', 'ctypes', 'getattr', 'setattr',
    'delattr', 'globals', 'locals', 'vars', 'dir', 'memoryview',
}

FORBIDDEN_ATTRS = {
    '__class__', '__bases__', '__subclasses__', '__globals__', '__code__',
    '__closure__', '__builtins__', '__import__', '__dict__', '__module__',
    '__qualname__', '__mro__', '__subclasshook__', 'f_globals', 'f_locals',
    'gi_frame', 'gi_code', 'cr_frame', 'tb_frame',
}

class SecurityVisitor(ast.NodeVisitor):
    def __init__(self):
        self.errors = []

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name.split('.')[0] in FORBIDDEN_CALLS:
                self.errors.append(f"ماژول مجاز نیست: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module and node.module.split('.')[0] in FORBIDDEN_CALLS:
            self.errors.append(f"ماژول مجاز نیست: {node.module}")
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
            self.errors.append(f"تابع غیرمجاز: {node.func.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if node.attr in FORBIDDEN_ATTRS:
            self.errors.append(f"ویژگی غیرمجاز: {node.attr}")
        self.generic_visit(node)


def mask_sensitive_shell_output(output: str, is_private_chat: bool) -> tuple[str, bool]:
    """
    If executed in a group, masks any secrets (API keys, bot tokens, cloudflare IDs, passwords,
    env variables) with '[SECRET]' and informs the commander to check PV for full uncensored output.
    """
    if is_private_chat:
        return output, False

    masked = output
    redacted = False

    known_secrets = [
        os.getenv("TELEGRAM_BOT_TOKEN", ""),
        os.getenv("ROUTER_API_KEY", ""),
        os.getenv("CLOUDFLARE_D1_ID", ""),
        os.getenv("CLOUDFLARE_KV_ID", ""),
        os.getenv("CLOUDFLARE_ACCOUNT_ID", ""),
        os.getenv("CLOUDFLARE_API_TOKEN", ""),
        os.getenv("ALLRATESTODAY_API_KEY", ""),
        os.getenv("GITHUB_TOKEN", ""),
        os.getenv("TAVILY_API_KEY", ""),
        os.getenv("TAVILY_API_KEYS", ""),
        os.getenv("SPOTIFY_CLIENT_ID", ""),
        os.getenv("SPOTIFY_CLIENT_SECRET", ""),
        os.getenv("E2B_API_KEY", ""),
    ]
    for s in known_secrets:
        if s and len(s) >= 8 and s in masked:
            masked = masked.replace(s, "[SECRET]")
            redacted = True

    patterns = [
        r'(?i)(token|key|secret|password|pwd|auth|credential|apikey)[\s:=]+([^\s,;\n]{6,})',
        r'sk-[a-zA-Z0-9_\-]{10,}',
        r'[0-9]{8,11}:[a-zA-Z0-9_\-]{30,}',
        r'art_live_[a-zA-Z0-9]{12,}',
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        r'ghp_[A-Za-z0-9]{20,}',
        r'gho_[A-Za-z0-9]{20,}',
        r'github_pat_[A-Za-z0-9_]{10,}',
        r'tvly-[A-Za-z0-9_\-]{8,}',
    ]
    for pat in patterns:
        if re.search(pat, masked):
            redacted = True
            masked = re.sub(pat, '[SECRET]', masked)

    if redacted:
        masked += "\n\n🔒 <i>[توجه امنیتی: اطلاعات حساس با عنوان [SECRET] ماسک شدند. برای مشاهده اطلاعات کامل لطفاً به پیوی مراجعه بفرمایید.]</i>"

    return masked, redacted

@register_tool(
    name="execute_python_code",
    description="اجرای کد پایتون فقط در سندباکس ابری E2B (مختص فرمانده ارشد؛ بدون E2B_API_KEY غیرفعال است، هیچ اجرای لوکالی وجود ندارد)",
    category="admin"
)
async def execute_python_code(code: str, caller_id: int = 0, is_private_chat: bool = False) -> str:
    """
    :param code: متن کد پایتون جهت اجرا
    """
    if int(caller_id or 0) != int(ADMIN_ID):
        return "⛔ دسترسی غیرمجاز! اجرای شل و کدهای سیستمی روی سرور ربات منحصراً در انحصار شخص فرمانده ارشد سیستم است."

    clean_code = code.strip()
    if clean_code.startswith("```python"):
        clean_code = clean_code[9:]
    elif clean_code.startswith("```"):
        clean_code = clean_code[3:]
    if clean_code.endswith("```"):
        clean_code = clean_code[:-3]
    clean_code = clean_code.strip()

    if not clean_code:
        return "کدی برای اجرا ارائه نشده است."

    # Red line 3: destructive shell stays blocked even for the Master Admin.
    if is_destructive_shell_command(clean_code):
        return "⛔ این دستور شل مخرب/حساس است و هرگز اجرا نمی‌شود (حتی به دستور ادمین)."

    try:
        validate_python_code(clean_code)
    except ValueError as e:
        return f"❌ خطای نگارشی (SyntaxError) در کد:\n{e}"
    except PermissionError as e:
        return f"⛔ کد به دلایل امنیتی مسدود شد:\n{e}"

    # Secrets never leave the bot.
    _lower_sec = clean_code.lower()
    if any(t in _lower_sec for t in (".env", "telegram_bot_token", "router_api_key", "e2b_api_key", "cloudflare")):
        return "⛔ کد به دلایل امنیتی مسدود شد: دسترسی به سکرت/توکن ممنوع است."

    # E2B-ONLY execution. There is deliberately NO local fallback: a local
    # Python "sandbox" without cgroups/containers is security theater and a
    # straight path to server RCE via indirect prompt injection. Without a
    # configured E2B key the tool is DISABLED (see SECURITY.md).
    try:
        from src.core.config import has_e2b as _has_e2b_cfg
        _e2b_on = bool(_has_e2b_cfg())
    except Exception:
        _e2b_on = False
    if not _e2b_on:
        try:
            from src.core.i18n import t as _t
            return _t("fa", "code_disabled")
        except Exception:
            return "⛔ اجرای کد خاموش است (E2B_API_KEY ست نشده)."
    try:
        from src.tools.system.e2b_sandbox import run_e2b_python as _e2b_run
        _e2b_out = await _e2b_run(clean_code)
        if _e2b_out:
            try:
                masked, _ = mask_sensitive_shell_output(_e2b_out, is_private_chat=is_private_chat)
                return masked
            except Exception:
                return _e2b_out
    except Exception as _e:
        logger.warning(f"E2B cloud run failed: {_e}")
    try:
        from src.core.i18n import t as _t2
        return _t2("fa", "code_disabled")
    except Exception:
        return "⛔ اجرای کد خاموش است (E2B_API_KEY ست نشده)."

# ==========================================
# 2. Server Diagnostics & Telemetry
# ==========================================

@register_tool(
    name="admin_system_diagnostics",
    description="استعلام تله‌متری کامل سرور شامل وضعیت CPU، مصرف RAM، دیسک، سیستم‌عامل و آپ‌تایم",
    category="admin"
)
def admin_system_diagnostics(caller_id: int = 0) -> str:
    if caller_id != ADMIN_ID:
        return "❌ استعلام تله‌متری و مشخصات سرور منحصراً مختص فرمانده ارشد سیستم است."
    try:
        import time as _t
        cpu_usage = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        try:
            load1, load5, load15 = psutil.getloadavg()
            load_txt = f"`{load1:.2f} / {load5:.2f} / {load15:.2f}`"
        except Exception:
            load_txt = "نامشخص"
        try:
            boot_ts = psutil.boot_time()
            up_sec = int(_t.time() - boot_ts)
            up_txt = f"`{up_sec // 3600}h {(up_sec % 3600) // 60}m`"
        except Exception:
            up_txt = "نامشخص"

        mem_used_gb = mem.used / (1024 ** 3)
        mem_total_gb = mem.total / (1024 ** 3)
        disk_free_gb = disk.free / (1024 ** 3)
        disk_total_gb = disk.total / (1024 ** 3)

        return (
            f"🖥 *وضعیت و تله‌متری سرور پرومته*:\n\n"
            f"• *سیستم‌عامل*: `{platform.system()} {platform.release()}`\n"
            f"• *پردازنده (CPU)*: *{cpu_usage}%* (load: {load_txt})\n"
            f"• *حافظه رم (RAM)*: *{mem_used_gb:.2f} GB* از *{mem_total_gb:.2f} GB* ({mem.percent}%)\n"
            f"• *فضای دیسک*: *{disk_free_gb:.2f} GB آزاد* از *{disk_total_gb:.2f} GB*\n"
            f"• *آپ‌تایم سرور*: {up_txt}\n"
            f"• *نسخه پایتون*: `{platform.python_version()}`\n"
            f"• *وضعیت کلی*: 🟢 *عملیاتی و ۱۰۰٪ پایدار*"
        )
    except Exception as e:
        return f"خطا در دریافت اطلاعات تله‌متری سرور: {str(e)}"

# ==========================================
# 3. User Moderation Tools (Robust Multi-Key Lookup)
# ==========================================

@register_tool(
    name="extract_user_id_tool",
    description="فقط برای استعلام آیدی عددی کاربر (Numeric User ID) زمانی که ادمین صراحتاً درخواست استعلام یا آیدی کاربر را کرده باشد. برای دستورات بن از این ابزار استفاده نکنید!",
    category="admin"
)
async def extract_user_id_tool(
    target: Optional[str] = None,
    name: Optional[str] = None,
    username: Optional[str] = None,
    query: Optional[str] = None,
    caller_id: int = 0
) -> str:
    try:
        from src.core.config import ADMIN_ID as _ADMIN
    except Exception:
        _ADMIN = 0
    try:
        if int(caller_id or 0) != int(_ADMIN):
            return "❌ این ابزار منحصراً در اختیار فرمانده ارشد است."
    except Exception:
        return "❌ این ابزار منحصراً در اختیار فرمانده ارشد است."
    raw_query = str(target or name or username or query or "").strip()
    if not raw_query:
        return "❌ لطفاً نام نمایشی، یوزرنیم یا متنی از کاربر مورد نظر را مشخص فرمایید."

    uid, resolved_label = await database.resolve_target_identifier(raw_query)
    if uid:
        details_sql = "SELECT user_name, username, chat_id, chat_title, msg_date, msg_time, created_at FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT 1"
        d_res = await database.execute_d1_query(details_sql, [uid])
        disp_name = resolved_label or "کاربر بدون یوزرنیم"
        uname_str = "ندارد"
        last_chat = "نامشخص"
        last_seen = "نامشخص"
        if d_res.get("success") and d_res.get("results"):
            row = d_res["results"][0]
            disp_name = row.get("user_name") or disp_name
            if row.get("username"):
                uname_str = f"@{row['username'].lstrip('@')}"
            last_chat = f"{row.get('chat_title') or ''} ({row.get('chat_id')})"
            last_seen = f"{row.get('msg_date', '')} {row.get('msg_time', '')}".strip() or row.get("created_at", "")

        is_banned = database.is_user_banned(uid)
        status_badge = "🚫 مسدود (Banned)" if is_banned else "🟢 فعال (Active)"

        lines = [
            "🎯 <b>هویت و شناسه عددی با موفقیت استخراج شد:</b>",
            f"• <b>شناسه عددی (Numeric ID):</b> <code>{uid}</code>",
            f"• <b>نام نمایشی فرد:</b> <b>{disp_name}</b>",
            f"• <b>یوزرنیم تلگرام:</b> <code>{uname_str}</code>",
            f"• <b>آخرین حضور در گروه:</b> {last_chat}",
            f"• <b>زمان آخرین فعالیت:</b> <code>{last_seen}</code>",
            f"• <b>وضعیت دسترسی:</b> {status_badge}",
            "",
            f"<i>💡 برای بن کردن این کاربر:</i> <code>/ban {uid}</code>"
        ]
        return "\n".join(lines)

    return f"❌ متأسفانه هیچ کاربری با مشخصه «{raw_query}» در حافظه و پیام‌های دیتابیس یافت نشد."

@register_tool(
    name="mute_user_tool",
    description="سکوت موقت کاربر: ربات تا پایان مدت به پیام‌های او پاسخی نمی‌دهد (مثل ۳۰ دقیقه). مدت فارسی/انگلیسی: نیم ساعت، ۳۰ دقیقه، 2 ساعت، 1 روز. (مختص ادمین)",
    category="admin"
)
async def mute_user_tool(
    target: Optional[str] = None,
    target_user_id: Optional[str] = None,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    duration: Optional[str] = None,
    duration_sec: int = 0,
    reason: str = "سکوت موقت به دستور فرمانده",
    first_name: str = "",
    source_chat_id: int = 0,
    source_chat_title: str = "",
    caller_id: int = 0,
    chat_id: int = 0
) -> str:
    if caller_id != ADMIN_ID:
        return "❌ فقط ادمین ارشد مجاز به سکوت کردن کاربران است."
    raw_target = target or target_user_id or user_id or username or ""
    clean_t = str(raw_target).strip()
    if not clean_t:
        return "❌ لطفاً شناسه عددی یا نام کاربری فرد را مشخص فرمایید."
    try:
        secs = int(duration_sec or 0)
    except Exception:
        secs = 0
    if not secs:
        secs = database.parse_mute_duration_to_sec(str(duration or ""))
    if not secs:
        secs = 1800
    src_id = int(source_chat_id or chat_id or 0)
    ok, dur, uid, uname = await database.mute_target_async(clean_t, secs, reason, first_name=first_name or "", muted_by=int(caller_id or 0), source_chat_id=src_id, source_chat_title=source_chat_title or "")
    if not ok:
        return "❌ ادمین ارشد مصونیت ابدی دارد و سکوت نمی‌شود."
    who = uid if uid else (uname or clean_t)
    return f"🔇 *سکوت موقت اعمال شد:* کاربر {who} تا *{database.format_mute_remaining(dur)}* پاسخی دریافت نمی‌کند."


@register_tool(
    name="unmute_user_tool",
    description="لغو سکوت موقت کاربر: ربات دوباره به پیام‌های او پاسخ می‌دهد. (مختص ادمین)",
    category="admin"
)
async def unmute_user_tool(
    target: Optional[str] = None,
    target_user_id: Optional[str] = None,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    caller_id: int = 0
) -> str:
    if caller_id != ADMIN_ID:
        return "❌ فقط ادمین ارشد مجاز به لغو سکوت کاربران است."
    raw_target = target or target_user_id or user_id or username or ""
    clean_t = str(raw_target).strip()
    if not clean_t:
        return "❌ لطفاً شناسه عددی یا نام کاربری فرد را مشخص فرمایید."
    await database.unmute_target_async(clean_t)
    return f"🔊 *سکوت کاربر `{clean_t}` لغو شد:* ربات دوباره به پیام‌های او پاسخ می‌دهد."


@register_tool(
    name="get_muted_users_list_tool",
    description="مشاهده لیست کاربران در سکوت موقت همراه با زمان باقی‌مانده (مختص ادمین)",
    category="admin"
)
async def get_muted_users_list_tool(caller_id: int = 0) -> str:
    if caller_id != ADMIN_ID:
        return "❌ فقط ادمین ارشد مجاز به مشاهده لیست سکوت است."
    import time as _t2
    recs = await database.get_muted_users_detailed_async()
    _now = _t2.time()
    _live = []
    for _r in recs:
        try:
            _left = float(_r.get("until_ts") or 0) - _now
        except Exception:
            _left = 0
        if _left > 0:
            _r["_left"] = _left
            _live.append(_r)
    if not _live:
        return "🟢 *هیچ کاربری در سکوت موقت نیست.*"
    lines = [f"🔇 *کاربران در سکوت موقت ({len(_live)} نفر)*:\n"]
    for _r in _live:
        _who = f"`{_r.get('user_id')}`" if _r.get("user_id") else f"`{_r.get('username', '')}`"
        lines.append(f"• {_who} — باقی‌مانده: *{database.format_mute_remaining(_r['_left'])}* (علت: {_r.get('reason', '')})" )
    return "\n".join(lines)


@register_tool(
    name="ban_user_tool",
    description="مسدودسازی دائمی دسترسی یک کاربر در دیتابیس ابری Cloudflare D1 بر اساس شناسه عددی یا نام کاربری (@username) (مختص ادمین)",
    category="admin"
)
async def ban_user_tool(
    target: Optional[str] = None,
    target_user_id: Optional[str] = None,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    reason: str = "تخلف از قوانین",
    first_name: str = "",
    source_chat_id: int = 0,
    source_chat_title: str = "",
    caller_id: int = 0,
    chat_id: int = 0
) -> str:
    """
    :param target: شناسه عددی (مانند 123456789) یا آیدی تلگرام (مانند @username)
    :param target_user_id: شناسه عددی کاربر
    :param user_id: شناسه کاربر
    :param username: نام کاربری تلگرام
    :param reason: علت مسدودسازی
    :param first_name: نام نمایشی فرد (در صورت اطلاع)
    :param source_chat_id: شناسه گروه محل تخلف
    :param source_chat_title: نام گروه محل تخلف
    """
    if caller_id != ADMIN_ID:
        return "❌ فقط ادمین ارشد مجاز به مسدودسازی کاربران است."

    raw_target = target or target_user_id or user_id or username or ""
    clean_t = str(raw_target).strip()
    if not clean_t:
        return "❌ لطفاً شناسه عددی یا نام کاربری فرد مورد نظر را مشخص فرمایید."

    uid, uname = await database.resolve_target_identifier(clean_t)

    if uid == ADMIN_ID:
        return "❌ ادمین ارشد مصونیت ابدی دارد و مسدود نمی‌شود."

    src_id = int(source_chat_id or chat_id or 0)
    await database.ban_target_async(
        clean_t, reason,
        first_name=first_name or "",
        banned_by=int(caller_id or 0),
        source_chat_id=src_id,
        source_chat_title=source_chat_title or ""
    )

    out = ["🚫 *کاربر هدف با موفقیت در دیتابیس ابدی Cloudflare D1 مسدود گردید:*"]
    if uid:
        out.append(f"• *شناسه عددی (User ID):* `{uid}`")
    if uname:
        out.append(f"• *نام کاربری (Username):* `@{uname}`")
    if first_name:
        out.append(f"• *نام:* *{first_name}*")
    out.append(f"• *علت:* {reason}")
    if source_chat_title or src_id:
        out.append(f"• *محل تخلف:* *{source_chat_title or src_id}* (`{src_id}`)")

    return "\n".join(out)

@register_tool(
    name="unban_user_tool",
    description="رفع مسدودیت دائمی کاربر در دیتابیس ابری Cloudflare D1 بر اساس شناسه عددی یا نام کاربری (@username) (مختص ادمین)",
    category="admin"
)
async def unban_user_tool(
    target: Optional[str] = None,
    target_user_id: Optional[str] = None,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    caller_id: int = 0
) -> str:
    """
    :param target: شناسه عددی یا نام کاربری تلگرام برای رفع مسدودیت
    :param target_user_id: شناسه عددی کاربر
    :param user_id: شناسه کاربر
    :param username: نام کاربری تلگرام
    """
    if caller_id != ADMIN_ID:
        return "❌ فقط ادمین ارشد مجاز به رفع مسدودیت کاربران است."

    raw_target = target or target_user_id or user_id or username or ""
    clean_t = str(raw_target).strip()
    if not clean_t:
        return "❌ لطفاً شناسه عددی یا نام کاربری فرد مورد نظر را مشخص فرمایید."

    uid, uname = await database.resolve_target_identifier(clean_t)
    await database.unban_target_async(clean_t)

    out = ["✅ *کاربر هدف با موفقیت در دیتابیس Cloudflare D1 رفع مسدودیت گردید:*"]
    if uid:
        out.append(f"• *شناسه عددی (User ID):* `{uid}`")
    if uname:
        clean_display_uname = uname.lstrip("@")
        out.append(f"• *شناسه / نام کاربری:* `@{clean_display_uname}`")
    if not uid and not uname:
        out.append(f"• *شناسه یا نام هدف:* `{clean_t}`")

    return "\n".join(out)

@register_tool(
    name="get_banned_users_list_tool",
    description="مشاهده لیست کامل، زنده و با جزئیات تمام کاربران مسدودشده (شناسه عددی، یوزرنیم، نام، علت، بن‌کننده، گروه محل تخلف و تاریخ) در دیتابیس Cloudflare D1 (مختص ادمین)",
    category="admin"
)
async def get_banned_users_list_tool(caller_id: int = 0, is_private_chat: bool = False) -> str:
    if caller_id != ADMIN_ID:
        return "❌ فقط ادمین ارشد مجاز به مشاهده لیست مسدودشدگان است."

    records = await database.get_banned_users_detailed_async()
    if not records:
        return "🟢 *هیچ کاربری در لیست سیاه سیستم مسدود نشده است.*"

    lines = [f"🚫 *لیست کاربران مسدودشده در Cloudflare D1 ({len(records)} کاربر)*:\n"]
    for idx, r in enumerate(records):
        uid = r.get("user_id") or "نامشخص"
        uname = f"@{r['username']}" if r.get("username") else "بدون یوزرنیم"
        fname = r.get("first_name") or "—"
        reason = r.get("reason", "نامشخص")
        time_b = r.get("banned_at", "-")
        banner = r.get("banned_by") or "—"
        src_title = r.get("source_chat_title") or ""
        src_id = r.get("source_chat_id") or ""
        src_txt = f"{src_title} (`{src_id}`)" if (src_title or src_id) else "—"
        lines.append(
            f"{idx+1}. شناسه: `{uid}` | یوزرنیم: *{uname}* | نام: *{fname}*\n"
            f"   علت: *{reason}* | بن‌کننده: `{banner}` | محل: *{src_txt}* | تاریخ: `{time_b}`"
        )

    return "\n".join(lines)
