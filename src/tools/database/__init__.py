import logging
from typing import Optional

from src.tools.registry import register_tool
from src.core import database
from src.core.config import ADMIN_ID

logger = logging.getLogger(__name__)

# =========================================================================
# Ultra-Fast Cloudflare Multi-Tier Storage (D1 & KV) Autonomous Tools
# =========================================================================

@register_tool(
    name="cloudflare_kv_store",
    description="ذخیره آنی هرگونه یادداشت، متغیر، داده، کد، کانفیگ یا مقدار در کش ابری Cloudflare KV با مدت زمان ماندگاری (TTL)",
    category="database"
)
async def cloudflare_kv_store(
    key: Optional[str] = None,
    name: Optional[str] = None,
    k: Optional[str] = None,
    value: Optional[str] = None,
    val: Optional[str] = None,
    data: Optional[str] = None,
    v: Optional[str] = None,
    ttl_seconds: int = 86400,
    ttl: Optional[int] = None
) -> str:
    """
    :param key: کلید یا شناسه داده برای ذخیره‌سازی (مانند user_note, project_config, api_status)
    :param value: متن کامل داده، کانفیگ، یادداشت یا JSON برای ذخیره
    :param ttl_seconds: مدت زمان ماندگاری به ثانیه (پیش‌فرض: ۸۶۴۰۰ ثانیه معادل ۲۴ ساعت)
    """
    raw_key = key or name or k or ""
    raw_val = value or val or data or v or ""
    final_ttl = ttl or ttl_seconds or 86400

    clean_k = str(raw_key).strip().replace(" ", "_")
    if not clean_k:
        return "کلید ذخیره‌سازی نمی‌تواند خالی باشد."

    ok = await database.kv_set_cache_async(clean_k, str(raw_val), expiration_ttl=max(60, int(final_ttl)))
    if ok:
        return f"✅ داده با کلید `{clean_k}` با موفقیت در پایگاه ابری Cloudflare KV ذخیره شد (مدت اعتبار: {final_ttl} ثانیه)."
    return "خطا در ذخیره‌سازی داده در Cloudflare KV."

@register_tool(
    name="cloudflare_kv_retrieve",
    description="بازیابی فوری و زیرمیلی‌ثانیه‌ای هر مقدار، یادداشت یا داده ذخیره‌شده از کش ابری Cloudflare KV با استفاده از کلید آن",
    category="database"
)
async def cloudflare_kv_retrieve(
    key: Optional[str] = None,
    name: Optional[str] = None,
    k: Optional[str] = None
) -> str:
    """
    :param key: کلید یا شناسه داده‌ای که قبلاً ذخیره شده است
    """
    raw_key = key or name or k or ""
    clean_k = str(raw_key).strip().replace(" ", "_")
    if not clean_k:
        return "لطفاً کلید داده مورد نظر را مشخص فرمایید."

    val = await database.kv_get_cache_async(clean_k)
    if val is not None:
        return f"📦 *داده بازیابی‌شده از Cloudflare KV (`{clean_k}`)*:\n\n{val}"
    return f"هیچ داده‌ای با کلید `{clean_k}` در حافظه کش ابری یافت نشد یا منقضی شده است."

@register_tool(
    name="cloudflare_d1_store_record",
    description="ثبت یا به‌روزرسانی دائمی و ساختاریافته داده‌ها، اطلاعات، یادداشت‌ها یا کانفیگ‌ها در پایگاه داده ابری Cloudflare D1 SQL (بدون انقضا)",
    category="database"
)
async def cloudflare_d1_store_record(
    key: str,
    value: str,
    category: str = "general"
) -> str:
    """
    :param key: عنوان یا کلید یکتا برای داده
    :param value: محتوای متنی، کد، تنظیمات یا JSON برای ذخیره ابدی
    :param category: دسته‌بندی اختیاری (مثال: configs, notes, rules)
    """
    clean_k = key.strip()
    if not clean_k:
        return "کلید داده نمی‌تواند خالی باشد."

    ok = await database.store_custom_record_d1(clean_k, value, category)
    if ok:
        return f"💾 *رکورد با موفقیت به صورت دائمی در دیتابیس ابری Cloudflare D1 ذخیره گردید*:\n• *کلید*: `{clean_k}`\n• *دسته‌بندی*: `{category}`"
    return "خطا در ذخیره‌سازی رکورد در Cloudflare D1."

@register_tool(
    name="cloudflare_d1_retrieve_record",
    description="فراخوانی و بازیابی مستقیم داده‌های ذخیره‌شده دائمی از پایگاه داده ابری Cloudflare D1 بر اساس کلید",
    category="database"
)
async def cloudflare_d1_retrieve_record(key: str) -> str:
    """
    :param key: کلید داده ذخیره‌شده در دیتابیس D1
    """
    clean_k = key.strip()
    val = await database.retrieve_custom_record_d1(clean_k)
    if val is not None:
        return f"📂 *داده بازیابی‌شده از دیتابیس ابری Cloudflare D1 (`{clean_k}`)*:\n\n{val}"
    return f"هیچ رکوردی با کلید `{clean_k}` در پایگاه داده D1 یافت نشد."

@register_tool(
    name="cloudflare_d1_search_records",
    description="جستجوی پیشرفته، متنی و بلادرنگ در تمام داده‌ها، یادداشت‌ها و رکوردهای ثبت‌شده در دیتابیس ابری Cloudflare D1",
    category="database"
)
async def cloudflare_d1_search_records(query: str) -> str:
    """
    :param query: عبارت یا موضوع مورد نظر برای جستجو در کل دیتابیس D1
    """
    clean_q = query.strip()
    records = await database.search_custom_records_d1(clean_q)
    if records:
        lines = [f"🔍 *نتایج جستجو در پایگاه داده Cloudflare D1 برای «{clean_q}»:*\n"]
        for r in records:
            lines.append(f"• *کلید*: `{r.get('key_name')}` [{r.get('category')}]\n  📄 {r.get('data_value')[:250]}\n  🕒 `{r.get('updated_at')}`\n")
        return "\n".join(lines)
    return f"هیچ رکوردی منطبق با «{clean_q}» در پایگاه داده D1 یافت نشد."

@register_tool(
    name="search_conversation_history",
    description="جستجو و بازیابی هوشمند، چندکلمه‌ای و پیشرفته در تاریخچه پیام‌ها و گفتگوهای قبلی همین گروه یا چت در دیتابیس ابری Cloudflare D1",
    category="database"
)
async def search_conversation_history(
    query: Optional[str] = None,
    search_query: Optional[str] = None,
    q: Optional[str] = None,
    user: Optional[str] = None,
    chat_id: int = 0,
    msg_date: Optional[str] = None,
    date: Optional[str] = None,
    msg_kind: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 10,
) -> str:
    """
    :param query: عبارت، کلمات کلیدی یا موضوع مورد نظر برای جستجو در تاریخچه چت
    :param user: فیلتر اختیاری بر اساس آیدی عددی یا نام کاربری فرستنده (مانند @username یا 123456)
    :param msg_date: فیلتر اختیاری تاریخ شمسی پیام (مانند 1403/05/12)
    :param msg_kind: فیلتر اختیاری نوع پیام (text/voice/photo/video/file/sticker/forward)
    :param limit: حداکثر تعداد نتایج (پیش‌فرض 10)
    """
    raw_q = query or search_query or q or ""
    clean_q = str(raw_q).strip()
    if not clean_q:
        return "عبارت جستجو خالی است."
    _date = (msg_date or date or "") or None
    _kind = (msg_kind or kind or "") or None
    try:
        _lim = max(1, min(30, int(limit or 10)))
    except Exception:
        _lim = 10

    results = await database.search_group_memory(chat_id, clean_q, user_identifier=user, limit=_lim, msg_date=_date, msg_kind=_kind)
    if results:
        lines = [f"🔍 *سوابق بازیابی‌شده از پایگاه داده ابری Cloudflare D1 برای «{clean_q}»:*\n"]
        for r in results:
            role = "کاربر" if r.get("role") == "user" else "ربات"
            uname = f" ({r['user_name']})" if r.get("user_name") else ""
            d_str = f" 📅 {r.get('msg_date', '')} 🕐 {r.get('msg_time', '')}" if r.get("msg_date") else (f" [{r.get('created_at')}]" if r.get("created_at") else "")
            k_str = f" [{r.get('msg_kind')}]" if r.get("msg_kind") and r.get("msg_kind") != "text" else ""
            rp = f" ↩️(به {r.get('reply_to_user', '')})" if r.get("reply_to_msg_id") else ""
            lines.append(f"• *{role}{uname}*{k_str}{rp}{d_str}: {r.get('content')[:200]}")
        return "\n".join(lines)
    return f"هیچ پیامی حاوی «{clean_q}» در تاریخچه پایگاه داده گروه یافت نشد."

@register_tool(
    name="manage_admin_memory",
    description="مدیریت حافظه دائمی و ابدی سیستم در دیتابیس D1 (افزودن دستور دائمی، حذف یا مشاهده دستورات - مختص ادمین)",
    category="admin"
)
async def manage_admin_memory(
    action: Optional[str] = None,
    command: Optional[str] = None,
    directive: str = "",
    memory: Optional[str] = None,
    text: Optional[str] = None,
    caller_id: int = 0
) -> str:
    """
    :param action: نوع عملیات ('add', 'remove', 'list', 'sync')
    :param directive: متن قانون یا دستور ابدی
    """
    if caller_id != ADMIN_ID:
        return "❌ فقط ادمین ارشد مجاز به مدیریت حافظه دائمی سیستم است."

    raw_act = action or command or "list"
    raw_dir = directive or memory or text or ""

    act = str(raw_act).lower().strip()
    if act in ["add", "set", "save", "ثبت", "افزودن"]:
        if not raw_dir.strip():
            return "متن دستور دائمی خالی است."
        await database.add_admin_memory_async(raw_dir.strip())
        return f"🧠 *دستور دائمی با موفقیت در دیتابیس ابدی D1 ذخیره و ثبت شد*:\n«{raw_dir.strip()}»"

    elif act in ["remove", "del", "delete", "حذف"]:
        await database.remove_admin_memory_async(raw_dir.strip())
        return f"🗑 دستور دائمی «{raw_dir.strip()}» از پایگاه داده D1 حذف گردید."

    elif act in ["sync", "update", "همگام"]:
        await database.sync_memory_from_d1_async()
        return "🔄 حافظه دائمی مدل با موفقیت از دیتابیس Cloudflare D1 به‌روزرسانی و همگام شد."

    else:
        await database.sync_memory_from_d1_async()
        mems = database.get_all_admin_memories()
        if mems:
            return "🧠 *لیست قوانین و دستورات دائمی فعال در Cloudflare D1*:\n\n" + "\n".join(f"{i+1}. {m}" for i, m in enumerate(mems))
        return "هیچ دستور دائمی در حافظه ثبت نشده است."

@register_tool(
    name="cloudflare_d1_delete_record",
    description="حذف قطعی یک رکورد، یادداشت یا کانفیگ ثبت‌شده از پایگاه داده ابری Cloudflare D1 و کش L1",
    category="database"
)
async def cloudflare_d1_delete_record(key: str, caller_id: int = 0) -> str:
    """
    :param key: عنوان یا کلید داده جهت حذف قطعی از دیتابیس D1
    """
    if caller_id != ADMIN_ID:
        return "❌ فقط ادمین ارشد مجاز به حذف رکوردهای دیتابیس D1 است."
    clean_k = key.strip()
    if not clean_k:
        return "کلید داده نمی‌تواند خالی باشد."
    ok = await database.delete_custom_record_d1(clean_k)
    if ok:
        return f"🗑 *رکورد `{clean_k}` با موفقیت از پایگاه داده ابری Cloudflare D1 و کش RAM حذف گردید.*"
    return f"خطا در حذف رکورد یا رکوردی با کلید `{clean_k}` یافت نشد."

@register_tool(
    name="cloudflare_d1_list_records",
    description="مشاهده فهرست کامل کلیدها و رکوردهای ذخیره شده در پایگاه داده ابری Cloudflare D1",
    category="database"
)
async def cloudflare_d1_list_records(category: Optional[str] = None, limit: int = 20) -> str:
    """
    :param category: دسته‌بندی اختیاری جهت فیلتر رکوردهای ذخیره شده
    :param limit: حداکثر تعداد رکوردهای خروجی
    """
    records = await database.list_custom_records_d1(category=category, limit=limit)
    if not records:
        return "هیچ رکوردی در پایگاه داده ابری Cloudflare D1 یافت نشد."
    lines = [f"📂 *فهرست رکوردهای ذخیره‌شده در Cloudflare D1 ({len(records)} رکورد):*\n"]
    for r in records:
        cat = r.get("category", "general")
        val_prev = str(r.get("data_value", ""))[:80].replace("\n", " ")
        lines.append(f"• `{r.get('key_name')}` [{cat}]: {val_prev}...")
    return "\n".join(lines)
