"""Minimal i18n layer for Prometheus.

Two-tier design (kept tiny on purpose):
- Bot UI strings: ``fa`` + ``en`` dictionaries. Any other Telegram language
  falls back to ``en`` for bot chrome.
- LLM reply language: full fidelity. :func:`lang_name` maps a language code
  to an English language name injected into the system prompt, and
  :func:`detect_lang` reads the *message text itself* (script + keywords), so
  the model answers in whatever language the user actually used — even when
  the Telegram client setting says otherwise. Tool outputs (often Persian)
  are translated by the model per the prompt rule.
"""

import re
from typing import Dict

SUPPORTED = ("fa", "en")

# Telegram language_code prefix -> English language name (for the LLM prompt).
_LANG_NAMES: Dict[str, str] = {
    "fa": "Persian (Farsi)",
    "en": "English",
    "ru": "Russian",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "ar": "Arabic",
    "tr": "Turkish",
    "it": "Italian",
    "pt": "Portuguese",
    "zh": "Chinese",
    "hi": "Hindi",
    "ur": "Urdu",
    "uk": "Ukrainian",
    "nl": "Dutch",
    "pl": "Polish",
    "id": "Indonesian",
    "ms": "Malay",
    "bn": "Bengali",
    "pa": "Punjabi",
    "az": "Azerbaijani",
    "ku": "Kurdish",
    "ps": "Pashto",
    "he": "Hebrew",
    "ja": "Japanese",
    "ko": "Korean",
}


def normalize_lang(code: object) -> str:
    """'fa' for Persian clients, 'en' for everyone else (bot chrome)."""
    try:
        c = str(code or "").strip().lower().replace("_", "-")
    except Exception:
        return "en"
    if c.startswith("fa"):
        return "fa"
    return "en"


def lang_name(code: object) -> str:
    """English name of the user's language (for the LLM system prompt)."""
    try:
        c = str(code or "").strip().lower().replace("_", "-")
    except Exception:
        return "English"
    for prefix, name in _LANG_NAMES.items():
        if c == prefix or c.startswith(prefix + "-"):
            return name
    return "English"


_LATIN_HINTS = (
    ("es", ("hola", "gracias", "por favor", "qué ", "estás", "cómo estás", "buenos")),
    ("fr", ("bonjour", "merci", "s'il", "comment", "quoi", "ça va", "pourquoi")),
    ("de", ("hallo", "danke", "bitte", "wie geht", "warum", "guten")),
    ("it", ("ciao", "grazie", "come stai", "per favore", "buongiorno")),
    ("pt", ("olá", "ola", "obrigado", "obrigada", "como vai", "tudo bem")),
    ("tr", ("merhaba", "teşekkür", "tesekkur", "nasılsın", "nasilsin", "nedir", "nasıl ")),
    ("nl", ("hallo", "dank je", "hoe gaat", "waarom", "goedemorgen")),
    ("pl", ("cześć", "dzień dobry", "dziękuję", "dziękuje", "dlaczego", "jak się")),
    ("id", ("halo", "terima kasih", "apa kabar", "tolong", "selamat")),
    ("ru", ("privet", "spasibo", "pozhaluysta", "kak dela", "pochemu")),
)


def detect_lang(text: object) -> str:
    """Detect the ISO-639 code of a message text (script first, keywords next).

    Returns e.g. 'fa', 'en', 'ru', 'ar', 'es' ... or 'und' when there is no
    detectable linguistic content (empty / numbers / emoji only). Latin text
    without strong hints defaults to 'en'.
    """
    try:
        s = str(text or "")
    except Exception:
        return "und"
    if not s or not s.strip():
        return "und"
    low = s.lower()
    # CJK / Indic / other scripts (checked before Arabic-script: no overlap).
    if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", s):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", s):
        return "ko"
    if re.search(r"[\u0900-\u097f]", s):
        return "hi"
    if re.search(r"[\u0980-\u09ff]", s):
        return "bn"
    # CJK: kana/hangul decided above; remaining Han-only text is Chinese.
    if re.search(r"[⺀-⻳一-鿿]", s):
        return "zh"
    if re.search(r"[\u0590-\u05ff]", s):
        return "he"
    # Cyrillic: Ukrainian-specific letters decide, else Russian.
    if re.search(r"[\u0400-\u04ff]", s):
        if re.search(r"[іїєґ]", low):
            return "uk"
        return "ru"
    # Arabic script: Persian-specific letters (or fa keywords) decide.
    if re.search(r"[\u0600-\u06ff]", s):
        if re.search(r"[گچپژ]", s):
            return "fa"
        if re.search(r"(پرومته|ربات|ممنون|مرسی|چطوری|خوبی|سلام|درود|چیست|کجاست|چرا|چطور|لطفا|باشه|فعلا)", low):
            return "fa"
        return "ar"
    # Turkish-specific diacritics are decisive (ç is shared with French,
    # so it does NOT decide alone — fr/pt keywords handle those).
    if re.search(r"[ğışöü]", low):
        return "tr"
    # Latin keyword hints (need letters at all, else 'und').
    if not re.search(r"[a-z]", low):
        return "und"
    for code, words in _LATIN_HINTS:
        try:
            if any(w in low for w in words):
                return code
        except Exception:
            continue
    return "en"


def t(lang: str, key: str, **kw: object) -> str:
    """Fetch a bot-chrome string. All strings are Telegram *Markdown*."""
    pack = STRINGS.get(lang) or STRINGS["en"]
    text = pack.get(key) or STRINGS["en"].get(key) or key
    if kw:
        try:
            text = text.format(**kw)
        except Exception:
            pass
    return text


STRINGS: Dict[str, Dict[str, str]] = {
    "fa": {
        "welcome": (
            "پرومته — یه ربات تلگرام معمولی که سعی می‌کنه مفید باشه، {name}.\n\n"
            "به‌جای حدس زدن می‌رم سراغ ابزار: قیمت دلار و طلا و رمزارز، هواشناسی، سرچ وب، موزیک، فایل، حساب‌وکتاب. "
            "اگه چیزی خراب باشه یا ندونم، همون رو می‌گم؛ معجزه‌ای در کار نیست.\n\n"
            "*طرز استفاده:*\n"
            "• تو گروه فقط وقتی جواب می‌دم که صدام کنی: ریپلای روی پیامم، منشن، یا اسم «پرومته». بقیه حرف‌ها رو فقط آرشیو می‌کنم.\n"
            "• لیست دستورها: `/help`\n"
            "• پیوی فقط برای ادمین بازه."
        ),
        "help_text": (
            "📖 *راهنمای دستورهای پرومته* (لازم نیست حفظ کنی؛ فارسی حرف بزن، خودم می‌فهمم):\n\n"
            "• `/tools_prometheus` - جعبه ابزارها\n"
            "• `/crypto_prometheus [نماد]` - تابلوی رمزارزها\n"
            "• `/gold_prometheus` - طلا و سکه\n"
            "• `/weather_prometheus [شهر]` - هواشناسی\n"
            "• `/music_prometheus [نام آهنگ]` - دانلود موزیک\n"
            "• `/search_prometheus [عبارت]` - جستجوی وب\n"
            "• `/calc_prometheus [فرمول]` - ماشین‌حساب\n"
            "• `/net_prometheus [دامنه]` - وضعیت سایت و DNS\n"
            "• `/del` یا `/delete` - حذف پیام (با ریپلای)"
        ),
        "pv_locked": "🔒 *دسترسی اختصاصی:*\nپیوی ربات فقط برای ادمین ارشده. لطفاً تو گروه‌ها ازم استفاده کن.",
        "rate_limited": "⚠️ به سقف پیام در دقیقه رسیدی. یه کم صبر کن.",
        "stopped": "🤐 چشم — تا اطلاع بعدی ساکت می‌مونم. (ادامه: «پرومته ادامه»)",
        "resumed": "🎙 برگشتم — در خدمتم.",
        "voice_failed": "🎤 ویست رسید ولی تبدیل به متن نشد. یه کم دیگه دوباره بفرست یا متنش رو بنویس.",
        "group_pending": (
            "⏳ *پرومته اضافه شد ولی هنوز فعال نیست.*\n"
            "منتظر تایید ادمین ارشد هستیم؛ تا اون موقع جوابی نمی‌دم.\n\n"
            "⏳ *Prometheus was added but is not active yet.*\n"
            "Waiting for the super-admin's approval; silent until then."
        ),
        "pv_group_request": (
            "🆕 *درخواست فعال‌سازی گروه جدید*\n\n"
            "• *گروه:* {title}\n"
            "• *شناسه:* `{cid}`\n"
            "• *اضافه‌کننده:* {inviter}\n\n"
            "با دکمه زیر فعال یا رد کن:"
        ),
        "group_approved_ok": "✅ گروه *{title}* (`{cid}`) فعال شد.",
        "group_rejected_ok": "🚫 گروه *{title}* (`{cid}`) رد شد؛ ربات خارج شد.",
        "limit_status": (
            "📊 *سهمیه روزانه تو:* {used} از {limit} استفاده شده؛ {left} باقی مانده.\n"
            "ریست خودکار در {h} ساعت و {m} دقیقه."
        ),
        "limit_admin": "♾ *سهمیه تو نامحدود است* (فرمانده ارشد).",
        "limit_exceeded": (
            "⏳ *سهمیه روزانه تو تمام شد.*\n"
            "سقف {limit} پاسخ در روز؛ از {h} ساعت و {m} دقیقه دیگر دوباره در خدمتم. (ریست خودکار هر 24 ساعت)"
        ),
        "quota_set": "✅ سهمیه {name} (`{uid}`) شد {limit} در روز.",
        "quota_adjusted": "✅ سهمیه {name} (`{uid}`) {delta:+d} شد؛ حالا {limit} در روز.",
        "quota_cleared": "♻️ سهمیه اختصاصی {name} (`{uid}`) حذف شد؛ برگشت به پیش‌فرض ({limit}).",
        "quota_invalid": "❌ عدد نامعتبر است. بین 1 تا 10000 بگو.",
        "quota_need_target": "❌ کاربر مشخص نیست. ریپلای کن، یا آیدی عددی / @یوزرنیم بده.",
        "quota_show": "📊 سهمیه {name} (`{uid}`): {used} از {limit} استفاده شده.",
        "injection_refused": "🛡 این درخواست با قوانین امنیتی ربات ناسازگار است و اجرا نشد. سؤال دیگری داری در خدمتم.",
        "group_hello": (
            "👋 *پرومته فعال شد.*\n"
            "برای حرف زدن باهام: پیامم رو ریپلای کن، منشنم کن، یا اسم «پرومته» رو بیار.\n\n"
            "👋 *Prometheus is on.*\n"
            "Talk to me with a reply, a mention, or the word «Prometheus»."
        ),
        "net_usage": "🌐 *ابزارهای شبکه:*\nدامنه یا IP بده. مثال: `/net_prometheus google.com`",
        "music_usage": "⚠️ اسم آهنگ یا خواننده رو بنویس:\nمثال: `/music_prometheus هایده سوغاتی`",
        "search_usage": "عبارت جستجو رو بنویس.",
        "calc_usage": "فرمول ریاضی رو بنویس.",
        "code_usage": "کد پایتون رو بنویس:\nمثال: `/code print(2**32)`",
        "code_disabled": (
            "⛔ *اجرای کد روی سرور خاموش است.*\n"
            "به دلایل امنیتی، کد فقط داخل سندباکس ابری E2B اجرا می‌شود.\n"
            "برای فعال‌سازی، `E2B_API_KEY` را ست کنید (رایگان: e2b.dev)."
        ),        "sh_usage": "💻 *ترمینال پرومته (مختص فرمانده):*\nدستور لینوکس رو بنویس:\nمثال: `/sh uptime`",
        "e2b_usage": "☁️ *سندباکس ابری E2B:*\nمثال پایتون: `/e2b print(2**32)`\nمثال جاوااسکریپت: `/e2b js console.log(2**32)`\nوضعیت: `/e2bstatus`",
        "e2bsh_usage": "☁️ مثال: `/e2bsh pip list` یا `/e2bsh python --version`",
        "loading": "⏳ یه لحظه...",
        "expired": "این دکمه منقضی شده؛ از منوی جدید استفاده کن.",
        "use_menu_hint": "برای استفاده، دستور یا متن مربوطه رو بفرست.",
        "choose_city": "🌦 شهر رو انتخاب کن:",
        "toolbox_title": "🛠 *جعبه ابزارهای پرومته:*",
        "network_menu": "🌐 *ابزارهای شبکه:*\nدستور: `/net_prometheus google.com`",
        "time_is": "⏰ *ساعت رسمی تهران:* `{hm}`",
        "date_today": "📅 *امروز (خورشیدی):* `{jalali}`\n🌐 *میلادی:* `{iso}`",
        "net_ip_hint": "🔍 *استعلام IP:*\n`get_ip_info` — مثال: `1.1.1.1` یا `google.com` رو بفرست.",
        "net_dns_hint": "📋 *رکوردهای DNS:* اسم دامنه رو بفرست (مثال: `google.com`).",
        "net_ssl_hint": "🔒 *بررسی SSL:* اسم دامنه رو بفرست (مثال: `github.com`).",
        "delivery_failed": "⚠️ ارسال جواب لحظه‌ای به مشکل خورد؛ پیامت رو یه بار دیگه بفرست.",
        "music_failed": "خطا در دریافت فایل موزیک.",
        "del_hint": "⚠️ این دستور رو روی پیامی که می‌خوای حذف بشه ریپلای کن.",
        "immune": "👑 فرمانده ارشد دارای مصونیت ابدی است.",
        "ban_done": "🚫 *فرمان اجرا شد:*\nکاربر *{name}* (`{uid}`) مسدود شد.",
        "unban_done": "✅ *فرمان اجرا شد:*\nکاربر *{name}* (`{uid}`) رفع مسدودیت شد.",
        "mute_done": "🔇 *سکوت اعمال شد:* تا *{dur}* پاسخی دریافت نمی‌کند.",
        "unmute_done": "🔊 *سکوت لغو شد:* ربات دوباره پاسخ می‌دهد.",
        "ai_server_error": "⚠️ خطای سرور هوش مصنوعی ({code}).",
        "ai_timeout": "⚠️ سرور هوش مصنوعی دیر جواب داد.",
        "ai_comm_error": "خطای ارتباطی: {err}",
        "ai_no_response": "⚠️ از سرور هوش مصنوعی جوابی نیومد.",
        "ai_empty": "درخواستی برای اجرا ثبت نشد؛ دقیق‌تر بگو.",
        "ai_offline": (
            "⚠️ *مغز AI فعال نیست:* کلید `ROUTER_API_KEY` ست نشده.\n"
            "فعلاً فقط قیمت/طلا/ارز/ساعت/محاسبات کار می‌کنه.\n"
            "برای فعال‌سازی کامل، متغیر `ROUTER_API_KEY` رو ست کن."
        ),
    },
    "en": {
        "welcome": (
            "Prometheus — a plain Telegram bot trying to be useful, {name}.\n\n"
            "Instead of guessing I use tools: dollar/gold/crypto prices, weather, web search, music, files, math. "
            "If something's broken or I don't know, I'll say so; no miracles here.\n\n"
            "*How to use:*\n"
            "• In groups I only answer when called: reply to my message, mention me, or say «Prometheus». The rest I just archive.\n"
            "• Command list: `/help`\n"
            "• Private chat is admin-only."
        ),
        "help_text": (
            "📖 *Prometheus commands* (no need to memorize; just talk to me):\n\n"
            "• `/tools_prometheus` - toolbox\n"
            "• `/crypto_prometheus [symbol]` - crypto board\n"
            "• `/gold_prometheus` - gold & coins\n"
            "• `/weather_prometheus [city]` - weather\n"
            "• `/music_prometheus [song]` - download music\n"
            "• `/search_prometheus [query]` - web search\n"
            "• `/calc_prometheus [formula]` - calculator\n"
            "• `/net_prometheus [domain]` - site status & DNS\n"
            "• `/del` or `/delete` - delete message (as reply)"
        ),
        "pv_locked": "🔒 *Private chat is exclusive:*\nThe bot's PV is admin-only. Please use me in groups.",
        "rate_limited": "⚠️ You hit the per-minute message cap. Wait a bit.",
        "stopped": "🤐 Got it — silent until further notice. (Resume: «Prometheus continue»)",
        "resumed": "🎙 I'm back — at your service.",
        "voice_failed": "🎤 Got your voice note but transcription failed. Try again in a bit or type it out.",
        "group_pending": (
            "⏳ *پرومته اضافه شد ولی هنوز فعال نیست.*\n"
            "منتظر تایید ادمین ارشد هستیم؛ تا اون موقع جوابی نمی‌دم.\n\n"
            "⏳ *Prometheus was added but is not active yet.*\n"
            "Waiting for the super-admin's approval; silent until then."
        ),
        "pv_group_request": (
            "🆕 *New group activation request*\n\n"
            "• *Group:* {title}\n"
            "• *ID:* `{cid}`\n"
            "• *Added by:* {inviter}\n\n"
            "Approve or reject below:"
        ),
        "group_approved_ok": "✅ Group *{title}* (`{cid}`) activated.",
        "group_rejected_ok": "🚫 Group *{title}* (`{cid}`) rejected; bot left.",
        "limit_status": (
            "📊 *Your daily quota:* {used} of {limit} used; {left} left.\n"
            "Auto-reset in {h}h {m}m."
        ),
        "limit_admin": "♾ *Your quota is unlimited* (master admin).",
        "limit_exceeded": (
            "⏳ *Your daily quota is over.*\n"
            "Cap is {limit} answers/day; back in {h}h {m}m. (auto-reset every 24h)"
        ),
        "quota_set": "✅ Quota of {name} (`{uid}`) set to {limit}/day.",
        "quota_adjusted": "✅ Quota of {name} (`{uid}`) {delta:+d}; now {limit}/day.",
        "quota_cleared": "♻️ Custom quota of {name} (`{uid}`) cleared; back to default ({limit}).",
        "quota_invalid": "❌ Invalid number. Use 1 to 10000.",
        "quota_need_target": "❌ No user specified. Reply, or send a numeric ID / @username.",
        "quota_show": "📊 Quota of {name} (`{uid}`): {used} of {limit} used.",
        "injection_refused": "🛡 This request conflicts with the bot's security rules and was not executed. Anything else I can help with?",
        "group_hello": (
            "👋 *پرومته فعال شد.*\n"
            "برای حرف زدن باهام: پیامم رو ریپلای کن، منشنم کن، یا اسم «پرومته» رو بیار.\n\n"
            "👋 *Prometheus is on.*\n"
            "Talk to me with a reply, a mention, or the word «Prometheus»."
        ),
        "net_usage": "🌐 *Network tools:*\nSend a domain or IP. Example: `/net_prometheus google.com`",
        "music_usage": "⚠️ Send a song or artist name:\nExample: `/music_prometheus Hello Adele`",
        "search_usage": "Send a search query.",
        "calc_usage": "Send a math formula.",
        "code_usage": "Send Python code:\nExample: `/code print(2**32)`",
        "code_disabled": (
            "⛔ *On-server code execution is DISABLED.*\n"
            "For security, code only runs inside the E2B cloud sandbox.\n"
            "To enable, set `E2B_API_KEY` (free: e2b.dev)."
        ),
        "sh_usage": "💻 *Prometheus terminal (commander only):*\nSend a Linux command:\nExample: `/sh uptime`",
        "e2b_usage": "☁️ *E2B cloud sandbox:*\nPython example: `/e2b print(2**32)`\nJavaScript example: `/e2b js console.log(2**32)`\nStatus: `/e2bstatus`",
        "e2bsh_usage": "☁️ Example: `/e2bsh pip list` or `/e2bsh python --version`",
        "loading": "⏳ One moment...",
        "expired": "This button expired; use a fresh menu.",
        "use_menu_hint": "To use it, just send the related command or text.",
        "choose_city": "🌦 Pick a city:",
        "toolbox_title": "🛠 *Prometheus toolbox:*",
        "network_menu": "🌐 *Network tools:*\nCommand: `/net_prometheus google.com`",
        "time_is": "⏰ *Official Tehran time:* `{hm}`",
        "date_today": "📅 *Today (Jalali):* `{jalali}`\n🌐 *Gregorian:* `{iso}`",
        "net_ip_hint": "🔍 *IP lookup:*\n`get_ip_info` — send `1.1.1.1` or `google.com`.",
        "net_dns_hint": "📋 *DNS records:* send a domain name (example: `google.com`).",
        "net_ssl_hint": "🔒 *SSL check:* send a domain name (example: `github.com`).",
        "delivery_failed": "⚠️ Delivering the answer hit a snag; please send your message once more.",
        "music_failed": "Failed to fetch the music file.",
        "del_hint": "⚠️ Reply this command to the message you want deleted.",
        "immune": "👑 The super-admin is immune.",
        "ban_done": "🚫 *Done:*\nUser *{name}* (`{uid}`) banned.",
        "unban_done": "✅ *Done:*\nUser *{name}* (`{uid}`) unbanned.",
        "mute_done": "🔇 *Muted* — no replies for *{dur}*.",
        "unmute_done": "🔊 *Unmuted* — I'll reply again.",
        "ai_server_error": "⚠️ AI server error ({code}).",
        "ai_timeout": "⚠️ The AI server took too long.",
        "ai_comm_error": "Connection error: {err}",
        "ai_no_response": "⚠️ No answer from the AI server.",
        "ai_empty": "Nothing actionable found; please be more specific.",
        "ai_offline": (
            "⚠️ *AI brain is off:* `ROUTER_API_KEY` is not set.\n"
            "Right now only prices/gold/fiat/time/math work.\n"
            "Set `ROUTER_API_KEY` for the full brain."
        ),
    },
}
