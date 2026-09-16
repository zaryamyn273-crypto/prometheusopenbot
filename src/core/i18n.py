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

SUPPORTED = ("fa",)


def normalize_lang(code: object = None) -> str:
    """100% Persian locked."""
    return "fa"


def lang_name(code: object = None) -> str:
    """Always Persian."""
    return "Persian (Farsi)"


def detect_lang(text: object = None) -> str:
    """100% Persian native bot."""
    return "fa"


def t(lang: str, key: str = None, **kw: object) -> str:
    """Fetch a bot-chrome string in 100% Persian Markdown."""
    actual_key = key if key is not None else lang
    pack = STRINGS.get("fa", {})
    text = pack.get(actual_key) or STRINGS.get("en", {}).get(actual_key) or actual_key
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
        "pv_locked": "🔒 *دسترسی اختصاصی:*\nپیوی ربات فقط برای ادمین ارشد فعال است. لطفاً در گروه‌ها از امکانات ربات استفاده فرمایید.",
        "rate_limited": "⚠️ به سقف پیام در دقیقه رسیدی. یه کم صبر کن.",
        "stopped": "🤐 چشم — تا اطلاع بعدی ساکت می‌مونم. (ادامه: «پرومته ادامه»)",
        "resumed": "🎙 برگشتم — در خدمتم.",
        "voice_failed": "🎤 ویست رسید ولی تبدیل به متن نشد. یه کم دیگه دوباره بفرست یا متنش رو بنویس.",
        "group_pending": (
            "⏳ *پرومته اضافه شد ولی هنوز فعال نیست.*\n"
            "منتظر تایید ادمین ارشد هستیم؛ تا اون موقع جوابی نمی‌دم."
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
            "برای حرف زدن باهام: پیامم رو ریپلای کن، منشنم کن، یا اسم «پرومته» رو بیار."
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
    "en": {},
}

# 100% Persian Native Lock: The English pack mirrors the Persian pack identically
# to guarantee zero English leaks across the entire bot chrome.
STRINGS["en"] = STRINGS["fa"]

