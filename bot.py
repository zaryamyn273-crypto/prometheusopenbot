import io
import json
import time
import logging
import asyncio
import re
from typing import Dict, Any

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    constants
)
from telegram.constants import ParseMode, ChatAction, ChatType
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    TypeHandler,
    ApplicationHandlerStop,
    filters
)

from src.core.config import (
    TELEGRAM_BOT_TOKEN,
    ADMIN_ID,
    RATE_LIMIT_USER_WINDOW_SEC,
    RATE_LIMIT_USER_MAX_REQUESTS,
    RATE_LIMIT_ADMIN_MAX_REQUESTS
)
from src.core import database, ai_service, config
from src.core.i18n import normalize_lang, lang_name, t
from src.tools import (
    financial,
    web_network,
    scientific,
    media,
    system,
    github,
    files,
    database as db_tools
)
from src.ui import admin_panel
from src.utils import telegram_formatter
from src.utils.display_name import username_to_persian_name

# Setup Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("PrometheusBot")

# Rate Limiter Memory
_USER_RATE_LIMITS: Dict[int, list] = {}

def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    max_req = RATE_LIMIT_ADMIN_MAX_REQUESTS if user_id == ADMIN_ID else RATE_LIMIT_USER_MAX_REQUESTS
    window = RATE_LIMIT_USER_WINDOW_SEC

    # Active memory maintenance: purge stale user records when map exceeds 2000 users
    if len(_USER_RATE_LIMITS) > 2000:
        stale_users = [uid for uid, ts_list in _USER_RATE_LIMITS.items() if not ts_list or (now - ts_list[-1] > window * 2)]
        for suid in stale_users:
            del _USER_RATE_LIMITS[suid]

    if user_id not in _USER_RATE_LIMITS:
        _USER_RATE_LIMITS[user_id] = []

    _USER_RATE_LIMITS[user_id] = [t for t in _USER_RATE_LIMITS[user_id] if now - t < window]

    if len(_USER_RATE_LIMITS[user_id]) >= max_req:
        return False

    _USER_RATE_LIMITS[user_id].append(now)
    return True

# Per-chat stop/quiet flag: when the Master Admin says stop in a group, the
# bot halts generation for that chat until explicitly resumed. Dict also
# briefly holds in-flight task refs so a running LLM turn can be cancelled.
_STOPPED_CHATS: Dict[int, float] = {}
_INFLIGHT_TURNS: Dict[int, Any] = {}


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def _ulang_of(update) -> tuple:
    """(lang, lang_name) for a Telegram update: 'fa' for Persian clients, else 'en' chrome + full LLM language."""
    try:
        code = (getattr(update.effective_user, "language_code", "") or "fa")
    except Exception:
        code = "fa"
    return normalize_lang(code), lang_name(code)


async def _maybe_translate(update, text: str) -> str:
    """Translate a Persian tool output for non-Persian clients.

    fa clients (and any failure) get the original text untouched, so the
    fast direct-command path stays zero-cost for the home audience.
    """
    try:
        ulang, ulang_name = _ulang_of(update)
        if ulang == "fa" or not isinstance(text, str) or not text.strip():
            return text
        return await ai_service.translate_text(text, ulang_name)
    except Exception:
        return text


def _pingpong_reply(norm_text: str, user_display: str, user_id: int, lang: str = "fa") -> str:
    """Instant deterministic reply for pure social chatter (no LLM, no tools)."""
    t = (norm_text or "").strip().lower()
    is_fa = (lang == "fa")
    if t in ("سلام", "درود", "هی", "های", "hello", "hi", "hey", "salam", "drood"):
        if int(user_id or 0) == int(ADMIN_ID):
            return "👑 درود فرمانده! در خدمتم — بفرمایید." if is_fa else "👑 Hello commander! At your service."
        return "سلام! 👋 چطور کمکتون کنم؟" if is_fa else "Hey! 👋 How can I help?"
    if t in ("خوبی", "چطوری", "چه خبر", "خسته نباشی", "how are you", "how are u", "whats up", "what's up"):
        return "ممنون، عالی‌ام! 💪 شما چطورید؟ چه کمکی از دستم برمیاد؟" if is_fa else "Doing great, thanks! 💪 How about you?"
    if t in ("ممنون", "مرسی", "دمت گرم", "thanks", "thank you", "thx", "ty"):
        return "خواهش می‌کنم! 🌹 در خدمتم." if is_fa else "You're welcome! 🌹"
    if t in ("باشه", "اوکی", "ok", "okay", "بله", "آره", "اره", "چشم", "حله", "yes", "yeah", "sure", "alright"):
        return "حله! ✅" if is_fa else "Got it! ✅"
    if t in ("نه", "no", "nope"):
        return "باشه، مشکلی نیست. 👍" if is_fa else "No problem. 👍"
    return "جانم؟ 🙂" if is_fa else "Yes? 🙂"

async def reply_safely(message, text: str, reply_markup=None):
    """Safely formats markdown to HTML and sends message with fallback + 4096-char chunking."""
    if not text or not str(text).strip():
        return None
    formatted = telegram_formatter.markdown_to_telegram_html(text)

    async def _send_one(chunk: str, markup=None):
        try:
            return await message.reply_text(chunk, parse_mode=ParseMode.HTML, reply_markup=markup)
        except Exception as e:
            logger.debug(f"HTML Parse error, falling back to plain text: {e}")
            try:
                # Plain-text fallback must also respect the 4096 limit.
                return await message.reply_text(chunk[:3900] if len(chunk) > 3900 else chunk, reply_markup=markup)
            except Exception as e2:
                logger.error(f"Failed to send reply: {e2}")
                return None

    # Telegram hard limit is 4096 chars — split long answers instead of failing silently.
    if len(formatted) <= 4000 and len(str(text)) <= 4000:
        return await _send_one(formatted, reply_markup)

    # Prefer splitting the already-formatted HTML on newlines to keep tags intact.
    chunks: list[str] = []
    buf = ""
    for line in formatted.split("\n"):
        if len(buf) + len(line) + 1 > 3800:
            if buf.strip():
                chunks.append(buf)
            buf = line
            # Single huge line (e.g. a link dump) — hard cut it.
            while len(buf) > 3800:
                chunks.append(buf[:3800])
                buf = buf[3800:]
        else:
            buf = (buf + "\n" + line) if buf else line
    if buf.strip():
        chunks.append(buf)
    # Keep replies readable: max 4 chunks (~15k chars), truncate the rest.
    if len(chunks) > 4:
        chunks = chunks[:4]
        chunks[-1] += "\n\n… [ادامه به دلیل سقف تلگرام خلاصه شد]"

    sent = None
    for i, ch in enumerate(chunks):
        sent = await _send_one(ch, reply_markup if i == 0 else None)
        if sent is None:
            break
    return sent


async def global_banned_user_gatekeeper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ABSOLUTE ZERO-RESPONSE GATEKEEPER:
    Intercepts EVERY incoming update (messages, commands, callbacks, inline queries)
    BEFORE any command or handler sees it. If the sender (user_id or username) is banned,
    it STOPS the handler chain immediately with ApplicationHandlerStop and drops the event
    in microseconds with ZERO response, complete radio silence, and zero processing.
    """
    user = update.effective_user
    if user:
        u_uname = user.username or ""
        try:
            _banned = database.is_user_banned(user.id, username=u_uname)
        except Exception:
            _banned = False
        if _banned:
            # Complete radio silence: kill update processing instantly
            raise ApplicationHandlerStop()
        try:
            _muted_left = database.is_user_muted(user.id, username=u_uname)
        except Exception:
            _muted_left = 0
        if _muted_left:
            try:
                _mid = update.effective_message.message_id if update.effective_message else 0
                _cid = update.effective_chat.id if update.effective_chat else 0
                _ct = update.effective_chat.title if update.effective_chat and getattr(update.effective_chat, "title", None) else ""
                _mt = update.effective_message.text or update.effective_message.caption or "" if update.effective_message else ""
                if _mt:
                    await database.save_message_async(_cid, user.id, "user", f"[MUTED-ARCHIVE] {_mt}", user_name=user.first_name or "x", username=u_uname, chat_title=_ct, message_id=_mid or 0)
            except Exception:
                pass
            raise ApplicationHandlerStop()

async def global_application_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Global Unhandled Exception Sink:
    Catches all unexpected exceptions across telegram updates, network timeouts, or API conflicts,
    logging detailed diagnostics without crashing the application event loop.
    """
    err = context.error
    logger.error(f"Global Application Handler caught exception: {err}", exc_info=err)

# ==========================================
# 1. Telegram Standard Commands
# ==========================================


async def group_command_gatekeeper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Global Group Slash-Command Gatekeeper:
    - Bypasses private chats (PV allows all commands freely).
    - In groups/supergroups, checks if a slash command is explicitly directed to Prometheus:
        a) Explicitly targets the bot username: /cmd@Prometheusbaibot
        b) Has the Prometheus suffix: /<cmd>_prometheus (or /<cmd>_prometheus@...)
    - Any other slash command (e.g. /clean, /settings, /ban@otherbot, or bare /clear)
      is SILENTLY archived to Cloudflare D1 and dropped via ApplicationHandlerStop.
    """
    chat = update.effective_chat
    message = update.effective_message
    user = update.effective_user

    if not chat or not message or not user:
        return

    # Private chat is exempt: commands run freely
    if chat.type == ChatType.PRIVATE:
        return

    raw_text = (message.text or message.caption or "").strip()
    if not raw_text.startswith("/"):
        return

    # Extract command token
    command_token = raw_text.split()[0][1:]  # strip leading '/'
    parts = command_token.split("@")
    cmd_name = parts[0].lower()
    target_bot = parts[1].lower() if len(parts) > 1 else None

    bot_uname = (getattr(context.bot, "username", None) or "Prometheusbaibot").lower()

    # Check if explicitly directed to Prometheus
    is_directed = False
    if target_bot:
        if target_bot == bot_uname:
            is_directed = True
    elif cmd_name.endswith("_prometheus"):
        is_directed = True

    if not is_directed:
        # Silently archive the foreign/other-bot command to Cloudflare D1
        chat_title = chat.title or "گروه"
        user_display = user.first_name or user.username or "کاربر"
        user_uname = user.username or ""
        _ctype = str(getattr(chat, "type", "") or "group")

        _rmid, _ruser, _rtext = 0, "", ""
        if message.reply_to_message:
            _rmid = message.reply_to_message.message_id or 0
            _rfu = message.reply_to_message.from_user
            _ruser = (_rfu.first_name if _rfu else "") or ""
            _rtext = (message.reply_to_message.text or message.reply_to_message.caption or "")[:200]

        await database.save_message_async(
            chat.id,
            user.id,
            "user",
            raw_text,
            user_name=user_display,
            username=user_uname,
            chat_title=chat_title,
            message_id=message.message_id or 0,
            chat_type=_ctype,
            msg_kind="command",
            reply_to_msg_id=_rmid,
            reply_to_user=_ruser,
            reply_to_text=_rtext,
        )

        # Stop propagation: zero command execution, zero AI trigger
        raise ApplicationHandlerStop()


class PrometheusGroupCommandFilter(filters.MessageFilter):
    """
    In private chats: allow all commands.
    In groups/channels: ONLY allow if the command ends with '_prometheus'
    or explicitly targets @Prometheusbaibot.
    Foreign commands (e.g. /clean, /clean@otherbot, /settings) are blocked from triggering.
    """
    def filter(self, message):
        if not message.text:
            return False
        try:
            _ctype = getattr(message.chat, "type", "")
            _ctype_s = str(_ctype).lower()
        except Exception:
            _ctype_s = ""
        # PTB v20+: Chat.type is a ChatType enum, not a plain string.
        if _ctype_s in ("private", "chatprivate") or _ctype == ChatType.PRIVATE:
            return True
        first_token = message.text.strip().split()[0].lower()
        return "@prometheusbaibot" in first_token or first_token.endswith("_prometheus")

PROMETHEUS_CMD_FILTER = PrometheusGroupCommandFilter()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    message = update.effective_message

    if not user or not message or database.is_user_banned(user.id, username=user.username or ""):
        return

    ulang, _ = _ulang_of(update)
    if chat and chat.type == ChatType.PRIVATE and not is_admin(user.id):
        await reply_safely(message, t(ulang, "pv_locked"))
        return

    welcome_text = t(ulang, "welcome", name=(user.first_name or "friend"))

    await reply_safely(
        message,
        welcome_text,
        reply_markup=admin_panel.get_start_keyboard(),
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    if not user or not message or database.is_user_banned(user.id, username=user.username or ""):
        return
    ulang, _ = _ulang_of(update)
    await reply_safely(message, t(ulang, "help_text"))

async def tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    if not user or not message or database.is_user_banned(user.id, username=user.username or ""):
        return
    ulang, _ = _ulang_of(update)
    await message.reply_text(
        t(ulang, "toolbox_title"),
        reply_markup=admin_panel.get_tools_keyboard(),
        parse_mode=ParseMode.HTML
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    chat = update.effective_chat
    if not is_admin(user.id):
        await message.reply_text("⛔ دسترسی غیرمجاز! این بخش مختص فرمانده ارشد سیستم است.")
        return

    is_pv = (chat.type == ChatType.PRIVATE)
    if not is_pv:
        await message.reply_text("🔒 <b>فرمانده عزیز:</b>\nبه جهت حفاظت از کلیدها و امنیت پیکربندی سیستم، پنل مدیریت تنها در پیوی (چت خصوصی) قابل بازگشایی است؛ لطفاً به پیوی ربات مراجعه فرمایید.", parse_mode=ParseMode.HTML)
        return

    await message.reply_text(
        "👑 <b>پنل کنترل و فرماندهی پرومته (مختص ادمین ارشد)</b>:",
        reply_markup=admin_panel.get_admin_panel_keyboard(),
        parse_mode=ParseMode.HTML
    )


async def remember_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct admin command to register or view perpetual directives: /remember <directive>"""
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not is_admin(user.id):
        return

    directive_text = " ".join(context.args).strip() if context.args else ""
    if not directive_text and message.reply_to_message:
        directive_text = message.reply_to_message.text or message.reply_to_message.caption or ""

    if not directive_text:
        # Show all active perpetual directives
        directives = database.get_all_admin_memories()
        if directives:
            formatted = "\n".join(f"• <code>{d}</code>" for d in directives)
            await message.reply_text(
                f"🧠 <b>قوانین و فرامین ابدی فعال در حافظه D1:</b>\n\n{formatted}\n\nبرای ثبت دستور جدید:\n<code>/remember &lt;متن دستور&gt;</code>\nبرای فراموشی:\n<code>/forget &lt;متن یا بخشی از دستور&gt;</code>",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.reply_text("🧠 در حال حاضر هیچ دستور ابدی در حافظه D1 ثبت نشده است.\nبرای ثبت:\n<code>/remember &lt;متن دستور&gt;</code>", parse_mode=ParseMode.HTML)
        return

    # Add directive instantly
    await database.add_admin_memory_async(directive_text)
    await message.reply_text(
        f"👑 <b>فرمان حاکمیتی با سرعت نور ثبت شد:</b>\nدستور زیر بلافاصله در حافظه بلادرنگ و دیتابیس ابدی Cloudflare D1 فعال گردید:\n\n«<code>{directive_text}</code>»",
        parse_mode=ParseMode.HTML
    )

async def forget_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct admin command to delete a perpetual directive: /forget <keyword or directive>"""
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not is_admin(user.id):
        return

    keyword = " ".join(context.args).strip() if context.args else ""
    if not keyword:
        await message.reply_text("⚠️ لطفاً متن یا کلمه‌ای از دستوری که می‌خواهید حذف شود را بنویسید:\nمثال: <code>/forget همیشه به من بگو قربان</code>", parse_mode=ParseMode.HTML)
        return

    await database.remove_admin_memory_async(keyword)
    await message.reply_text(
        f"🗑 <b>فرمان اجرا شد:</b>\nدستور منطبق با «<code>{keyword}</code>» بلافاصله از حافظه فعال سیستم و دیتابیس D1 حذف گردید.",
        parse_mode=ParseMode.HTML
    )

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    chat = update.effective_chat
    if not is_admin(user.id):
        await message.reply_text("⛔ دسترسی غیرمجاز! پاکسازی حافظه گفتگو در این چت فقط توسط فرمانده ارشد امکان‌پذیر است.")
        return
    database.clear_chat_context(chat.id)
    await message.reply_text("🧹 <b>کانتکست گفتگو در این چت ریست شد.</b> آماده دریافت فرامین جدید هستم.", parse_mode=ParseMode.HTML)

async def _reply_audio_bytes(message, chat, context, *, title, performer, caption,
                             audio_bytes, duration=None, thumb_url="",
                             thumb_min_bytes=5000, archive_label="موزیک ارسالی"):
    """Single shared MP3-bytes uploader: cover thumb + reply_audio + file_id cache + D1 archive.

    Used by /music AND the AI media pipeline so the upload path exists exactly once.
    Returns the sent telegram Message, or None on failure (caller picks the fallback).
    """
    clean_filename = re.sub(r'[\\/*?:"<>|\r\n\t]', "_", str(title)).strip()[:60] or "track"
    audio_stream = io.BytesIO(audio_bytes)
    audio_stream.name = f"{clean_filename}.mp3"
    thumb_stream = None
    if (thumb_url or "").startswith("http"):
        try:
            from src.core.http import get_http_client as _thumb_client
            th_res = await _thumb_client("web").get(thumb_url, timeout=10.0)
            if th_res.status_code == 200 and len(th_res.content) > thumb_min_bytes:
                thumb_stream = io.BytesIO(th_res.content)
                thumb_stream.name = "cover.jpg"
        except Exception:
            thumb_stream = None
    sent = await message.reply_audio(
        audio=audio_stream,
        title=title,
        performer=performer,
        caption=telegram_formatter.markdown_to_telegram_html(caption or ""),
        parse_mode=ParseMode.HTML,
        duration=duration or None,
        thumbnail=thumb_stream,
        write_timeout=180.0,
        read_timeout=60.0,
    )
    if sent and getattr(sent, "message_id", 0):
        try:
            from src.tools.media import clean_music_query
            _audio_fid = getattr(getattr(sent, "audio", None), "file_id", None)
            if _audio_fid:
                _q_clean = clean_music_query(f"{performer} {title}")
                _fid_payload = json.dumps({
                    "type": "audio_file_id",
                    "file_id": _audio_fid,
                    "title": title,
                    "performer": performer,
                    "caption": caption or "",
                })
                asyncio.create_task(database.kv_set_cache_async(
                    f"music_v2_{_q_clean.replace(' ', '_')}", _fid_payload, expiration_ttl=604800))
        except Exception:
            pass
        asyncio.create_task(database.save_message_async(
            chat.id, context.bot.id, "assistant",
            f"[{archive_label}: {title} — {performer}]",
            user_name="Prometheus",
            chat_title=getattr(chat, "title", "") or "",
            message_id=sent.message_id))
    return sent

async def music_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        ulang, _ = _ulang_of(update)
        await reply_safely(message, t(ulang, "music_usage"))
        return

    await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_VOICE)
    res = await media.download_music_track(query)
    if isinstance(res, dict) and res.get("caption"):
        # Same track, user's language on the caption (audio itself is universal).
        res["caption"] = await _maybe_translate(update, res["caption"])
    if isinstance(res, dict):
        # 1. Native MP3 bytes upload
        if res.get("type") == "audio_bytes" and res.get("bytes"):
            try:
                sent = await _reply_audio_bytes(
                    message, chat, context,
                    title=res.get("title", query),
                    performer=res.get("performer", "Prometheus Audio"),
                    caption=res.get("caption", ""),
                    audio_bytes=res["bytes"],
                    duration=res.get("duration", 0),
                    thumb_url=res.get("thumb", ""),
                    thumb_min_bytes=3000,
                    archive_label="موزیک ارسالی",
                )
                if sent:
                    return
            except Exception as e:
                logger.error(f"Error uploading native MP3 in music_command: {e}")

        # 2. Resilient streaming or direct URL upload (shared pool, size-capped)
        if res.get("url"):
            try:
                from src.core.http import get_http_client as _dl_client_f
                audio_url = res["url"]
                audio_buf = io.BytesIO()
                dl_client = _dl_client_f("stream")
                async with dl_client.stream("GET", audio_url) as r_stream:
                    if r_stream.status_code == 200:
                        _total = 0
                        async for chunk in r_stream.aiter_bytes(65536):
                            _total += len(chunk)
                            if _total > 25 * 1024 * 1024:
                                break
                            audio_buf.write(chunk)
                raw_bytes = audio_buf.getvalue()
                if len(raw_bytes) >= 1500000:
                    sent = await _reply_audio_bytes(
                        message, chat, context,
                        title=res.get("title", query),
                        performer=res.get("performer", "Prometheus Audio"),
                        caption=res.get("caption", ""),
                        audio_bytes=raw_bytes,
                        archive_label="موزیک ارسالی",
                    )
                    if sent:
                        return
            except Exception as e:
                logger.debug(f"Direct stream download in music_command failed: {e}")

            # Direct Telegram stream URL fallback
            try:
                await message.reply_audio(
                    audio=res["url"],
                    title=res.get("title", query),
                    performer=res.get("performer", "Prometheus Audio"),
                    caption=telegram_formatter.markdown_to_telegram_html(res.get("caption", "")),
                    parse_mode=ParseMode.HTML,
                    write_timeout=180.0,
                    read_timeout=60.0
                )
                return
            except Exception as e2:
                logger.error(f"Fallback audio send in music_command failed: {e2}")

        await reply_safely(message, res.get("caption") or res.get("message", "خطا در دریافت فایل موزیک."))
    else:
        await reply_safely(message, str(res))

async def crypto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    sym = " ".join(context.args).strip() if context.args else "BTC"
    res = await financial.get_price(sym)
    await reply_safely(message, await _maybe_translate(update, res))

async def gold_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    res = await financial.get_gold_and_coin_price()
    await reply_safely(message, await _maybe_translate(update, res))

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    city = " ".join(context.args).strip() if context.args else "Tehran"
    res = await web_network.get_weather(city)
    await reply_safely(message, await _maybe_translate(update, res))

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    q = " ".join(context.args).strip() if context.args else ""
    if not q:
        ulang, _ = _ulang_of(update)
        await reply_safely(message, t(ulang, "search_usage"))
        return
    res = await web_network.web_search(q)
    res = await _maybe_translate(update, f"🔍 *نتایج جستجوی وب برای «{q}»:*\n\n{res}")
    await reply_safely(message, res)

async def calc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    expr = " ".join(context.args).strip() if context.args else ""
    if not expr:
        ulang, _ = _ulang_of(update)
        await reply_safely(message, t(ulang, "calc_usage"))
        return
    res = scientific.calculate_math_expression(expr)
    await reply_safely(message, await _maybe_translate(update, res))

async def groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.tools.admin import group_manager
    user = update.effective_user
    message = update.effective_message
    chat = update.effective_chat
    if not user or not message or not is_admin(user.id):
        await message.reply_text("⛔ دسترسی غیرمجاز! این بخش مختص فرمانده ارشد سیستم است.")
        return

    is_pv = (chat.type == ChatType.PRIVATE)
    res = await group_manager.list_joined_groups_tool(caller_id=user.id, is_private_chat=is_pv)
    await reply_safely(message, res)


async def channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows public channels connected to the bot (Allowed in all groups and private chats)."""
    from src.tools.admin import group_manager
    message = update.effective_message
    res = await group_manager.list_public_channels_tool()
    await reply_safely(message, res)


async def bangroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bans and permanently leaves a group by name or chat_id: /bangroup <group name or id>"""
    from src.tools.admin import group_manager
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not is_admin(user.id):
        return
    target = " ".join(context.args).strip() if context.args else ""
    if not target and message.reply_to_message:
        target = str(update.effective_chat.id)
    if not target:
        await reply_safely(message, "🚫 <b>مسدودسازی کامل گروه:</b>\nنام یا شناسه گروه را وارد کنید:\nمثال: <code>/bangroup گروه تست</code> یا <code>/bangroup -100123456789</code>")
        return
    res = await group_manager.ban_group_by_name_or_id_tool(group_name=target, caller_id=user.id)
    await reply_safely(message, res)

async def leave_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from src.tools.admin import group_manager
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not is_admin(user.id):
        await message.reply_text("⛔ دسترسی غیرمجاز! این بخش مختص فرمانده ارشد سیستم است.")
        return
    target = " ".join(context.args).strip() if context.args else ""
    if message.reply_to_message and not target:
        pass
    if not target:
        await reply_safely(message, "🚪 *خروج از گروه:*\nشناسه عددی یا بخشی از نام گروه را وارد کنید. مثال:\n`/leave_prometheus -100123456789`\nبرای دیدن لیست گروه‌ها: `/groups_prometheus`")
        return
    res = await group_manager.leave_group_by_admin_tool(chat_identifier=target, caller_id=user.id)
    await reply_safely(message, res)

async def net_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    target = " ".join(context.args).strip() if context.args else ""
    if not target:
        ulang, _ = _ulang_of(update)
        await reply_safely(message, t(ulang, "net_usage"))
        return
    status = await web_network.check_website_status(target)
    dns = await web_network.resolve_dns(target)
    await reply_safely(message, await _maybe_translate(update, f"{status}\n\n{dns}"))

async def code_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    chat = update.effective_chat
    if not user or not message or not is_admin(user.id):
        await reply_safely(message, "⛔ <b>دسترسی غیرمجاز:</b>\nاجرای شل و کدهای سیستمی روی سرور منحصراً در انحصار شخص فرمانده ارشد سیستم است.")
        return

    code_text = " ".join(context.args).strip() if context.args else ""
    if not code_text and message.reply_to_message:
        code_text = message.reply_to_message.text or ""
    if not code_text:
        ulang, _ = _ulang_of(update)
        await reply_safely(message, t(ulang, "code_usage"))
        return
    caller_id = user.id if user else 0
    is_pv = (chat.type == ChatType.PRIVATE)
    res = await system.execute_python_code(code_text, caller_id=caller_id, is_private_chat=is_pv)
    await reply_safely(message, res)

async def sh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct Terminal Shell Command (Bash/Linux) - Exclusively for Master Admin."""
    user = update.effective_user
    message = update.effective_message
    chat = update.effective_chat
    if not user or not message or not is_admin(user.id):
        await reply_safely(message, "⛔ <b>دسترسی غیرمجاز:</b>\nاجرای دستورات ترمینال و شل لینوکس روی سرور منحصراً در انحصار شخص فرمانده ارشد سیستم است.")
        return

    is_pv = (chat.type == ChatType.PRIVATE)

    cmd_text = " ".join(context.args).strip() if context.args else ""
    if not cmd_text and message.reply_to_message:
        cmd_text = message.reply_to_message.text or ""

    # Red line 3: destructive shell stays blocked even for the Master Admin.
    if system.is_destructive_shell_command(cmd_text.strip()):
        await reply_safely(message, "⛔ این دستور شل مخرب/حساس است و هرگز اجرا نمی‌شود (حتی به دستور ادمین).")
        return

    if not cmd_text:
        ulang, _ = _ulang_of(update)
        await reply_safely(message, t(ulang, "sh_usage"))
        return

    import asyncio.subprocess as _asp
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd_text,
            stdout=_asp.PIPE,
            stderr=_asp.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=12.0)
            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()
            result_str = out if out else (err if err else "(دستور بدون خروجی متنی با موفقیت پایان یافت)")
            
            # Mask sensitive tokens/passwords if executed inside a group
            masked_str, redacted = system.mask_sensitive_shell_output(result_str, is_private_chat=is_pv)
            if len(masked_str) > 3500:
                masked_str = masked_str[:3500] + "\n... [خروجی به دلیل محدودیت تلگرام خلاصه شد]"
            
            group_notice = "\n\n🔒 <i>[برای اطلاعات کامل به پیوی مراجعه بکنید.]</i>" if (not is_pv and not redacted) else ""
            await message.reply_text(
                f"💻 <b>فرمان لینوکس اجرا شد:</b> <code>{cmd_text}</code>\n\n<pre><code>{masked_str}</code></pre>{group_notice}",
                parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            await message.reply_text("⏱ زمان اجرای دستور شل به پایان رسید (Timeout 12s).")
    except Exception as e:
        await message.reply_text(f"❌ خطای اجرای شل:\n<code>{str(e)}</code>", parse_mode=ParseMode.HTML)


async def e2b_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """E2B cloud sandbox runner: /e2b <python code> | /e2b js <code> | reply-to-code."""
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not is_admin(user.id):
        await reply_safely(message, "⛔ <b>دسترسی غیرمجاز:</b>\nسندباکس ابری E2B فقط در انحصار فرمانده ارشد است.")
        return
    raw = " ".join(context.args).strip() if context.args else ""
    if not raw and message.reply_to_message:
        raw = message.reply_to_message.text or message.reply_to_message.caption or ""
    if not raw:
        ulang, _ = _ulang_of(update)
        await reply_safely(message, t(ulang, "e2b_usage"))
        return
    lang = "python"
    low = raw.lower()
    if low.startswith("js ") or low.startswith("javascript ") or low.startswith("node "):
        lang = "javascript"
        raw = raw.split(" ", 1)[1] if " " in raw else ""
    try:
        from src.tools.system import e2b_sandbox as _e2b
        res = await _e2b.e2b_run_code(raw, language=lang, timeout_sec=30, caller_id=user.id)
    except Exception as e:
        res = f"❌ خطای E2B: {e}"
    await reply_safely(message, res)


async def e2bsh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """E2B cloud shell: /e2bsh <linux command> — filesystem ربات مصون می‌ماند."""
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not is_admin(user.id):
        await reply_safely(message, "⛔ <b>دسترسی غیرمجاز:</b>\nسندباکس ابری E2B فقط در انحصار فرمانده ارشد است.")
        return
    cmd = " ".join(context.args).strip() if context.args else ""
    if not cmd and message.reply_to_message:
        cmd = message.reply_to_message.text or ""
    if not cmd:
        ulang, _ = _ulang_of(update)
        await reply_safely(message, t(ulang, "e2bsh_usage"))
        return
    try:
        from src.tools.system import e2b_sandbox as _e2b2
        res = await _e2b2.e2b_run_command(cmd, timeout_sec=30, caller_id=user.id)
    except Exception as e:
        res = f"❌ خطای E2B: {e}"
    await reply_safely(message, res)


async def e2bstatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not is_admin(user.id):
        return
    try:
        from src.tools.system import e2b_sandbox as _e2b3
        res = await _e2b3.e2b_status(caller_id=user.id)
    except Exception as e:
        res = f"❌ خطای E2B: {e}"
    await reply_safely(message, res)


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct instant admin ban command: /ban <id|username> [reason] or replied to a target user"""
    user = update.effective_user
    message = update.effective_message
    chat = update.effective_chat
    if not user or not message or not is_admin(user.id):
        return

    target_user = message.reply_to_message.from_user if message.reply_to_message else None
    args = context.args or []
    target_str = ""
    reason = "دستور مستقیم فرمانده"
    first_name = ""
    username = ""

    if target_user:
        target_str = str(target_user.id)
        if args:
            reason = " ".join(args).strip()
        first_name = target_user.first_name or ""
        username = target_user.username or ""
    elif args:
        target_str = args[0].strip()
        if len(args) > 1:
            reason = " ".join(args[1:]).strip()
        first_name = ""
        username = target_str if target_str.startswith("@") else ""
    else:
        await reply_safely(message, "⚠️ فرمت دستور:\n<code>/ban &lt;شناسه یا @username یا نام فرد&gt; [علت]</code>\nیا روی پیام کاربر دستور /ban را ریپلای کنید.")
        return

    # Call high-speed instant ban
    res = await system.ban_user_tool(
        target=target_str,
        reason=reason,
        first_name=first_name,
        caller_id=user.id,
        chat_id=chat.id,
        source_chat_title=chat.title or ""
    )
    # Also delete the target message if banned on reply
    if message.reply_to_message:
        try:
            await message.reply_to_message.delete()
        except Exception:
            pass
    await reply_safely(message, res)

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct instant admin unban command: /unban <id|username> or replied to a target user"""
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not is_admin(user.id):
        return

    target_user = message.reply_to_message.from_user if message.reply_to_message else None
    args = context.args or []
    target_str = ""

    if target_user:
        target_str = str(target_user.id)
    elif args:
        target_str = args[0].strip()
    else:
        await reply_safely(message, "⚠️ فرمت دستور:\n<code>/unban &lt;شناسه یا @username&gt;</code>\nیا روی پیام کاربر دستور /unban را ریپلای کنید.")
        return

    res = await system.unban_user_tool(
        target=target_str,
        caller_id=user.id
    )
    await reply_safely(message, res)


async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    chat = update.effective_chat
    if not user or not message or not is_admin(user.id):
        return
    target_user = message.reply_to_message.from_user if message.reply_to_message else None
    args = list(context.args or [])
    target_str = ""
    first_name = ""
    if target_user:
        target_str = str(target_user.id)
        first_name = target_user.first_name or ""
    elif args:
        target_str = args.pop(0).strip()
    else:
        await reply_safely(message, "⚠️ فرمت: <code>/mute &lt;شناسه یا @username&gt; [مدت]</code> یا روی پیام کاربر ریپلای کنید. مثال: <code>/mute 12345 نیم ساعت</code>")
        return
    dur_text = " ".join(args).strip() if args else (message.text or "")
    secs = database.parse_mute_duration_to_sec(dur_text) if dur_text else 0
    if not secs:
        secs = 1800
    res = await system.mute_user_tool(target=target_str, duration_sec=secs, first_name=first_name, caller_id=user.id, chat_id=chat.id if chat else 0, source_chat_title=chat.title if chat else "")
    await reply_safely(message, res)


async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not is_admin(user.id):
        return
    target_user = message.reply_to_message.from_user if message.reply_to_message else None
    args = context.args or []
    if target_user:
        target_str = str(target_user.id)
    elif args:
        target_str = args[0].strip()
    else:
        await reply_safely(message, "⚠️ فرمت: <code>/unmute &lt;شناسه یا @username&gt;</code> یا روی پیام کاربر ریپلای کنید.")
        return
    res = await system.unmute_user_tool(target=target_str, caller_id=user.id)
    await reply_safely(message, res)


async def mutelist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not is_admin(user.id):
        return
    res = await system.get_muted_users_list_tool(caller_id=user.id)
    await reply_safely(message, res)


async def getid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Direct command to deeply extract numeric User ID: /id <name|username> or replied to a message."""
    user = update.effective_user
    message = update.effective_message
    if not user or not message or not is_admin(user.id):
        return

    target_user = message.reply_to_message.from_user if message.reply_to_message else None
    if target_user:
        uname = f"@{target_user.username}" if target_user.username else "ندارد"
        fname = target_user.first_name or "کاربر"
        uid = target_user.id
        is_banned = database.is_user_banned(uid)
        status_txt = "🚫 مسدود (Banned)" if is_banned else "🟢 فعال (Active)"
        await reply_safely(
            message,
            f"🎯 <b>شناسه عددی پیام ریپلای‌شده:</b>\n• <b>شناسه عددی (ID):</b> <code>{uid}</code>\n• <b>نام:</b> <b>{fname}</b>\n• <b>یوزرنیم:</b> <code>{uname}</code>\n• <b>وضعیت:</b> {status_txt}\n\n<i>💡 برای بن کردن:</i> <code>/ban {uid}</code>"
        )
        return

    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await reply_safely(message, "⚠️ فرمت دستور:\n<code>/id &lt;نام فرد یا @username&gt;</code>\nیا روی پیام فرد ریپلای کنید.")
        return

    res = await system.extract_user_id_tool(target=query, caller_id=user.id)
    await reply_safely(message, res)

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Deletes the replied-to target message (especially the bot's own message or any target message)
    when commanded by the Admin or Group Administrator.
    """
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not user or database.is_user_banned(user.id):
        return

    # Check permissions: Admin or Group Administrator
    is_authorized = is_admin(user.id)
    if not is_authorized and chat.type != ChatType.PRIVATE:
        try:
            member = await chat.get_member(user.id)
            if member.status in [constants.ChatMemberStatus.ADMINISTRATOR, constants.ChatMemberStatus.OWNER]:
                is_authorized = True
        except Exception:
            pass

    if not is_authorized:
        return

    target_msg = message.reply_to_message
    if not target_msg:
        await message.reply_text("⚠️ لطفاً این دستور را روی پیامی از ربات (یا هر پیامی) که می‌خواهید حذف شود ریپلای کنید.")
        return

    # Delete replied message and command message
    try:
        await target_msg.delete()
    except Exception as e:
        logger.warning(f"Failed to delete target message: {e}")

    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Failed to delete command message: {e}")

# ==========================================
# 2. Group Membership Guardian (Auto-Leave)
# ==========================================

async def track_chat_member_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Guardian: If the bot is added to any group by anyone OTHER than the Master Admin (ADMIN_ID),
    it sends an unauthorized notice and immediately leaves the group.
    """
    result = update.my_chat_member
    if not result:
        return

    chat = result.chat
    new_status = result.new_chat_member.status
    inviter = result.from_user

    # When bot is added or promoted in group / supergroup
    if new_status in [constants.ChatMemberStatus.MEMBER, constants.ChatMemberStatus.ADMINISTRATOR]:
        # The bot is now permitted to join and serve in ALL groups without restriction!
        chat_title = chat.title or "گروه"
        inviter_id = inviter.id if inviter else ADMIN_ID
        await database.track_group_presence_async(chat.id, chat_title, chat_type=str(chat.type), added_by=inviter_id)
        logger.info(f"Bot added/promoted in group {chat.id} ({chat_title}) by user {inviter_id}. Tracked in D1.")
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=telegram_formatter.markdown_to_telegram_html(t("fa", "group_hello")),
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass

    # When bot is removed/kicked from group
    elif new_status in [constants.ChatMemberStatus.LEFT, constants.ChatMemberStatus.BANNED]:
        await database.remove_group_presence_async(chat.id)
        logger.info(f"Bot left/kicked from group {chat.id}. Removed from D1 tracking.")

# ==========================================
# 3. Inline Callback Query Router
# ==========================================

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data

    # SILENT DROP for banned users on inline clicks
    if not user or database.is_user_banned(user.id, username=user.username or ""):
        try:
            await query.answer()
        except Exception:
            pass
        return

    # Admin actions
    if data.startswith("admin_"):
        if not is_admin(user.id):
            await query.answer("مختص ادمین ارشد است.", show_alert=True)
            return

        if data in ["admin_dashboard", "admin_status"]:
            await query.answer("در حال بارگذاری تله‌متری سرور...")
            txt = await admin_panel.get_system_status_text_async()
            await query.edit_message_text(txt, reply_markup=admin_panel.get_admin_panel_keyboard(), parse_mode=ParseMode.HTML)

        elif data == "admin_db_health":
            await query.answer("بررسی سلامت دیتابیس...")
            health = await database.get_cache_health_async()
            txt = (
                "⚡ <b>گزارش تفصیلی سلامت دیتابیس ابری و لایه‌های کش:</b>\n\n"
                f"• <b>اتصال دیتابیس Cloudflare D1:</b> {'🟢 فعال' if health.get('d1_reachable') else '🔴 قطع'}\n"
                f"• <b>صف پیام‌های بدون بلاک D1:</b> عمق صف <code>{health.get('d1_queue_depth', 0)}</code>\n"
                f"• <b>ورکر پس‌زمینه Batch Writer:</b> {'🟢 در حال کار' if health.get('d1_batch_worker_alive') else '🔴 متوقف'}\n"
                f"• <b>کلیدهای بارگذاری‌شده در RAM L1:</b> <code>{health.get('l1_keys', 0)}</code> کلید\n"
                f"• <b>وضعیت سیرکیت کلودفلر KV:</b> {'🔴 بسته (محدودیت سقف)' if health.get('kv_circuit_open') else '🟢 باز و عملیاتی'}\n"
                f"• <b>زمان آخرین خطای ثبت‌شده:</b> <code>{health.get('kv_last_cloud_error', 'ندارد')}</code>"
            )
            await query.edit_message_text(txt, reply_markup=admin_panel.get_admin_panel_keyboard(), parse_mode=ParseMode.HTML)

        elif data in ["admin_memory", "admin_memory_sync"]:
            await query.answer("دریافت قوانین ابدی...")
            if data == "admin_memory_sync":
                await database.sync_memory_from_d1_async()
            txt = await admin_panel.get_memory_text_async()
            await query.edit_message_text(txt, reply_markup=admin_panel.get_admin_memory_keyboard(), parse_mode=ParseMode.HTML)

        elif data == "admin_banned_list":
            await query.answer("دریافت لیست سیاه...")
            txt = await admin_panel.get_banned_users_text_async()
            await query.edit_message_text(txt, reply_markup=admin_panel.get_admin_banned_keyboard(), parse_mode=ParseMode.HTML)

        elif data in ["admin_groups_list", "admin_groups_refresh"]:
            await query.answer("استعلام گروه‌های زنده...")
            txt = await admin_panel.get_connected_groups_text_async(bot=context.bot)
            html_txt = telegram_formatter.markdown_to_telegram_html(txt)
            await query.edit_message_text(html_txt, reply_markup=admin_panel.get_admin_groups_keyboard(), parse_mode=ParseMode.HTML)

        elif data == "admin_channels_list":
            await query.answer("استعلام کانال‌ها...")
            ch_res = await system.list_public_channels_tool(caller_id=ADMIN_ID)
            await query.edit_message_text(ch_res, reply_markup=admin_panel.get_admin_panel_keyboard(), parse_mode=ParseMode.HTML)

        elif data == "admin_d1_recent":
            await query.answer("خواندن رکوردهای D1...")
            txt = await admin_panel.get_recent_d1_messages_text_async()
            await query.edit_message_text(txt, reply_markup=admin_panel.get_admin_panel_keyboard(), parse_mode=ParseMode.HTML)

        elif data == "admin_refresh_sync":
            await query.answer("بروزرسانی کش و مموری...", show_alert=True)
            await database.sync_memory_from_d1_async()
            txt = await admin_panel.get_system_status_text_async()
            await query.edit_message_text(txt + "\n\n🔄 <i>تمامی کش‌ها، قوانین ابدی و لیست سیاه با موفقیت از Cloudflare D1 بروزرسانی شدند.</i>", reply_markup=admin_panel.get_admin_panel_keyboard(), parse_mode=ParseMode.HTML)

        elif data == "admin_clear_context":
            database.clear_chat_context(query.message.chat_id)
            await query.answer("کانتکست چت ریست شد.", show_alert=True)

        elif data == "admin_close":
            await query.message.delete()
        return

    # Weather quick buttons
    if data.startswith("qweather_"):
        await query.answer(t(normalize_lang(user.language_code), "loading"))
        city = data.replace("qweather_", "")
        res = await web_network.get_weather(city)
        await reply_safely(query.message, await _maybe_translate(update, res), reply_markup=admin_panel.get_weather_quick_keyboard())
        return

    # Tools navigation
    if data == "open_toolbox_main":
        await query.answer()
        ulang_tb, _ = _ulang_of(update)
        await query.edit_message_text(telegram_formatter.markdown_to_telegram_html(t(ulang_tb, "toolbox_title")), reply_markup=admin_panel.get_tools_keyboard(), parse_mode=ParseMode.HTML)
    elif data == "tool_crypto":
        await query.answer(t(normalize_lang(user.language_code), "loading"))
        res = await financial.get_crypto_overview()
        await reply_safely(query.message, await _maybe_translate(update, res))
    elif data == "tool_gold":
        await query.answer(t(normalize_lang(user.language_code), "loading"))
        res = await financial.get_gold_and_coin_price()
        await reply_safely(query.message, await _maybe_translate(update, res))
    elif data == "tool_news":
        await query.answer(t(normalize_lang(user.language_code), "loading"))
        res = await web_network.live_news("general")
        await reply_safely(query.message, await _maybe_translate(update, f"📰 *اخبار فوری جهان:*\n\n{res}"))
    elif data == "tool_weather_menu":
        await query.answer()
        ulang_wm, _ = _ulang_of(update)
        await query.message.reply_text(t(ulang_wm, "choose_city"), reply_markup=admin_panel.get_weather_quick_keyboard())
    elif data == "tool_network_menu":
        await query.answer()
        ulang_nm, _ = _ulang_of(update)
        await reply_safely(query.message, t(ulang_nm, "network_menu"), reply_markup=admin_panel.get_network_tools_keyboard())
    elif data == "tool_time":
        await query.answer(t(normalize_lang(user.language_code), "loading"))
        t_info = scientific.get_current_datetime_info()
        await reply_safely(query.message, await _maybe_translate(update, t_info))
    elif data in ["tool_net_ip_prompt", "tool_net_dns_prompt", "tool_net_ssl_prompt"]:
        await query.answer()
        hints = {
            "tool_net_ip_prompt": "\U0001F50D *استعلام IP:*\n`get_ip_info` — مثال: `1.1.1.1` یا `google.com` را ارسال کنید.",
            "tool_net_dns_prompt": "\U0001F4CB *رکوردهای DNS:* نام دامنه را ارسال کنید (مثال: `google.com`).",
            "tool_net_ssl_prompt": "\U0001F512 *بررسی SSL:* نام دامنه را ارسال کنید (مثال: `github.com`)."
        }
        await reply_safely(query.message, hints[data])
        return
    elif data in ["tool_calc_menu", "tool_hash_menu", "tool_units_menu", "tool_telegraph", "tool_qr", "tool_music_menu"]:
        await query.answer(t(normalize_lang(user.language_code), "use_menu_hint"), show_alert=True)
    else:
        # Unknown/dead callback (e.g. stale buttons): never leave the spinner hanging
        try:
            await query.answer(t(normalize_lang(user.language_code), "expired"), show_alert=False)
        except Exception:
            pass

# ==========================================
# 4. Main Message & Vision Pipeline
# ==========================================

async def main_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    # SILENT DROP: If user is banned (by ID or username), completely ignore with ZERO response
    try:
        _banned_here = bool(user) and database.is_user_banned(user.id, username=user.username or "")
    except Exception:
        _banned_here = False
    if not user or not message or _banned_here:
        return

    # TEMP MUTE: admin-silenced users get ZERO bot replies until expiry.
    # Their messages are still archived to D1 (memory intact), but the bot
    # never answers, reacts, or transcribes for them while muted.
    try:
        _mute_left = database.is_user_muted(user.id, username=user.username or "")
    except Exception:
        _mute_left = 0
    if _mute_left and not is_admin(user.id):
        try:
            _mt = message.text or message.caption or ""
            if _mt:
                _mu = user.username or ""
                _md = user.first_name or "کاربر"
                _ct = chat.title if chat else "گروه"
                await database.save_message_async(chat.id, user.id, "user", f"[سکوت موقت] {_mt}", user_name=_md, username=_mu, chat_title=_ct, message_id=message.message_id or 0)
        except Exception:
            pass
        return

    if not check_rate_limit(user.id):
        ulang_rl, _ = _ulang_of(update)
        await message.reply_text(t(ulang_rl, "rate_limited"))
        return

    is_pv = (chat.type == ChatType.PRIVATE)

    # PRIVATE CHAT LOCK: Private chat (PV) is exclusively open for Master Admin.
    # Non-admin users attempting to talk in PV are politely directed to groups or rejected.
    if is_pv and not is_admin(user.id):
        ulang_pv, _ = _ulang_of(update)
        await reply_safely(message, t(ulang_pv, "pv_locked"))
        return

    ulang, ulang_name = _ulang_of(update)
    user_text = message.text or message.caption or ""
    user_uname = user.username or ""
    fa_from_uname = username_to_persian_name(user_uname) if (user_uname and ulang == "fa") else ""
    user_display = fa_from_uname or user.first_name or ("کاربر" if ulang == "fa" else "user")

    # Check fast natural language administrative actions from Master Admin on reply (Delete / Ban / Unban)
    # NOTE: non-admin replies fall THROUGH to the normal group gate below —
    # an empty reply-to-bot then answers the quoted message (fixed last pass).
    if message.reply_to_message and is_admin(user.id) and user_text.strip():
        clean_cmd = user_text.strip().lower()
        target_user = message.reply_to_message.from_user

        # 1. Direct Delete ("حذف", "پاک کن", "del", "delete")
        if clean_cmd in ["حذف", "پاکش کن", "حذفش کن", "پاک کن", "حذف کن", "del", "delete", "/del", "/delete"]:
            try:
                await message.reply_to_message.delete()
            except Exception as e:
                logger.warning(f"Failed to delete replied message: {e}")
            try:
                await message.delete()
            except Exception as e:
                logger.warning(f"Failed to delete admin trigger message: {e}")
            # Do NOT send any extra reply message! Complete silent deletion.
            return

        # 2. Direct Reply Ban ("بن", "مسدود", "ban", "بنش کن", "مسدودش کن")
        elif clean_cmd in ["بن", "بنش کن", "مسدود", "مسدودش کن", "ban", "/ban"] and target_user:
            if target_user.id == ADMIN_ID:
                await message.reply_text("👑 فرمانده ارشد دارای مصونیت ابدی است.")
                return
            target_uname = target_user.username or ""
            target_uid = target_user.id
            target_fname = target_user.first_name or ""
            src_chat_title = chat.title or ""
            await database.ban_target_async(
                target_uid,
                reason="دستور مستقیم فرمانده بر روی پیام",
                first_name=target_fname,
                banned_by=user.id,
                source_chat_id=chat.id,
                source_chat_title=src_chat_title
            )
            if target_uname:
                await database.ban_target_async(
                    f"@{target_uname}",
                    reason="دستور مستقیم فرمانده بر روی پیام",
                    first_name=target_fname,
                    banned_by=user.id,
                    source_chat_id=chat.id,
                    source_chat_title=src_chat_title
                )

            target_name = target_fname or f"کاربر {target_uid}"
            uname_text = f" (<code>@{target_uname}</code>)" if target_uname else " (فاقد یوزرنیم)"
            await message.reply_text(
                f"🚫 <b>فرمان اجرا شد:</b>\nکاربر <b>{target_name}</b>{uname_text} با شناسه عددی <code>{target_uid}</code> با موفقیت در دیتابیس ابدی Cloudflare D1 مسدود گردید.",
                parse_mode=ParseMode.HTML
            )
            return

        # 3. Direct Reply Unban ("آنبن", "آن بن", "انبن", "unban", "آزادش کن")
        elif clean_cmd in ["آنبن", "آن بن", "انبن", "unban", "/unban", "آزادش کن", "آنبنش کن"] and target_user:
            target_uname = target_user.username or ""
            target_uid = target_user.id
            await database.unban_target_async(target_uid)
            if target_uname:
                await database.unban_target_async(f"@{target_uname}")
            target_name = target_user.first_name or f"کاربر {target_uid}"
            uname_text = f" (<code>@{target_uname}</code>)" if target_uname else " (فاقد یوزرنیم)"
            await message.reply_text(
                f"✅ <b>فرمان اجرا شد:</b>\nکاربر <b>{target_name}</b>{uname_text} با شناسه عددی <code>{target_uid}</code> در دیتابیس Cloudflare D1 رفع مسدودیت گردید.",
                parse_mode=ParseMode.HTML
            )
            return

        # 3b. Direct Reply Mute with duration (MUTE30 / MUTE2H / MUTE1D / MUTE + text)
        elif (clean_cmd == "mute" or clean_cmd.startswith("mute") or clean_cmd in ["/mute"]) and target_user:
            _m = re.match(r"^(mute)\s*(\d+\s*[mhd])?$", clean_cmd)
            _sfx = (_m.group(2) or "").replace(" ", "") if _m else ""
            _dur = 1800
            try:
                if _sfx:
                    _n = int(re.sub(r"[^0-9]", "", _sfx) or 0)
                    _u = re.sub(r"[0-9\s]", "", _sfx).lower()
                    _dur = _n * (60 if _u == "m" else (3600 if _u == "h" else 86400)) if _n else 1800
                else:
                    _dur = database.parse_mute_duration_to_sec(user_text)
                    if not _dur:
                        _dur = 1800
            except Exception:
                _dur = 1800
            if target_user.id == ADMIN_ID:
                await message.reply_text("👑 فرمانده ارشد دارای مصونیت ابدی است.")
                return
            await database.mute_target_async(target_user.id, _dur, "direct-reply-mute", first_name=target_user.first_name or "", muted_by=user.id, source_chat_id=chat.id, source_chat_title=chat.title or "")
            if target_user.username:
                await database.mute_target_async("@" + target_user.username, _dur, "direct-reply-mute", first_name=target_user.first_name or "", muted_by=user.id, source_chat_id=chat.id, source_chat_title=chat.title or "")
            await message.reply_text(f"🔇 <b>سکوت اعمال شد:</b> کاربر تا <b>{database.format_mute_remaining(_dur)}</b> پاسخی دریافت نمی‌کند.", parse_mode=ParseMode.HTML)
            return

        # 3b2. Persian Reply Mute triggers with duration words
        elif (clean_cmd == "سکوت" or clean_cmd.startswith("سکوت") or clean_cmd in ["میوت", "میوتش کن", "سکوتش کن"]) and target_user:
            _dur = database.parse_mute_duration_to_sec(user_text)
            if not _dur:
                _dur = 1800
            if target_user.id == ADMIN_ID:
                await message.reply_text("👑 فرمانده ارشد دارای مصونیت ابدی است.")
                return
            await database.mute_target_async(target_user.id, _dur, "direct-reply-mute-fa", first_name=target_user.first_name or "", muted_by=user.id, source_chat_id=chat.id, source_chat_title=chat.title or "")
            if target_user.username:
                await database.mute_target_async("@" + target_user.username, _dur, "direct-reply-mute-fa", first_name=target_user.first_name or "", muted_by=user.id, source_chat_id=chat.id, source_chat_title=chat.title or "")
            await message.reply_text(f"🔇 <b>سکوت اعمال شد:</b> کاربر تا <b>{database.format_mute_remaining(_dur)}</b> پاسخی دریافت نمی‌کند.", parse_mode=ParseMode.HTML)
            return

        # 3c. Direct Reply Unmute (EN + FA triggers)
        elif (clean_cmd in ["unmute", "/unmute", "un mute", "آنمیوت", "آن میوت", "رفع سکوت"] or clean_cmd.startswith("لغو سکوت")) and target_user:
            await database.unmute_target_async(target_user.id)
            if target_user.username:
                await database.unmute_target_async("@" + target_user.username)
            await message.reply_text("🔊 <b>سکوت لغو شد:</b> ربات دوباره پاسخ می‌دهد.", parse_mode=ParseMode.HTML)
            return

        # 4. Direct Reply Remember ("یادت باشه", "به خاطر بسپار", "ثبت کن")
        elif any(clean_cmd.startswith(p) for p in ["یادت باشه", "به خاطر بسپار", "ثبت کن", "یادت نره"]):
            replied_text = message.reply_to_message.text or message.reply_to_message.caption or ""
            directive_content = clean_cmd
            for p in ["یادت باشه", "به خاطر بسپار", "ثبت کن", "یادت نره"]:
                if directive_content.startswith(p):
                    directive_content = directive_content[len(p):].lstrip(" :,!-").strip()
            final_directive = f"{directive_content} (مرجع: {replied_text})" if (directive_content and replied_text) else (replied_text or directive_content)
            if final_directive:
                await database.add_admin_memory_async(final_directive)
                await message.reply_text(
                    f"👑 <b>فرمان حاکمیتی ثبت شد:</b>\n«<code>{final_directive}</code>»\nبلافاصله در حافظه بلادرنگ و دیتابیس D1 فعال گردید.",
                    parse_mode=ParseMode.HTML
                )
                return

    # Check if bot should respond in group (Supergroup / Group)
    if not is_pv:
        is_reply_to_bot = False
        _bot_id = getattr(context.bot, "id", None) or (int(TELEGRAM_BOT_TOKEN.split(":")[0]) if ":" in TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN.split(":")[0].isdigit() else 0)
        _bot_uname = (getattr(context.bot, "username", None) or "Prometheusbaibot").lower()
        if message.reply_to_message:
            _rep_from = message.reply_to_message.from_user
            if _rep_from:
                if _rep_from.id == _bot_id:
                    is_reply_to_bot = True
                elif (_rep_from.username or "").lower() == _bot_uname:
                    is_reply_to_bot = True
                elif getattr(_rep_from, "is_bot", False) and (_rep_from.first_name or "").lower() in ("prometheus", "پرومته"):
                    is_reply_to_bot = True

        bot_uname = getattr(context.bot, "username", None) or "Prometheusbaibot"
        is_mentioned = False
        if bot_uname and f"@{bot_uname.lower()}" in user_text.lower():
            is_mentioned = True
            user_text = re.sub(rf'@{re.escape(bot_uname)}', '', user_text, flags=re.IGNORECASE).strip()
        elif "@prometheusbaibot" in user_text.lower():
            is_mentioned = True
            user_text = re.sub(r'@prometheusbaibot', '', user_text, flags=re.IGNORECASE).strip()

        # Strict Trigger Policy: Bot ONLY triggers in groups if directly replied to,
        # mentioned via @username, or explicitly called by the name "پرومته" / "prometheus"
        keywords = [
            "پرومته", "prometheus", "پرومتئوس", "پرومتیوس", "پرومتيوس", "پرومتـه"
        ]
        _call_norm = re.sub(r"[\s،,:؛!\-–—?.؟\"'()\[\]]+", " ", user_text).strip().lower()
        _call_tokens = _call_norm.split(" ")
        has_bot_call = False
        for _tok in _call_tokens:
            for _k in keywords:
                if _tok == _k or _tok.startswith(_k):
                    has_bot_call = True
                    break
            if has_bot_call:
                break
        if not has_bot_call and (re.search(r"\bprometheus\b", user_text, re.IGNORECASE) or any(k in _call_norm for k in keywords)):
            has_bot_call = True

    # Master-Admin STOP switch: when the admin says stop in a group, the bot
    # halts generation there (tasks cancelled, turns skipped) until resumed.
    # NOTE: the message is still archived — stopping answers, not memory.
    _STOP_PHRASES = ("پرومته بسه", "پرومته بس کن", "ربات بسه", "ربات بس کن", "بات بسه", "پرومته ساکت", "پرومته خفه", "ساکت شو", "خفه شو",
                       "prometheus stop", "prometheus shut up", "prometheus silence", "prometheus hush", "bot stop")
    _RESUME_PHRASES = ("پرومته ادامه", "پرومته ادامه بده", "ربات ادامه", "ادامه بده پرومته", "شروع کن پرومته",
                       "prometheus continue", "prometheus resume", "prometheus go on", "continue prometheus")
    _norm_stop = re.sub(r"[\s\u200c،,:؛!\-–—?.؟\"'()\[\]]+", " ", user_text).strip().lower()
    if not is_pv and is_admin(user.id):
        if any(_p == _norm_stop or f" {_p} " in f" {_norm_stop} " for _p in _STOP_PHRASES):
            _STOPPED_CHATS[int(chat.id)] = time.time()
            try:
                _t = _INFLIGHT_TURNS.pop(int(chat.id), None)
                if _t is not None and not _t.done():
                    _t.cancel()
            except Exception:
                pass
            try:
                await message.reply_text(t(ulang, "stopped"))
            except Exception:
                pass
            return
        if any(_p in _norm_stop for _p in _RESUME_PHRASES):
            _STOPPED_CHATS.pop(int(chat.id), None)
            try:
                await message.reply_text(t(ulang, "resumed"))
            except Exception:
                pass
            return
    if not is_pv and int(chat.id) in _STOPPED_CHATS:
        return

    # Multi-Group Isolation & 100% Background Archiving:
    # If in group and bot is NOT triggered, silently archive message with complete metadata to D1.
    # NOTE: Foreign slash commands (e.g. /clean, /settings, /clean@otherbot) in groups must NEVER
    # trigger Prometheus. In groups, a command ONLY qualifies as a direct command if it is
    # customized for Prometheus (*_prometheus) or explicitly targets @Prometheusbaibot.
    _first_word = user_text.strip().split()[0].lower() if user_text else ""
    _is_prom_cmd_in_group = bool(_first_word.startswith("/") and (
        _first_word.endswith("_prometheus") or 
        "@prometheusbaibot" in _first_word
    ))
    _is_direct_command = _is_prom_cmd_in_group if not is_pv else bool(user_text and user_text.strip().startswith("/"))

    if not is_pv:
        if not (is_reply_to_bot or is_mentioned or has_bot_call or _is_direct_command):
            chat_title = chat.title or "گروه"
            user_display = user.first_name or user.username or "کاربر"
            user_uname = user.username or ""
            msg_text = message.text or message.caption or ""

            # If user sent a voice/audio note in the background, transcribe it so D1 gets the REAL text spoken!
            # Skipped entirely when no ROUTER_API_KEY (offline Railway deploy) — no crash, just archive the voice tag.
            if (message.voice or message.audio) and not msg_text and (config.ROUTER_API_KEY or "").strip():
                try:
                    from src.core.http import get_http_client as _bg_stt
                    target_a = message.voice or message.audio
                    a_file = await context.bot.get_file(target_a.file_id)
                    a_buf = io.BytesIO()
                    await a_file.download_to_memory(a_buf)
                    raw_a_bytes = a_buf.getvalue()
                    if raw_a_bytes and len(raw_a_bytes) <= 25 * 1024 * 1024:
                        mime_t = "audio/ogg" if message.voice else "audio/mpeg"
                        f_ext = "voice.ogg" if mime_t == "audio/ogg" else "audio.mp3"
                        client = _bg_stt("api")
                        headers = {"Authorization": f"Bearer {config.ROUTER_API_KEY}"}
                        files = {"file": (f_ext, raw_a_bytes, mime_t)}
                        data = {"model": "whisper-1"}
                        r_bg = await client.post(f"{config.ROUTER_BASE_URL}/audio/transcriptions", headers=headers, data=data, files=files, timeout=30.0)
                        if r_bg.status_code == 200:
                            v_txt = r_bg.json().get("text", "").strip()
                            if v_txt:
                                msg_text = f"[پیام صوتی پیاده‌شده]: {v_txt}"
                except Exception as e:
                    logger.debug(f"Background voice transcription error: {e}")

            if not msg_text:
                if message.document:
                    _doc = message.document
                    _mime = getattr(_doc, "mime_type", "") or ""
                    _size = getattr(_doc, "file_size", 0) or 0
                    _size_txt = f" ~{_size // 1024}KB" if _size else ""
                    msg_text = f"[فایل سند: {_doc.file_name or 'document'} ({_mime}{_size_txt})]"
                elif message.photo:
                    _cap = (message.caption or "").strip()
                    msg_text = f"[عکس: {_cap}]" if _cap else "[عکس بدون کپشن]"
                elif message.video:
                    _cap = (message.caption or "").strip()
                    _dur = getattr(message.video, "duration", 0) or 0
                    _dur_txt = f" ({_dur}s)" if _dur else ""
                    msg_text = f"[ویدیو{_dur_txt}: {_cap}]" if _cap else f"[ویدیو بدون کپشن{_dur_txt}]"
                elif message.video_note:
                    _dur = getattr(message.video_note, "duration", 0) or 0
                    msg_text = f"[ویدیو مسیج ({_dur}s)]" if _dur else "[ویدیو مسیج]"
                elif message.sticker:
                    _set = getattr(message.sticker, "set_name", "") or ""
                    msg_text = f"[استیکر: {message.sticker.emoji or ''} (ست {_set})]" if _set else f"[استیکر: {message.sticker.emoji or ''}]"
                elif message.location:
                    _loc = message.location
                    msg_text = f"[لوکیشن: {getattr(_loc, 'latitude', '?')},{getattr(_loc, 'longitude', '?')}]"
                elif message.contact:
                    _c = message.contact
                    msg_text = f"[مخاطب: {getattr(_c, 'first_name', '') or ''} {getattr(_c, 'phone_number', '') or ''}]"
                elif message.poll:
                    _p = message.poll
                    _q = getattr(_p, "question", "") or ""
                    msg_text = f"[نظرسنجی: {_q}]"
                elif getattr(message, "forward_origin", None):
                    _fo = message.forward_origin
                    _src = "منبع ناشناس"
                    try:
                        if hasattr(_fo, "sender_user") and _fo.sender_user:
                            _src = _fo.sender_user.first_name or "کاربر"
                        elif hasattr(_fo, "chat") and _fo.chat:
                            _src = getattr(_fo.chat, "title", "") or "کانال/گروه"
                        elif hasattr(_fo, "sender_user_name") and _fo.sender_user_name:
                            _src = _fo.sender_user_name
                    except Exception:
                        pass
                    _fwd_txt = (message.text or message.caption or "").strip()[:200]
                    msg_text = f"[فوروارد از {_src}: {_fwd_txt}]" if _fwd_txt else f"[فوروارد از {_src} (بدون متن)]"

            # Reply linkage: archive WHO replied to WHOM + WHICH message, so the
            # bot later recalls the thread even when nobody calls its name.
            _reply_link = ""
            try:
                _rm = message.reply_to_message
                if _rm is not None:
                    _ruser = _rm.from_user
                    _rname = (_ruser.first_name if _ruser else "") or "شخص دیگر"
                    _rtext = (_rm.text or _rm.caption or "").strip()[:200]
                    if _rtext:
                        _reply_link = f" [↩️ ریپلای به «{_rname}»: «{_rtext}»]"
                    else:
                        _reply_link = f" [↩️ ریپلای به پیام «{_rname}» (بدون متن)]"
            except Exception:
                pass
            # Rich background auto-save: kind + chat type + reply ids ride as
            # real columns (group/user/date/kind split), not just text tags.
            _bg_kind = "text"
            if message.voice or message.audio:
                _bg_kind = "voice"
            elif message.photo:
                _bg_kind = "photo"
            elif message.video or message.video_note:
                _bg_kind = "video"
            elif message.document:
                _bg_kind = "file"
            elif message.sticker:
                _bg_kind = "sticker"
            elif message.location or message.contact or message.poll:
                _bg_kind = "info"
            elif getattr(message, "forward_origin", None):
                _bg_kind = "forward"
            _bg_ctype = str(getattr(chat, "type", "") or "group")
            _bg_rmid, _bg_ruser, _bg_rtext = 0, "", ""
            try:
                if message.reply_to_message:
                    _bg_rmid = message.reply_to_message.message_id or 0
                    _bg_fu = message.reply_to_message.from_user
                    _bg_ruser = (_bg_fu.first_name if _bg_fu else "") or ""
                    _bg_rtext = (message.reply_to_message.text or message.reply_to_message.caption or "")[:200]
            except Exception:
                pass
            if msg_text:
                msg_text = f"{msg_text}{_reply_link}" if _reply_link else msg_text
                await database.save_message_async(
                    chat.id,
                    user.id,
                    "user",
                    msg_text,
                    user_name=user_display,
                    username=user_uname,
                    chat_title=chat_title,
                    message_id=message.message_id or 0,
                    chat_type=_bg_ctype,
                    msg_kind=_bg_kind,
                    reply_to_msg_id=_bg_rmid,
                    reply_to_user=_bg_ruser,
                    reply_to_text=_bg_rtext,
                )
            return

        # Strip bot trigger name if at the beginning as a whole word/token
        stripped_text = user_text
        for k in ["پرومته", "prometheus", "پرومتئوس", "پرومتیوس", "پرومتيوس", "پرومتـه"]:
            _m = re.match(rf"^{re.escape(k)}([\s:,!؟?\-–—]+|$)", stripped_text, flags=re.IGNORECASE)
            if _m:
                stripped_text = stripped_text[_m.end():].strip()
                break
        
        # If stripping left some content, use it. If user ONLY sent the name (e.g. "پرومته"), keep it as a greeting call!
        user_text = stripped_text if stripped_text else user_text

        if not user_text and not message.photo and not message.voice and not message.audio and not message.reply_to_message:
            return

    # Multimodal image byte holder
    image_bytes = None

    # Robust Audio & Voice Message Transcription Architecture:
    # Handles voice notes, audio files, podcasts, and forwarded voice messages.
    # NOTE: the group trigger-gate is above, so reaching here means the bot IS
    # addressed (PV, reply-to-bot, mention or name-call) — voice always proceeds.
    replied_audio = None
    if message.reply_to_message and not user_text:
        replied_audio = message.reply_to_message.voice or message.reply_to_message.audio
    if message.voice or message.audio or replied_audio:
        target_audio = message.voice or message.audio or replied_audio
        if target_audio:
            voice_failed = False
            try:
                await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
                audio_file = await context.bot.get_file(target_audio.file_id)
                audio_buf = io.BytesIO()
                await audio_file.download_to_memory(audio_buf)
                raw_audio_bytes = audio_buf.getvalue()

                if raw_audio_bytes:
                    mime_type = "audio/ogg" if (message.voice or (message.reply_to_message and message.reply_to_message.voice)) else "audio/mpeg"
                    file_ext = "voice.ogg" if mime_type == "audio/ogg" else "audio.mp3"

                    from src.core.http import get_http_client as _stt_client
                    headers = {"Authorization": f"Bearer {config.ROUTER_API_KEY}"}
                    files = {"file": (file_ext, raw_audio_bytes, mime_type)}
                    data = {"model": "whisper-1"}
                    r = await _stt_client("api").post(f"{config.ROUTER_BASE_URL}/audio/transcriptions", headers=headers, data=data, files=files, timeout=60.0)
                    if r.status_code == 200:
                        transcribed_text = r.json().get("text", "").strip()
                        if transcribed_text:
                            if user_text:
                                user_text = f"{user_text}\n\n[محتوای متن پیاده‌شده از ویس/صوت]: «{transcribed_text}»"
                            else:
                                user_text = f"[پیام صوتی پیاده‌شده]: «{transcribed_text}»"
                        else:
                            voice_failed = True
                    else:
                        voice_failed = True
                        logger.warning(f"Voice transcription HTTP {r.status_code}: {r.text[:200]}")
                else:
                    voice_failed = True
            except Exception as e:
                voice_failed = True
                logger.warning(f"Voice transcription pipeline error: {e}")
            if voice_failed and not user_text:
                # Never go silent on an addressed voice note: say so instead of
                # falling through with an empty prompt.
                await reply_safely(message, t(ulang, "voice_failed"))
                return

    # Build multi-message context if replying to someone else's message.
    # BOTH sides stay visible: the quoted message AND the user's new text are
    # fused into one prompt, so the bot always sees the full thread.
    # NOTE: a bare reply-to-bot with NO new text (e.g. tapping reply then
    # hitting send) must NOT fall through with an empty prompt — answer the
    # quoted message itself instead of going silent.
    if message.reply_to_message:
        replied_msg = message.reply_to_message
        _r_from = replied_msg.from_user
        replied_user = _r_from.first_name if _r_from else "شخص دیگر"
        replied_uname = f"@{_r_from.username}" if (_r_from and _r_from.username) else ""
        replied_text = replied_msg.text or replied_msg.caption or ""
        # Quoted voice/audio: transcribe so BOTH sides are textual.
        _replied_voice_txt = ""
        if not replied_text and (replied_msg.voice or replied_msg.audio):
            try:
                _rv = replied_msg.voice or replied_msg.audio
                _rv_file = await context.bot.get_file(_rv.file_id)
                _rv_buf = io.BytesIO()
                await _rv_file.download_to_memory(_rv_buf)
                _rv_bytes = _rv_buf.getvalue()
                if _rv_bytes:
                    from src.core.http import get_http_client as _rv_client
                    _rv_mime = "audio/ogg" if replied_msg.voice else "audio/mpeg"
                    _rv_ext = "voice.ogg" if replied_msg.voice else "audio.mp3"
                    _rv_r = await _rv_client("api").post(
                        f"{config.ROUTER_BASE_URL}/audio/transcriptions",
                        headers={"Authorization": f"Bearer {config.ROUTER_API_KEY}"},
                        data={"model": "whisper-1"},
                        files={"file": (_rv_ext, _rv_bytes, _rv_mime)},
                        timeout=60.0,
                    )
                    if _rv_r.status_code == 200:
                        _replied_voice_txt = (_rv_r.json().get("text", "") or "").strip()
            except Exception as _e:
                logger.debug(f"Quoted-voice transcription error: {_e}")
        if _replied_voice_txt and not replied_text:
            replied_text = f"[ویس پیاده‌شده]: {_replied_voice_txt}"

        # If the replied message had a photo, extract it for vision analysis
        if replied_msg.photo:
            try:
                r_photo = replied_msg.photo[-1]
                r_photo_file = await context.bot.get_file(r_photo.file_id)
                r_img_buf = io.BytesIO()
                await r_photo_file.download_to_memory(r_img_buf)
                image_bytes = r_img_buf.getvalue()
            except Exception:
                pass

        _who = f"{replied_user} ({replied_uname})" if replied_uname else replied_user
        if replied_text:
            if user_text.strip():
                user_text = f"[پیام ریپلای‌شده از {_who}]: «{replied_text}»\n\n[پیام و دستور من ({user_display})]: {user_text}"
            else:
                user_text = f"[کاربر پیام زیر را از {_who} ریپلای کرده و بدون متن جدید فرستاده؛ همان پیام نقل‌شده را مستقیم پاسخ بده]: «{replied_text}»"
        elif replied_msg.photo:
            _cap_note = f"«{replied_text}» " if replied_text else "(بدون کپشن) "
            if user_text.strip():
                user_text = f"[کاربر روی عکس {_who} {_cap_note}ریپلای کرده]: {user_text}"
            else:
                user_text = f"[کاربر روی عکس {_who} {_cap_note}ریپلای کرده و سوالی نپرسیده؛ عکس را تحلیل و نظر بده]"
        elif replied_msg.sticker:
            _emo = replied_msg.sticker.emoji or ""
            if user_text.strip():
                user_text = f"[کاربر روی استیکر {_who} ({_emo}) ریپلای کرده]: {user_text}"
            else:
                user_text = f"[کاربر روی استیکر {_who} ({_emo}) ریپلای کرده؛ با humor کوتاه واکنش نشان بده]" 
        # Persist the QUOTED message too (it may never have been archived —
        # e.g. bot was offline when first sent). D1 then holds BOTH sides.
        try:
            _q_text = replied_text or f"[ریپلای روی پیام غیرمتنی {_who}]"
            _q_uid = _r_from.id if _r_from else 0
            _q_uname = _r_from.username if (_r_from and _r_from.username) else ""
            _q_name = _r_from.first_name if (_r_from and _r_from.first_name) else replied_user
            await database.save_message_async(
                chat.id, _q_uid or user.id, "user", f"[نقل‌شده] {_q_text}",
                user_name=_q_name, username=_q_uname or "",
                chat_title=chat_title or "", message_id=replied_msg.message_id or 0,
            )
        except Exception:
            pass

    # Multimodal Vision processing on current message
    if message.photo:
        try:
            photo = message.photo[-1]
            photo_file = await context.bot.get_file(photo.file_id)
            img_buffer = io.BytesIO()
            await photo_file.download_to_memory(img_buffer)
            image_bytes = img_buffer.getvalue()
        except Exception as e:
            logger.warning(f"Error downloading photo: {e}")

    # Save user message to database history with full user details, group title and username mapping
    user_uname = user.username or ""
    # Addressing: meaningful username -> Persian name (parham271$ -> پرهام);
    # gibberish username -> no name at all (never guess). Falls back to first_name.
    # Persian addressing only applies to fa clients; everyone else keeps first_name.
    fa_from_uname = username_to_persian_name(user_uname) if (user_uname and ulang == "fa") else ""
    user_display = fa_from_uname or user.first_name or ("کاربر" if ulang == "fa" else "user")
    address_hint = f" (خطاب: {fa_from_uname})" if (ulang == "fa" and fa_from_uname and user.id != ADMIN_ID) else ""
    chat_title = chat.title or ("پیوی" if is_pv else "گروه")
    # Rich auto-save: every reply/thread link, media kind, chat type and
    # Jalali date+time land in BOTH RAM (instant) and D1 (forever), split by
    # group (chat_id), user (user_id/username) and kind — no call needed.
    _save_kind = "text"
    if message.voice:
        _save_kind = "voice"
    elif message.audio:
        _save_kind = "audio"
    elif message.photo:
        _save_kind = "photo"
    elif message.video or message.video_note:
        _save_kind = "video"
    elif message.document:
        _save_kind = "file"
    elif message.sticker:
        _save_kind = "sticker"
    elif message.location or message.contact or message.poll:
        _save_kind = "info"
    elif getattr(message, "forward_origin", None):
        _save_kind = "forward"
    _save_ctype = str(getattr(chat, "type", "") or ("private" if is_pv else "group"))
    _rq_mid, _rq_user, _rq_text = 0, "", ""
    try:
        if message.reply_to_message:
            _rq_mid = message.reply_to_message.message_id or 0
            _rq_fu = message.reply_to_message.from_user
            _rq_user = (_rq_fu.first_name if _rq_fu else "") or ""
            _rq_text = (message.reply_to_message.text or message.reply_to_message.caption or "")[:200]
    except Exception:
        pass
    # Zero-Wait Asynchronous Message Archiving (Fire-and-forget: does not block the critical response path)
    asyncio.create_task(database.save_message_async(chat.id, user.id, "user", user_text, user_name=user_display, username=user_uname, chat_title=chat_title, message_id=message.message_id or 0, chat_type=_save_ctype, msg_kind=_save_kind, reply_to_msg_id=_rq_mid, reply_to_user=_rq_user, reply_to_text=_rq_text))

    # Background self-use prefetch: rewrite + intent-tag + tool-hint while the
    # typing indicator runs, so the AI turn starts with hot context and the
    # model sees a concrete tool suggestion for the exact normalized query.
    _prefetch_hints = {"intent_block": "", "tool_hint": "", "rewritten": ""}

    async def _self_prefetch():
        try:
            from src.tools import internal as _internal
            rewritten = _internal.bot_query_rewriter(user_text)
            _prefetch_hints["rewritten"] = rewritten
            if rewritten.startswith("__PINGPONG__"):
                _prefetch_hints["intent_block"] = "__PINGPONG__"
                return "__PINGPONG__"
            _prefetch_hints["intent_block"] = _internal.bot_intent_splitter(rewritten)
            try:
                _prefetch_hints["tool_hint"] = _internal.bot_tool_picker(rewritten)
            except Exception:
                pass
            try:
                await _internal.bot_smart_cache_put(f"last_query_{chat.id}", rewritten[:300])
            except Exception:
                pass
            try:
                await _internal.bot_history_recall(rewritten.split(" ")[0][:40] if rewritten else "", chat_id=chat.id)
            except Exception:
                pass
            return _prefetch_hints["intent_block"]
        except Exception:
            return ""
    prefetch_task = asyncio.create_task(_self_prefetch())

    # High-Speed Keep-Alive Typing Action (1.5s interval for instant feedback)
    typing_active = True
    async def keep_typing():
        while typing_active:
            try:
                await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
            except Exception:
                pass
            await asyncio.sleep(1.8)

    typing_task = asyncio.create_task(keep_typing())
    _INFLIGHT_TURNS[int(chat.id)] = asyncio.current_task()

    try:
        # Collect prefetch (best-effort, 2s cap) and feed normalized query to AI
        try:
            await asyncio.wait_for(asyncio.shield(prefetch_task), timeout=2.0)
        except Exception:
            pass
        # Run AI Super Agent (numeric-ID admin check + Persian addressing hint + on-demand memory)
        has_reply = bool(message.reply_to_message)
        # --- Sub-Millisecond Deterministic Fast-Path (Zero-LLM Latency Bypass) ---
        # Deterministic single-intent requests (price, time, date, gold, crypto) bypass LLM inference entirely
        # returning verified results in < 50ms without burning router tokens or adding network roundtrips.
        _norm_user = re.sub(r"[!؟?،,.]+", "", user_text).strip().lower()
        _fast_res = None
        if not image_bytes and not bool(message.reply_to_message) and len(_norm_user) < 50:
            # 1. Time / Date Fast Path (< 1ms)
            if _norm_user in ["ساعت", "ساعت چنده", "ساعت چند است", "ساعت الان", "تایم", "time", "what time is it", "current time", "time now", "whats the time"]:
                _t_iso, _t_hm, _t_j = database.get_tehran_timestamps()
                _fast_res = t(ulang, "time_is", hm=_t_hm)
            elif _norm_user in ["تاریخ", "امروز چندمه", "تاریخ امروز", "امروز چندم است", "امروز چندمه؟", "date", "what date is it", "todays date", "today's date", "current date"]:
                _t_iso, _t_hm, _t_j = database.get_tehran_timestamps()
                _fast_res = t(ulang, "date_today", jalali=_t_j, iso=_t_iso)
            # 2. Dollar / Fiat Fast Path
            elif _norm_user in ["قیمت دلار", "دلار", "دلار چنده", "نرخ دلار", "دلار تهران", "دلار چند"]:
                from src.tools import financial as _fin
                _fast_res = await _fin.get_dollar_price()
            elif _norm_user in ["قیمت طلا", "طلا", "سکه", "قیمت سکه", "طلا چنده", "سکه امامی"]:
                from src.tools import financial as _fin
                _fast_res = await _fin.get_gold_and_coin_price()
            elif _norm_user in ["ارزها", "تابلوی ارز", "قیمت ارزها", "قیمت یورو", "درهم", "قیمت تتر", "تتر"]:
                from src.tools import financial as _fin
                _fast_res = await _fin.get_fiat_overview()
            # 3. Major Crypto Fast Path
            elif _norm_user in ["بیتکوین", "بیت کوین", "قیمت بیتکوین", "قیمت بیت کوین", "btc", "bitcoin"]:
                from src.tools import financial as _fin
                _fast_res = await _fin.get_price("BTC")
            elif _norm_user in ["اتریوم", "قیمت اتریوم", "eth", "ethereum"]:
                from src.tools import financial as _fin
                _fast_res = await _fin.get_price("ETH")
            elif _norm_user in ["سولانا", "sol", "قیمت سولانا"]:
                from src.tools import financial as _fin
                _fast_res = await _fin.get_price("SOL")
            elif _norm_user in ["کریپتو", "تابلوی رمزارز", "بازار کریپتو"]:
                from src.tools import financial as _fin
                _fast_res = await _fin.get_crypto_overview()

        if _fast_res:
            ai_response, extra_action = _fast_res, None
        # Ping/pong fast-lane: pure social chatter answers instantly, no LLM burn.
        elif _prefetch_hints.get("intent_block") == "__PINGPONG__" and not image_bytes:
            _norm_pp = (_prefetch_hints.get("rewritten", "").replace("__PINGPONG__", "").strip() or user_text).strip()
            ai_response, extra_action = _pingpong_reply(_norm_pp, user_display, user.id, ulang), None
        else:
            _tool_hint_suffix = ""
            _hint = (_prefetch_hints.get("tool_hint") or "").strip()
            if _hint:
                _tool_hint_suffix = f"\n[پیشنهاد سیستمی ابزار (از تحلیل‌گر داخلی، با اطمینان بالا)]: {_hint}"
            ai_response, extra_action = await ai_service.generate_response(
                chat_id=chat.id,
                user_prompt=user_text + address_hint + _tool_hint_suffix,
                image_bytes=image_bytes,
                caller_user_id=user.id,
                caller_name=user_display,
                caller_username=user_uname,
                is_private_chat=is_pv,
                has_reply_context=has_reply,
                user_lang_code=(user.language_code or "fa"),
            )
    finally:
        typing_active = False
        typing_task.cancel()
        try:
            if _INFLIGHT_TURNS.get(int(chat.id)) is asyncio.current_task():
                _INFLIGHT_TURNS.pop(int(chat.id), None)
        except Exception:
            pass
        if not prefetch_task.done():
            prefetch_task.cancel()

    # Persist assistant turn first (never lose it), then deliver media/text and
    # backfill the real Telegram message_id once the reply is actually sent.
    await database.save_message_async(chat.id, context.bot.id, "assistant", ai_response, user_name="Prometheus", chat_title=chat_title, message_id=0)

    # Global safety net: NO addressed message may ever end without an answer.
    # Any unexpected exception below becomes a Persian apology, never silence.
    try:
        _answered = await _deliver_ai_turn(message, chat, context, ai_response, extra_action, chat_title)
    except Exception as _e:
        logger.error(f"AI turn delivery crashed: {_e}")
        _answered = False
    if not _answered:
        try:
            await reply_safely(message, "⚠️ پاسخ‌گویی لحظه‌ای با اختلال روبه‌رو شد؛ لطفاً پیام خود را یک بار دیگر بفرستید.")
        except Exception:
            pass
    return

async def _deliver_ai_turn(message, chat, context, ai_response, extra_action, chat_title):
    """Sends media/text for one AI turn. Returns True if user got an answer."""
    sent_media_msg_id = 0

    # Instant Sub-Second Delivery via Telegram Cached file_id
    if isinstance(extra_action, dict) and extra_action.get("type") == "audio_file_id" and extra_action.get("file_id"):
        try:
            audio_title = extra_action.get("title", "آهنگ")
            audio_performer = extra_action.get("performer", "موزیک")
            caption_formatted = telegram_formatter.markdown_to_telegram_html(extra_action.get("caption", ""))
            sent_audio = await message.reply_audio(
                audio=extra_action["file_id"],
                title=audio_title,
                performer=audio_performer,
                caption=caption_formatted,
                parse_mode=ParseMode.HTML
            )
            sent_media_msg_id = sent_audio.message_id if sent_audio else 0
            if sent_media_msg_id:
                asyncio.create_task(database.save_message_async(chat.id, context.bot.id, "assistant", f"[موزیک ارسالی فوری: {audio_title} — {audio_performer}]", user_name="Prometheus", chat_title=chat_title, message_id=sent_media_msg_id))
            return True
        except Exception as e:
            logger.warning(f"Failed to send cached audio file_id: {e}")
    # If a document file was created by tool for upload
    if isinstance(extra_action, dict) and extra_action.get("type") == "document" and extra_action.get("bytes"):
        try:
            doc_buf = io.BytesIO(extra_action["bytes"])
            doc_buf.name = extra_action.get("filename", "file.txt")
            sent_doc = await message.reply_document(
                document=doc_buf,
                filename=extra_action.get("filename", "file.txt"),
                caption=telegram_formatter.markdown_to_telegram_html(extra_action.get("caption", "")),
                parse_mode=ParseMode.HTML
            )
            sent_media_msg_id = sent_doc.message_id if sent_doc else 0
            if sent_media_msg_id:
                await database.save_message_async(chat.id, context.bot.id, "assistant", f"[فایل ارسالی: {extra_action.get('filename', 'file.txt')}]" + (f"\n{ai_response}" if ai_response else ""), user_name="Prometheus", chat_title=chat_title, message_id=sent_media_msg_id)
            return True
        except Exception as e:
            logger.error(f"Error uploading generated document to Telegram: {e}")

    # If a full MP3 was downloaded (YouTube strategy) -> upload bytes natively
    if isinstance(extra_action, dict) and extra_action.get("type") == "audio_bytes" and extra_action.get("bytes"):
        try:
            sent_full = await _reply_audio_bytes(
                message, chat, context,
                title=extra_action.get("title", "آهنگ"),
                performer=extra_action.get("performer", "موزیک"),
                caption=extra_action.get("caption", ""),
                audio_bytes=extra_action["bytes"],
                duration=extra_action.get("duration", 0),
                thumb_url=extra_action.get("thumb", ""),
                archive_label="موزیک کامل ارسالی",
            )
            if sent_full:
                return True
        except Exception as e:
            logger.error(f"Error uploading full MP3 bytes: {e}")

    # If an audio track was returned by tool
    if isinstance(extra_action, dict) and extra_action.get("type") == "audio" and extra_action.get("url"):
        audio_url = extra_action["url"]
        audio_title = extra_action.get("title", "آهنگ")
        audio_performer = extra_action.get("performer", "موزیک")
        caption_formatted = telegram_formatter.markdown_to_telegram_html(extra_action.get("caption", ""))

        # Strategy 1: Resilient chunk streaming to guarantee 100% complete audio (no half-cuts)
        try:
            from src.core.http import get_http_client as _dl_client_s
            audio_buf = io.BytesIO()
            dl_client = _dl_client_s("stream")
            async with dl_client.stream("GET", audio_url) as r_stream:
                if r_stream.status_code == 200:
                    _tot2 = 0
                    async for chunk in r_stream.aiter_bytes(65536):
                        _tot2 += len(chunk)
                        if _tot2 > 25 * 1024 * 1024:
                            break
                        audio_buf.write(chunk)
            
            raw_audio_bytes = audio_buf.getvalue()
            # Verify full track size: genuine songs are at least 1.5MB (1,500,000 bytes)
            if len(raw_audio_bytes) >= 1500000:
                sent_audio = await _reply_audio_bytes(
                    message, chat, context,
                    title=audio_title,
                    performer=audio_performer,
                    caption=extra_action.get("caption", ""),
                    audio_bytes=raw_audio_bytes,
                    archive_label="موزیک ارسالی",
                )
                if sent_audio:
                    return True
            else:
                logger.warning(f"Downloaded audio track too small ({len(raw_audio_bytes)} bytes), likely a preview. Initiating full YouTube fallback...")
        except Exception as e:
            logger.warning(f"Audio streaming error from portal ({e}), initiating full YouTube fallback...")

        # Strategy 2: Guaranteed Full-Track YouTube Extraction if portal URL is incomplete/preview
        try:
            from src.tools.media import youtube_audio as _yt
            from src.tools.media import _tokenize_fa
            yt_q = f"{audio_performer} {audio_title}".strip()
            yt_tokens = _tokenize_fa(yt_q)
            yt_res = await _yt.youtube_download_full_track(yt_q, yt_tokens)
            if yt_res and yt_res.get("audio_bytes"):
                yt_buf = io.BytesIO(yt_res["audio_bytes"])
                yt_buf.name = f"{yt_res['title']}.mp3"
                sent_yt = await message.reply_audio(
                    audio=yt_buf,
                    title=yt_res["title"],
                    performer=yt_res["performer"],
                    caption=caption_formatted,
                    parse_mode=ParseMode.HTML,
                    duration=yt_res.get("duration_sec", 0) or None,
                    write_timeout=180.0,
                    read_timeout=60.0
                )
                sent_media_msg_id = sent_yt.message_id if sent_yt else 0
                if sent_media_msg_id:
                    asyncio.create_task(database.save_message_async(chat.id, context.bot.id, "assistant", f"[موزیک کامل ارسالی: {yt_res['title']} — {yt_res['performer']}]", user_name="Prometheus", chat_title=chat_title, message_id=sent_media_msg_id))
                return True
        except Exception as yt_err:
            logger.error(f"YouTube audio fallback failed: {yt_err}")

        # Strategy 3: Telegram direct stream fallback only as the absolute last resort
        try:
            sent_audio2 = await message.reply_audio(
                audio=audio_url,
                title=audio_title,
                performer=audio_performer,
                caption=caption_formatted,
                parse_mode=ParseMode.HTML,
                write_timeout=180.0,
                read_timeout=60.0
            )
            sent_media_msg_id = sent_audio2.message_id if sent_audio2 else 0
            if sent_media_msg_id:
                asyncio.create_task(database.save_message_async(chat.id, context.bot.id, "assistant", f"[موزیک ارسالی: {audio_title} — {audio_performer}]", user_name="Prometheus", chat_title=chat_title, message_id=sent_media_msg_id))
            return True
        except Exception as e:
            logger.error(f"Error sending audio: {e}")

    # Send final formatted response and backfill its real Telegram message_id.
    # Empty AI text is NEVER silence: fall back to a Persian notice.
    if not ai_response or not str(ai_response).strip():
        ai_response = "⚠️ پاسخ این مرحله خالی برگشت؛ لطفاً پیام خود را شفاف‌تر بفرستید یا یک بار دیگر تلاش کنید."
    sent_final = await reply_safely(message, ai_response)
    if sent_final and getattr(sent_final, "message_id", 0):
        await database.save_message_async(chat.id, context.bot.id, "assistant", ai_response, user_name="Prometheus", chat_title=chat_title, message_id=sent_final.message_id)
        return True
    return False

# ==========================================
# 5. Bot Initialization & App Builder
# ==========================================

async def post_init_callback(application):
    logger.info("Initializing high-performance background daemons on Railway...")
    database.ensure_batch_worker()
    from src.tools.admin import group_manager
    group_manager.set_bot_instance(application.bot)
    try:
        warmed = await database.warm_l1_from_cloud_async()
        logger.info(f"L1 cache warmed with {warmed} keys from Cloudflare KV.")
    except Exception as e:
        logger.warning(f"L1 warmup skipped: {e}")
    async def first_financial_sync():
        try:
            await financial.get_price("BTC", force_refresh=True)
            await financial.get_gold_and_coin_price(force_refresh=True)
            await financial.get_fiat_overview(force_refresh=True)
            logger.info("First financial sync done — prices fresh at startup.")
        except Exception as e:
            logger.warning(f"First financial sync skipped: {e}")
    asyncio.create_task(first_financial_sync())
    asyncio.create_task(financial.background_sync_financial_cache())

    # Self-use background daemon: periodic tool-health snapshot into smart cache
    async def self_health_daemon():
        await asyncio.sleep(30.0)
        while True:
            try:
                from src.tools import internal as _internal
                diag = await _internal.bot_self_diagnose()
                probe = await _internal.bot_tool_health_probe("")
                await _internal.bot_smart_cache_put("health_snapshot", f"{diag}\n{probe}"[:1500])
            except Exception:
                pass
            await asyncio.sleep(300.0)
    asyncio.create_task(self_health_daemon())

    # Keep-Alive warmer: ONLY when a router key exists, and every 120s
    # (not 20s) so Railway free tiers don't burn quota/traffic.
    async def keep_ai_router_warm():
        from src.core import ai_service
        try:
            from src.core.config import has_router as _has_r
            if not bool(_has_r()):
                return
        except Exception:
            return
        while True:
            try:
                client = ai_service.get_shared_client()
                await client.get(f"{config.ROUTER_BASE_URL}/models", timeout=4.0)
            except Exception:
                pass
            await asyncio.sleep(120.0)

    asyncio.create_task(keep_ai_router_warm())

def build_application():
    # Fail-fast with a CLEAR Persian log so Railway users instantly see what's missing.
    try:
        _issues = config.validate_startup_config()
    except Exception:
        _issues = []
    for _iss in (_issues or []):
        logger.warning(f"CONFIG: {_iss}")
    try:
        from src.core.config import has_router, has_tavily, has_cloudflare, has_e2b
        logger.info(
            "API mode: router=%s tavily=%s cloudflare=%s e2b=%s fin_sync=%s",
            "ON" if has_router() else "OFFLINE (free tools only)",
            "ON" if has_tavily() else "OFF (free DDG/Bing)",
            "ON" if has_cloudflare() else "OFF (RAM only)",
            "ON" if has_e2b() else "OFF (local sandbox)",
            getattr(config, "ENABLE_FINANCIAL_SYNC", True),
        )
    except Exception:
        pass
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN خالی است — در Railway Variables ست کنید.")
    database.init_db()

    from telegram.request import HTTPXRequest
    # Railway-safe pool: 512 connections OOMs on 512MB instances. 128 is plenty
    # for polling + music uploads and keeps RAM flat.
    extended_request = HTTPXRequest(
        connection_pool_size=128,
        connect_timeout=25.0,
        read_timeout=60.0,
        write_timeout=120.0,
        pool_timeout=10.0,
        media_write_timeout=180.0
    )

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(extended_request)
        .post_init(post_init_callback)
        .concurrent_updates(True)
        .build()
    )

    # Register global robust error handler to catch all unhandled update exceptions
    app.add_error_handler(global_application_error_handler)

    # Priority 0: Global Banned User Gatekeeper (Zero-tolerance radio silence)
    # Any update from a banned ID or username is intercepted and terminated before any command runs.
    app.add_handler(TypeHandler(Update, global_banned_user_gatekeeper), group=-1)

    # Priority 0: Group Slash-Command Gatekeeper
    # Intercepts foreign commands (e.g. /clean, /settings, /clean@otherbot) in groups,
    # silently archives them to D1, and drops them before reaching any CommandHandler or AI.
    app.add_handler(TypeHandler(Update, group_command_gatekeeper), group=-1)

    # Commands (Filtered so in groups ONLY commands ending in _prometheus or targeting @Prometheusbaibot trigger)
    def _pcmd(cmd_name: str, handler_fn):
        return CommandHandler(cmd_name, handler_fn, filters=PROMETHEUS_CMD_FILTER)

    app.add_handler(_pcmd("start", start_command))
    app.add_handler(_pcmd("help", help_command))
    app.add_handler(_pcmd("tools", tools_command))
    app.add_handler(_pcmd("tools_prometheus", tools_command))
    app.add_handler(_pcmd("admin", admin_command))
    app.add_handler(_pcmd("admin_prometheus", admin_command))
    app.add_handler(_pcmd("panel", admin_command))
    app.add_handler(_pcmd("panel_prometheus", admin_command))
    app.add_handler(_pcmd("clear", clear_command))
    app.add_handler(_pcmd("clear_prometheus", clear_command))
    app.add_handler(_pcmd("music", music_command))
    app.add_handler(_pcmd("music_prometheus", music_command))
    app.add_handler(_pcmd("crypto", crypto_command))
    app.add_handler(_pcmd("crypto_prometheus", crypto_command))
    app.add_handler(_pcmd("gold", gold_command))
    app.add_handler(_pcmd("gold_prometheus", gold_command))
    app.add_handler(_pcmd("weather", weather_command))
    app.add_handler(_pcmd("weather_prometheus", weather_command))
    app.add_handler(_pcmd("search", search_command))
    app.add_handler(_pcmd("search_prometheus", search_command))
    app.add_handler(_pcmd("calc", calc_command))
    app.add_handler(_pcmd("calc_prometheus", calc_command))
    app.add_handler(_pcmd("code", code_command))
    app.add_handler(_pcmd("code_prometheus", code_command))
    app.add_handler(_pcmd("sh", sh_command))
    app.add_handler(_pcmd("sh_prometheus", sh_command))
    app.add_handler(_pcmd("bash", sh_command))
    app.add_handler(_pcmd("e2b", e2b_command))
    app.add_handler(_pcmd("e2b_prometheus", e2b_command))
    app.add_handler(_pcmd("e2bsh", e2bsh_command))
    app.add_handler(_pcmd("e2bsh_prometheus", e2bsh_command))
    app.add_handler(_pcmd("e2bstatus", e2bstatus_command))
    app.add_handler(_pcmd("e2bstatus_prometheus", e2bstatus_command))
    app.add_handler(_pcmd("net", net_command))
    app.add_handler(_pcmd("net_prometheus", net_command))
    app.add_handler(_pcmd("channels", channels_command))
    app.add_handler(_pcmd("channels_prometheus", channels_command))
    app.add_handler(_pcmd("groups", groups_command))
    app.add_handler(_pcmd("groups_prometheus", groups_command))
    app.add_handler(_pcmd("leave", leave_command))
    app.add_handler(_pcmd("leave_prometheus", leave_command))
    app.add_handler(_pcmd("bangroup", bangroup_command))
    app.add_handler(_pcmd("bangroup_prometheus", bangroup_command))
    app.add_handler(_pcmd("remember", remember_command))
    app.add_handler(_pcmd("forget", forget_command))
    app.add_handler(_pcmd("remember_prometheus", remember_command))
    app.add_handler(_pcmd("forget_prometheus", forget_command))
    app.add_handler(_pcmd("ban", ban_command))
    app.add_handler(_pcmd("unban", unban_command))
    app.add_handler(_pcmd("mute", mute_command))
    app.add_handler(_pcmd("unmute", unmute_command))
    app.add_handler(_pcmd("mutelist", mutelist_command))
    app.add_handler(_pcmd("ban_prometheus", ban_command))
    app.add_handler(_pcmd("unban_prometheus", unban_command))
    app.add_handler(_pcmd("id", getid_command))
    app.add_handler(_pcmd("getid", getid_command))
    app.add_handler(_pcmd("id_prometheus", getid_command))
    app.add_handler(_pcmd("del", delete_command))
    app.add_handler(_pcmd("delete", delete_command))
    app.add_handler(_pcmd("del_prometheus", delete_command))
    app.add_handler(_pcmd("delete_prometheus", delete_command))

    # Callbacks, Chat Member Updates & Messages
    app.add_handler(ChatMemberHandler(track_chat_member_updates, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL | filters.VIDEO | filters.VIDEO_NOTE, main_message_handler))

    return app

if __name__ == "__main__":
    logger.info("Starting Prometheus Super Agent Bot...")
    app = build_application()
    # Concurrent update polling with drop_pending_updates=False ensures no update drops while maintaining full parallelism
    app.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)
