"""Minimal i18n layer for Prometheus.

Two-tier design (kept tiny on purpose):
- Bot UI strings: ``fa`` + ``en`` dictionaries. Any other Telegram language
  falls back to ``en`` for bot chrome.
- LLM reply language: full fidelity. :func:`lang_name` maps a Telegram
  ``language_code`` to an English language name that is injected into the
  system prompt, so the model answers in Russian, Spanish, French, ... even
  though bot chrome only ships fa/en. Tool outputs (often Persian) are
  translated by the model per the prompt rule.
"""

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
        "sh_usage": "💻 *ترمینال پرومته (مختص فرمانده):*\nدستور لینوکس رو بنویس:\nمثال: `/sh uptime`",
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
