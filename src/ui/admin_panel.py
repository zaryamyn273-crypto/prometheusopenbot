from typing import Optional, List, Dict, Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from src.core import database
from src.tools import system
from src.tools.admin import group_manager

def get_start_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🛠 جعبه ابزارهای تخصصی", callback_data="open_toolbox_main"),
            InlineKeyboardButton("👑 پنل فرماندهی", callback_data="admin_dashboard")
        ],
        [
            InlineKeyboardButton("🌤 هواشناسی زنده", callback_data="tool_weather_menu"),
            InlineKeyboardButton("📰 اخبار فوری", callback_data="tool_news")
        ],
        [
            InlineKeyboardButton("💰 تابلوی قیمت‌ها و ارز", callback_data="tool_gold"),
            InlineKeyboardButton("🎵 موتور موسیقی ۳۲۰", callback_data="tool_music_menu")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    """
    Ultra-Advanced Executive Management Matrix for Master Admin
    """
    keyboard = [
        [
            InlineKeyboardButton("📊 داشبورد زنده و سلامت سرور", callback_data="admin_dashboard"),
            InlineKeyboardButton("⚡ استعلام سلامت D1 & RAM", callback_data="admin_db_health")
        ],
        [
            InlineKeyboardButton("🧠 فرامین ابدی و قوانین D1", callback_data="admin_memory"),
            InlineKeyboardButton("🚫 مدیریت لیست سیاه کاربران", callback_data="admin_banned_list")
        ],
        [
            InlineKeyboardButton("👥 گروه‌ها و سوپرگروه‌های متصل", callback_data="admin_groups_list"),
            InlineKeyboardButton("📢 کانال‌های عمومی متصل", callback_data="admin_channels_list")
        ],
        [
            InlineKeyboardButton("💾 دیتابیس D1 (آخرین پیام‌ها)", callback_data="admin_d1_recent"),
            InlineKeyboardButton("🧹 پاکسازی کانتکست چت جاری", callback_data="admin_clear_context")
        ],
        [
            InlineKeyboardButton("🛠 جعبه ابزارهای تخصصی سیستم", callback_data="open_toolbox_main"),
            InlineKeyboardButton("🔄 بروزرسانی سریع کش و دیتابیس", callback_data="admin_refresh_sync")
        ],
        [
            InlineKeyboardButton("❌ بستن پنل فرماندهی", callback_data="admin_close")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_groups_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🔄 بازبینی زنده اعضا و وضعیت", callback_data="admin_groups_refresh"),
            InlineKeyboardButton("🔙 بازگشت به پنل اصلی", callback_data="admin_dashboard")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_banned_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🔄 بروزرسانی لیست سیاه", callback_data="admin_banned_list"),
            InlineKeyboardButton("🔙 بازگشت به پنل اصلی", callback_data="admin_dashboard")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_memory_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🔄 همگام‌سازی حافظه از D1", callback_data="admin_memory_sync"),
            InlineKeyboardButton("🔙 بازگشت به پنل اصلی", callback_data="admin_dashboard")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_tools_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("💰 تابلوی کریپتو و نوبیتکس", callback_data="tool_crypto"),
            InlineKeyboardButton("🥇 نرخ طلا، سکه و ارز آزاد", callback_data="tool_gold")
        ],
        [
            InlineKeyboardButton("📰 اخبار زنده ایران و جهان", callback_data="tool_news"),
            InlineKeyboardButton("🌦 هواشناسی چندلایه‌ای", callback_data="tool_weather_menu")
        ],
        [
            InlineKeyboardButton("🌐 بازرسی شبکه، IP و SSL", callback_data="tool_network_menu"),
            InlineKeyboardButton("🧮 ماشین‌حساب پیشرفته و مهندسی", callback_data="tool_calc_menu")
        ],
        [
            InlineKeyboardButton("🔐 تولید انواع هش و امنیت", callback_data="tool_hash_menu"),
            InlineKeyboardButton("📏 تبدیل واحدهای مهندسی", callback_data="tool_units_menu")
        ],
        [
            InlineKeyboardButton("📝 مقاله‌ساز فوری تلگراف", callback_data="tool_telegraph"),
            InlineKeyboardButton("🔳 تولید بارکد هوشمند QR", callback_data="tool_qr")
        ],
        [
            InlineKeyboardButton("🎵 دانلود آهنگ 320 و لیریکس", callback_data="tool_music_menu"),
            InlineKeyboardButton("⏰ تقویم و اوقات رسمی تهران", callback_data="tool_time")
        ],
        [
            InlineKeyboardButton("🔙 بازگشت به پنل فرماندهی", callback_data="admin_dashboard")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_weather_quick_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("تهران", callback_data="qweather_Tehran"),
            InlineKeyboardButton("مشهد", callback_data="qweather_Mashhad"),
            InlineKeyboardButton("اصفهان", callback_data="qweather_Isfahan")
        ],
        [
            InlineKeyboardButton("تبریز", callback_data="qweather_Tabriz"),
            InlineKeyboardButton("شیراز", callback_data="qweather_Shiraz"),
            InlineKeyboardButton("دبی", callback_data="qweather_Dubai")
        ],
        [
            InlineKeyboardButton("🔙 بازگشت به جعبه ابزار", callback_data="open_toolbox_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_network_tools_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🔍 استعلام آی‌پی و WHOIS", callback_data="tool_net_ip_prompt"),
            InlineKeyboardButton("📋 رکوردهای DNS دامنه", callback_data="tool_net_dns_prompt")
        ],
        [
            InlineKeyboardButton("🔒 بررسی گواهی امنیتی SSL", callback_data="tool_net_ssl_prompt")
        ],
        [
            InlineKeyboardButton("🔙 بازگشت به جعبه ابزار", callback_data="open_toolbox_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def get_system_status_text_async() -> str:
    base = system.admin_system_diagnostics()
    try:
        health = await database.get_cache_health_async()
    except Exception:
        health = {}

    kv_state = "🟢 فعال و بدون تاخیر" if not health.get("kv_circuit_open") else "🟠 محدودیت نوشتن ابری (فعالیت کامل در RAM L1)"
    d1_state = "🟢 آنلاین و متصل" if health.get("d1_reachable") else "🔴 نامتصل"
    worker_state = "🟢 در حال اجرا (Queue Drainer)" if health.get("d1_batch_worker_alive") else "🟡 آماده‌باش"

    db_tail = (
        "\n\n🗄 <b>وضعیت زیرساخت ابری و پایگاه داده (D1 SQL & RAM Cache):</b>\n"
        f"• <b>مخزن حافظه رم (L1 Hot Cache):</b> <code>{health.get('l1_keys', 0)}</code> کلید فعال\n"
        f"• <b>اتصال دیتابیس ابری Cloudflare D1:</b> {d1_state}\n"
        f"• <b>موتور پردازش صف ذخیره‌سازی پیام‌ها:</b> {worker_state} (عمق صف: <code>{health.get('d1_queue_depth', 0)}</code>)\n"
        f"• <b>وضعیت لایه ذخیره موقت (KV Store):</b> {kv_state}\n"
    )
    return base + db_tail

async def get_memory_text_async() -> str:
    mems = database.get_all_admin_memories()
    if not mems:
        return (
            "🧠 <b>حافظه دائمی و قوانین ابدی سیستم (Cloudflare D1):</b>\n\n"
            "<i>هیچ قانون دائمی ثبت نشده است.</i>\n\n"
            "💡 برای ثبت دستور جدید:\n"
            "<code>/remember متن دستور حاکمیتی</code>"
        )
    lines = [f"<b>{i+1}.</b> <code>{m}</code>" for i, m in enumerate(mems)]
    return (
        f"🧠 <b>قوانین و فرامین ابدی فعال در حافظه دیتابیس D1 ({len(mems)} دستور):</b>\n\n"
        + "\n".join(lines)
        + "\n\n💡 برای حذف دستور: <code>/forget متن دستور</code>"
    )

async def get_banned_users_text_async() -> str:
    records = await database.get_banned_users_detailed_async()
    if not records:
        return "🚫 <b>لیست سیاه کاربران:</b>\n\nهیچ کاربری در لیست مسدودشدگان قرار ندارد."
    
    out = [f"🚫 <b>لیست کاربران مسدودشده در Cloudflare D1 ({len(records)} کاربر):</b>\n"]
    for i, r in enumerate(records[:20], 1):
        uid = r.get("user_id") or "نامشخص"
        uname = f"@{r.get('username')}" if r.get("username") else "بدون یوزرنیم"
        fname = r.get("first_name") or "—"
        reason = r.get("reason") or "تخلف از قوانین"
        out.append(f"<b>{i}.</b> <code>{uid}</code> | <b>{fname}</b> ({uname})\n   علت: <i>{reason}</i>")
    
    if len(records) > 20:
        out.append(f"\n... و {len(records) - 20} کاربر دیگر")
    
    out.append("\n💡 <i>برای آزادسازی:</i> <code>/unban &lt;شناسه یا @username&gt;</code>")
    return "\n".join(out)

async def get_connected_groups_text_async(bot=None) -> str:
    from src.core.config import ADMIN_ID
    res = await group_manager.list_joined_groups_tool(caller_id=ADMIN_ID, bot=bot)
    return res

async def get_recent_d1_messages_text_async() -> str:
    res = await database.execute_d1_query(
        "SELECT id, chat_title, user_name, username, role, content, msg_time FROM messages ORDER BY id DESC LIMIT 10"
    )
    if not res.get("success") or not res.get("results"):
        return "🗄 <b>آخرین پیام‌های ثبت‌شده در دیتابیس D1:</b>\n\nهیچ رکوردی یافت نشد."
    
    lines = ["🗄 <b>۱۰ پیام اخیر ثبت‌شده در دیتابیس Cloudflare D1:</b>\n"]
    for r in res["results"]:
        grp = r.get("chat_title") or "چت خصوصی"
        user = r.get("user_name") or r.get("username") or "کاربر"
        role = "🤖 پرومته" if r.get("role") == "assistant" else f"👤 {user}"
        preview = str(r.get("content", ""))[:45].replace("\n", " ")
        t = r.get("msg_time") or ""
        lines.append(f"• [{t}] <b>{grp}</b> | {role}: <code>{preview}...</code>")
    
    return "\n".join(lines)
