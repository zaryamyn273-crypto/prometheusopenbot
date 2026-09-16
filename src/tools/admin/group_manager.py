import logging
import asyncio
from typing import Optional, Any

from src.tools.registry import register_tool
from src.core import database
from src.core.config import ADMIN_ID, is_admin_id

logger = logging.getLogger(__name__)

# Global Telegram Bot context reference for direct leave action
_TELEGRAM_BOT_INSTANCE = None

def set_bot_instance(bot):
    global _TELEGRAM_BOT_INSTANCE
    _TELEGRAM_BOT_INSTANCE = bot

def get_bot_instance():
    return _TELEGRAM_BOT_INSTANCE

async def _resolve_live_bot():
    """Return (bot_client, bot_id) for live membership checks, or (None, None)."""
    bot_inst = get_bot_instance()
    if not bot_inst:
        try:
            from telegram import Bot
            from src.core.config import TELEGRAM_BOT_TOKEN
            bot_inst = Bot(token=TELEGRAM_BOT_TOKEN)
        except Exception:
            bot_inst = None
    if not bot_inst:
        return None, None
    try:
        me = await bot_inst.get_me()
        return bot_inst, me.id
    except Exception:
        return bot_inst, None


async def _live_membership(bot_inst, bot_me_id, cid: int):
    """Live check via Telegram: returns (present, definitive).

    present=True  -> bot is verifiably (or assumably, on transient error) in.
    definitive=False means the check itself failed -> keep current status.
    Only definitive LEFT/BANNED/kicked signals flip a group to inactive.
    """
    from telegram.constants import ChatMemberStatus
    if not bot_inst:
        return True, False
    try:
        if bot_me_id:
            member = await bot_inst.get_chat_member(chat_id=cid, user_id=bot_me_id)
            if member.status in [ChatMemberStatus.LEFT, ChatMemberStatus.BANNED]:
                return False, True
            return True, True
        # No bot id (token-only client that can't get_me): probe the chat itself.
        await bot_inst.get_chat(cid)
        return True, True
    except Exception as e:
        err_str = str(e).lower()
        if any(k in err_str for k in ["chat not found", "bot was kicked", "bot is not a member", "forbidden", "chat_admin_required", "kicked"]):
            return False, True
        return True, False

@register_tool(
    name="list_joined_groups_tool",
    description="مشاهده وضعیت زنده، تعداد اعضا، دسترسی و لینک تمام گروه‌هایی که ربات در آنها حضور فعال دارد (مختص فرمانده ارشد)",
    category="admin"
)
async def list_joined_groups_tool(caller_id: int = 0, is_private_chat: bool = False, bot: Any = None, **kwargs) -> str:
    if not caller_id or int(caller_id or 0) <= 0 or not is_admin_id(caller_id):
        return "❌ این فرمان منحصراً در اختیار فرمانده ارشد سیستم است."

    if bot is not None:
        try:
            set_bot_instance(bot)
        except Exception:
            pass

    await database.sync_memory_from_d1_async()
    groups = await database.get_all_tracked_groups_async()
    if not groups:
        return "ربات در حال حاضر در هیچ گروهی عضو نیست."

    bot_inst, bot_me_id = await _resolve_live_bot()

    # Parallel Live Group Inspection Worker
    async def _inspect_group(g: dict) -> Optional[dict]:
        cid = g.get("chat_id")
        if not cid:
            return None
        try:
            cid = int(cid)
        except Exception:
            return None
        if "channel" in str(g.get("chat_type", "")).lower():
            return None
        if database.is_user_banned(cid):
            return None
        status = str(g.get("status") or "active").lower()

        present, definitive = await _live_membership(bot_inst, bot_me_id, cid)
        if not present and definitive:
            try:
                await database.set_group_status_async(cid, "left")
            except Exception:
                pass
            return None

        if status == "pending":
            return {
                "kind": "pending",
                "chat_id": cid,
                "title": g.get("title") or "گروه",
                "added_by": g.get("added_by") or 0
            }
        if status == "left":
            return None

        actual_title = g.get("title") or "گروه"
        member_cnt = g.get("member_count") or 0
        bot_role = "عضو عادی"
        link = ""

        if bot_inst:
            try:
                chat_obj = await bot_inst.get_chat(cid)
                if chat_obj:
                    actual_title = chat_obj.title or actual_title
                    if getattr(chat_obj, "username", None):
                        link = f"https://t.me/{chat_obj.username}"
                # Fetch live member count
                try:
                    live_cnt = await bot_inst.get_chat_member_count(cid)
                    if live_cnt:
                        member_cnt = live_cnt
                except Exception:
                    pass
                # Check bot's role
                if bot_me_id:
                    try:
                        m_obj = await bot_inst.get_chat_member(chat_id=cid, user_id=bot_me_id)
                        from telegram.constants import ChatMemberStatus
                        if m_obj.status == ChatMemberStatus.ADMINISTRATOR:
                            bot_role = "🛡️ ادمین با دسترسی کامل"
                        elif m_obj.status == ChatMemberStatus.OWNER:
                            bot_role = "👑 مالک / سازنده"
                        else:
                            bot_role = "👤 عضو عادی"
                    except Exception:
                        pass
                # Resolve link if not public
                if not link:
                    link = g.get("invite_link") or ""
                if not link and bot_role.startswith("🛡️"):
                    try:
                        inv = await bot_inst.export_chat_invite_link(chat_id=cid)
                        if inv:
                            link = str(inv).strip()
                            try:
                                await database.track_group_presence_async(cid, actual_title, chat_type=g.get("chat_type", "supergroup"), invite_link=link)
                            except Exception:
                                pass
                    except Exception:
                        pass
            except Exception:
                pass

        return {
            "kind": "active",
            "chat_id": cid,
            "title": actual_title,
            "member_count": member_cnt,
            "bot_role": bot_role,
            "link": link
        }

    # Concurrently inspect all groups in parallel for sub-second execution
    tasks = [_inspect_group(g) for g in groups]
    inspections = await asyncio.gather(*tasks, return_exceptions=True)

    active_items = []
    pending_items = []

    for item in inspections:
        if isinstance(item, dict):
            if item.get("kind") == "active":
                active_items.append(item)
            elif item.get("kind") == "pending":
                pending_items.append(item)

    lines = []
    if active_items:
        lines.append("👥 *لیست گروه‌های زنده و فعال پرومته (Live Telemetry):*\n")
        for idx, act in enumerate(active_items, 1):
            cid = act["chat_id"]
            title = act["title"]
            cnt_str = f"`{act['member_count']} نفر`" if act.get("member_count") else "`نامشخص`"
            link_str = act["link"] if act.get("link") else "در دسترس نیست (لینک عمومی ندارد / ربات ادمین نیست)"
            lines.append(
                f"{idx}. 🌟 *{title}*\n"
                f"   • شناسه عددی: `<code>{cid}</code>`\n"
                f"   • اعضای فعال: {cnt_str}\n"
                f"   • سطح دسترسی پرومته: `{act['bot_role']}`\n"
                f"   • پیوند ورود: {link_str}\n"
            )

    if pending_items:
        lines.append("\n⏳ *گروه‌های در انتظار تایید ادمین ارشد:*\n")
        for p in pending_items:
            inv = f" — اضافه کننده: `<code>{p['added_by']}</code>`" if p.get("added_by") else ""
            lines.append(f"• ⏳ *{p['title']}* (`<code>{p['chat_id']}</code>`){inv}")

    if not lines:
        return "ربات در حال حاضر در هیچ گروه فعالی عضو نیست."

    return "\n".join(lines)

@register_tool(
    name="list_public_channels_tool",
    description="مشاهده و نمایش لیست کانال‌های رسمی و عمومی که ربات در آنها عضو و متصل است (قابل نمایش در تمام گروه‌ها)",
    category="media"
)
async def list_public_channels_tool() -> str:
    await database.sync_memory_from_d1_async()
    groups = await database.get_all_tracked_groups_async()
    channels = [g for g in groups if "channel" in str(g.get("chat_type", "")).lower()]
    if not channels:
        return "📢 ربات در حال حاضر در کانال عمومی متصل یا ثبت نشده است."
    lines = ["📢 *کانال‌های عمومی فعال و متصل به پرومته:*\n"]
    for idx, ch in enumerate(channels, 1):
        title = ch.get("title") or "کانال رسمی"
        cid = ch.get("chat_id")
        lines.append(f"{idx}. 📣 *{title}* (`{cid}`)")
    return "\n".join(lines)

@register_tool(
    name="ban_group_by_name_or_id_tool",
    description="بن کردن و خروج ابدی ربات از یک گروه فقط با گفتن نام گروه یا آیدی عددی چت، همراه با مسدودسازی دائمی دسترسی آن گروه در دیتابیس (مختص فرمانده ارشد)",
    category="admin"
)
async def ban_group_by_name_or_id_tool(
    group_name: Optional[str] = None,
    target: Optional[str] = None,
    chat_identifier: Optional[str] = None,
    chat_id: Optional[str] = None,
    reason: str = "مسدودسازی دائمی گروه به دستور فرمانده",
    caller_id: int = 0
) -> str:
    if not caller_id or int(caller_id or 0) <= 0 or not is_admin_id(caller_id):
        return "❌ این فرمان منحصراً در اختیار فرمانده ارشد سیستم است."
    raw_query = str(group_name or target or chat_identifier or chat_id or "").strip()
    if not raw_query:
        return "لطفاً نام یا شناسه عددی گروه مورد نظر برای بن را مشخص فرمایید."
    await database.sync_memory_from_d1_async()
    groups = await database.get_all_tracked_groups_async()
    target_chat_id = None
    target_title = ""
    if raw_query.lstrip("-").isdigit():
        target_chat_id = int(raw_query)
        for g in groups:
            if g.get("chat_id") == target_chat_id:
                target_title = g.get("title") or ""
                break
    else:
        clean_q = raw_query.lower()
        _matches = []
        for g in groups:
            g_title = str(g.get("title", "")).lower()
            if not g_title:
                continue
            if clean_q in g_title or g_title in clean_q:
                _matches.append(g)
        if len(_matches) > 1:
            _names = ", ".join(f"{m.get('title') or 'group'} (`{m.get('chat_id')}`)" for m in _matches[:10])
            return f"چند گروه با `{raw_query}` مطابقت دارد. لطفا شناسه دقیق را بدهید:\n{_names}"
        if _matches:
            target_chat_id = _matches[0].get("chat_id")
            target_title = _matches[0].get("title") or ""
    if not target_chat_id:
        return f"❌ گروهی با نام یا مشخصه «{raw_query}» در لیست گروه‌های فعال ربات یافت نشد."
    await database.ban_target_async(
        target_chat_id,
        reason=f"گروه بن شد: {reason}",
        first_name=target_title,
        banned_by=caller_id,
        source_chat_id=target_chat_id,
        source_chat_title=target_title
    )
    bot_inst = get_bot_instance()
    if bot_inst:
        try:
            await bot_inst.send_message(
                chat_id=target_chat_id,
                text="🚫 <b>این گروه به دستور مستقیم فرمانده ارشد مسدود گردید. ربات خارج می‌شود.</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass
        try:
            await bot_inst.leave_chat(target_chat_id)
        except Exception as e:
            logger.warning(f"Failed to leave chat {target_chat_id}: {e}")
    await database.remove_group_presence_async(target_chat_id)
    name_label = f"«{target_title}» " if target_title else ""
    return f"🚫 *فرمان مسدودسازی گروه با موفقیت اجرا شد:*\nگروه {name_label}با شناسه `{target_chat_id}` در دیتابیس Cloudflare D1 مسدود گردید و ربات فوراً از آن خارج شد."

@register_tool(
    name="leave_group_by_admin_tool",
    description="خروج و ترک فوری ربات از یک گروه خاص بر اساس نام گروه یا آیدی عددی چت (مختص فرمانده ارشد)",
    category="admin"
)
async def leave_group_by_admin_tool(
    chat_identifier: Optional[str] = None,
    group: Optional[str] = None,
    chat_id: Optional[str] = None,
    caller_id: int = 0
) -> str:
    """
    :param chat_identifier: شناسه عددی چت (مانند -10012345678) یا بخشی از نام گروه
    """
    if not caller_id or int(caller_id or 0) <= 0 or not is_admin_id(caller_id):
        return "❌ این فرمان منحصراً در اختیار فرمانده ارشد سیستم است."

    target_raw = str(chat_identifier or group or chat_id or "").strip()
    if not target_raw:
        return "لطفاً شناسه عددی یا نام گروه مورد نظر برای خروج را مشخص فرمایید."

    target_chat_id = None
    target_title = ""

    # Check if target is a direct chat_id
    await database.sync_memory_from_d1_async()
    groups = await database.get_all_tracked_groups_async()
    if target_raw.lstrip("-").isdigit():
        target_chat_id = int(target_raw)
        if target_chat_id > 0:
            return f"ID `{target_raw}` شناسه گروه نیست. شناسه گروه عدد منفی است (مثل -100123456789). لیست: /groups_prometheus"
        for g in groups:
            if g.get("chat_id") == target_chat_id:
                target_title = g.get("title") or ""
                break
    else:
        # Search by title: never guess — refuse on zero or multiple matches.
        _q = target_raw.lower()
        matches = [g for g in groups if _q and _q in str(g.get("title") or "").lower()]
        if not matches:
            return f"گروهی با مشخصه `{target_raw}` پیدا نشد."
        if len(matches) > 1:
            _names = ", ".join(f"{m.get('title') or 'group'} (`{m.get('chat_id')}`)" for m in matches[:10])
            return f"چند گروه با `{target_raw}` مطابقت دارد. لطفا شناسه دقیق را بدهید:\n{_names}"
        target_chat_id = matches[0].get("chat_id")
        target_title = matches[0].get("title") or ""

    if not target_chat_id:
        return f"گروهی با مشخصه `{target_raw}` پیدا نشد."

    # Live-verify the target and resolve its real title (this chat ONLY).
    bot_inst = get_bot_instance()
    live_title = ""
    if bot_inst:
        try:
            _chat = await bot_inst.get_chat(target_chat_id)
            live_title = (getattr(_chat, "title", "") or "").strip()
        except Exception:
            live_title = ""
    if live_title:
        target_title = live_title
    name_str = f"`{target_title}` " if target_title else ""

    if not bot_inst:
        return f"اتصال زنده به تلگرام در دسترس نیست؛ خروج از گروه {name_str}(`{target_chat_id}`) انجام نشد."

    # Perform Telegram API leave chat (THIS chat only — never anything else).
    try:
        await bot_inst.leave_chat(target_chat_id)
    except Exception as e:
        logger.warning(f"leave_chat failed for {target_chat_id}: {e}")

    # Honest verification: confirm we are really out before claiming success.
    try:
        _me = await bot_inst.get_me()
        _mem = await bot_inst.get_chat_member(chat_id=target_chat_id, user_id=_me.id)
        _st = str(getattr(_mem, "status", "")).lower()
    except Exception:
        _st = "left"
    if _st not in ("left", "kicked"):
        return f"خروج از گروه {name_str}(`{target_chat_id}`) ناموفق بود؛ ربات هنوز عضو است. هیچ تغییری در دیتابیس اعمال نشد."

    # Mark inactive in D1/RAM (record + messages are KEPT).
    await database.remove_group_presence_async(target_chat_id)

    return f"خروج انجام شد: ربات از گروه {name_str}(`{target_chat_id}`) خارج شد. رکورد گروه به صورت غیرفعال نگه داشته شد."


# =========================================================================
# Group Authority & Moderation Actions (Delete, Ban, Kick, Mute, Pin)
# Only Group Owner (Creator) can whitelist/unwhitelist.
# Owner, Telegram Admins, and Whitelisted Virtual Admins can moderate.
# =========================================================================

async def resolve_group_user_authority(chat_id: int, user_id: int, bot_inst=None) -> dict:
    """
    Resolves the exact permissions of user_id in chat_id.
    Returns:
      is_creator: True only if user is Telegram Owner/Creator of the chat
      is_tg_admin: True if user is Telegram Creator or Administrator
      is_whitelisted: True if user is in the group's virtual admin whitelist
      can_moderate: True if user is Creator, Telegram Admin, or Whitelisted
      can_manage_whitelist: True ONLY for the Creator/Owner (Even global ADMIN_ID cannot if not creator!)
    """
    cid = int(chat_id)
    uid = int(user_id)
    if not bot_inst:
        bot_inst = get_bot_instance()
    if not bot_inst:
        bot_inst, _ = await _resolve_live_bot()

    is_creator = False
    is_tg_admin = False
    if bot_inst:
        try:
            from telegram.constants import ChatMemberStatus
            try:
                mem = await bot_inst.get_chat_member(chat_id=cid, user_id=uid)
            except TypeError:
                mem = await bot_inst.get_chat_member(cid, uid)
            status = getattr(mem, "status", None)
            owner_val = getattr(ChatMemberStatus, "OWNER", getattr(ChatMemberStatus, "CREATOR", "owner"))
            admin_val = getattr(ChatMemberStatus, "ADMINISTRATOR", "administrator")
            st_str = str(status).lower() if status is not None else ""
            if status == owner_val or "creator" in st_str or "owner" in st_str:
                is_creator = True
                is_tg_admin = True
            elif status == admin_val or "admin" in st_str:
                is_tg_admin = True
        except Exception as e:
            logger.debug(f"get_chat_member check failed for {uid} in {cid}: {e}")

    is_whitelisted = database.is_user_group_whitelisted(cid, uid)
    can_moderate = is_creator or is_tg_admin or is_whitelisted

    # CRUCIAL RULE: Only the Owner/Creator of this specific group can manage the whitelist!
    # Even the global bot admin (ADMIN_ID) CANNOT whitelist admins unless they are the Owner/Creator of this group.
    can_manage_whitelist = is_creator

    return {
        "is_creator": is_creator,
        "is_tg_admin": is_tg_admin,
        "is_whitelisted": is_whitelisted,
        "can_moderate": can_moderate,
        "can_manage_whitelist": can_manage_whitelist
    }


@register_tool(
    name="group_whitelist_add_tool",
    description="افزودن کاربر به لیست ادمین‌های مجازی ربات در گروه (صلاحیت اجرای فرامین به ربات؛ منحصراً در اختیار مالک و اونر اصلی گروه)",
    category="admin"
)
async def group_whitelist_add_tool(
    chat_id: int,
    target_user_id: int,
    caller_id: int,
    target_username: str = "",
    target_first_name: str = "",
    bot_inst=None
) -> str:
    """Adds a user to the group's virtual admin whitelist. ONLY Group Owner can execute."""
    auth = await resolve_group_user_authority(chat_id, caller_id, bot_inst=bot_inst)
    if not auth["can_manage_whitelist"]:
        return "❌ تنها مالک و سازنده اصلی این گروه (Group Owner/Creator) صلاحیت افزودن ادمین‌های مجازی به وایت‌لیست ربات را دارد. حتی ادمین کل ربات در صورتی که مالک این گروه نباشد، این دسترسی را ندارد."

    success = await database.add_group_whitelisted_admin_async(
        chat_id=chat_id,
        user_id=target_user_id,
        added_by=caller_id,
        username=target_username,
        first_name=target_first_name
    )
    name_label = target_first_name or (f"@{target_username}" if target_username else f"کاربر {target_user_id}")
    if success:
        return f"✅ {name_label} (`{target_user_id}`) با موفقیت توسط مالک گروه به لیست ادمین‌های مجازی ربات اضافه شد و اکنون می‌تواند فرامین مدیریتی (حذف، بن، میوت، پین) را صادر کند."
    return f"❌ خطا در افزودن {name_label} به وایت‌لیست ادمین‌های مجازی."


@register_tool(
    name="group_whitelist_remove_tool",
    description="حذف کاربر از لیست ادمین‌های مجازی ربات در گروه (منحصراً در اختیار مالک و اونر اصلی گروه)",
    category="admin"
)
async def group_whitelist_remove_tool(
    chat_id: int,
    target_user_id: int,
    caller_id: int,
    bot_inst=None
) -> str:
    """Removes a user from the group's virtual admin whitelist. ONLY Group Owner can execute."""
    auth = await resolve_group_user_authority(chat_id, caller_id, bot_inst=bot_inst)
    if not auth["can_manage_whitelist"]:
        return "❌ تنها مالک و سازنده اصلی این گروه (Group Owner/Creator) صلاحیت حذف ادمین‌های مجازی از وایت‌لیست ربات را دارد."

    success = await database.remove_group_whitelisted_admin_async(chat_id=chat_id, user_id=target_user_id)
    if success:
        return f"✅ کاربر `{target_user_id}` با موفقیت از لیست ادمین‌های مجازی ربات در این گروه حذف شد."
    return f"❌ خطا در حذف کاربر `{target_user_id}` از وایت‌لیست."


@register_tool(
    name="group_whitelist_list_tool",
    description="مشاهده لیست تمام ادمین‌های مجازی وایت‌لیست‌شده ربات در گروه",
    category="admin"
)
async def group_whitelist_list_tool(chat_id: int, caller_id: int = 0) -> str:
    """Lists all whitelisted virtual admins for this group."""
    admins = await database.get_group_whitelisted_admins_async(chat_id)
    if not admins:
        return "📋 هیچ ادمین مجازی برای این گروه در وایت‌لیست ربات ثبت نشده است."

    lines = ["📋 *لیست ادمین‌های مجازی مجاز ربات در این گروه:*\n"]
    for idx, a in enumerate(admins, 1):
        uname = f" (@{a['username']})" if a.get("username") else ""
        fname = a.get("first_name") or "ادمین مجازی"
        uid = a.get("user_id")
        lines.append(f"{idx}. 👤 *{fname}*{uname} — شناسه: `<code>{uid}</code>`")
    return "\n".join(lines)


@register_tool(
    name="group_delete_message_tool",
    description="حذف یک پیام در گروه (مختص اونر، ادمین‌های تلگرام، و ادمین‌های مجازی وایت‌لیست‌شده)",
    category="admin"
)
async def group_delete_message_tool(chat_id: int, message_id: int, caller_id: int, bot_inst=None) -> str:
    auth = await resolve_group_user_authority(chat_id, caller_id, bot_inst=bot_inst)
    if not auth["can_moderate"]:
        return "❌ شما صلاحیت اجرای فرامین مدیریتی در این گروه را ندارید (نیاز به دسترسی اونر، ادمین گروه، یا ادمین مجازی وایت‌لیست‌شده)."

    if not bot_inst:
        bot_inst = get_bot_instance()
    if not bot_inst:
        bot_inst, _ = await _resolve_live_bot()
    if not bot_inst:
        return "❌ اتصال ربات به تلگرام برقرار نیست."

    try:
        await bot_inst.delete_message(chat_id=chat_id, message_id=message_id)
        return "✅ پیام با موفقیت حذف گردید."
    except Exception as e:
        return f"❌ خطا در حذف پیام: {e} (اطمینان حاصل کنید ربات دسترسی ادمین 'حذف پیام' را دارد)"


@register_tool(
    name="group_ban_member_tool",
    description="مسدودسازی و بن دائمی کاربر از گروه (مختص اونر، ادمین‌های تلگرام، و ادمین‌های مجازی وایت‌لیست‌شده)",
    category="admin"
)
async def group_ban_member_tool(chat_id: int, target_user_id: int, caller_id: int, reason: str = "", bot_inst=None) -> str:
    auth = await resolve_group_user_authority(chat_id, caller_id, bot_inst=bot_inst)
    if not auth["can_moderate"]:
        return "❌ شما صلاحیت اجرای فرامین مدیریتی در این گروه را ندارید."

    # Prevent banning supreme commander or group creator
    if is_admin_id(target_user_id):
        return "⛔ فرمانده ارشد ربات مصونیت مطلق دارد و قابل بن شدن نیست."

    target_auth = await resolve_group_user_authority(chat_id, target_user_id, bot_inst=bot_inst)
    if target_auth["is_creator"]:
        return "⛔ مالک و اونر اصلی گروه قابل بن شدن نیست."

    if not bot_inst:
        bot_inst = get_bot_instance()
    if not bot_inst:
        bot_inst, _ = await _resolve_live_bot()
    if not bot_inst:
        return "❌ اتصال ربات به تلگرام برقرار نیست."

    try:
        await bot_inst.ban_chat_member(chat_id=chat_id, user_id=target_user_id)
        return f"🚫 کاربر `{target_user_id}` با موفقیت از گروه مسدود و اخراج شد."
    except Exception as e:
        return f"❌ خطا در بن کردن کاربر: {e} (اطمینان حاصل کنید ربات دسترسی ادمین 'مسدودسازی کاربران' را دارد)"


@register_tool(
    name="group_kick_member_tool",
    description="اخراج موقت کاربر از گروه بدون بن دائمی (مختص اونر، ادمین‌های تلگرام، و ادمین‌های مجازی وایت‌لیست‌شده)",
    category="admin"
)
async def group_kick_member_tool(chat_id: int, target_user_id: int, caller_id: int, bot_inst=None) -> str:
    auth = await resolve_group_user_authority(chat_id, caller_id, bot_inst=bot_inst)
    if not auth["can_moderate"]:
        return "❌ شما صلاحیت اجرای فرامین مدیریتی در این گروه را ندارید."

    if is_admin_id(target_user_id) or (await resolve_group_user_authority(chat_id, target_user_id, bot_inst=bot_inst))["is_creator"]:
        return "⛔ این کاربر دارای مصونیت است و قابل اخراج نیست."

    if not bot_inst:
        bot_inst = get_bot_instance()
    if not bot_inst:
        bot_inst, _ = await _resolve_live_bot()
    if not bot_inst:
        return "❌ اتصال ربات به تلگرام برقرار نیست."

    try:
        await bot_inst.ban_chat_member(chat_id=chat_id, user_id=target_user_id)
        await bot_inst.unban_chat_member(chat_id=chat_id, user_id=target_user_id)
        return f"👢 کاربر `{target_user_id}` با موفقیت از گروه اخراج گردید."
    except Exception as e:
        return f"❌ خطا در اخراج کاربر: {e}"


@register_tool(
    name="group_mute_member_tool",
    description="سکوت موقت کاربر در گروه (مختص اونر، ادمین‌های تلگرام، و ادمین‌های مجازی وایت‌لیست‌شده)",
    category="admin"
)
async def group_mute_member_tool(chat_id: int, target_user_id: int, caller_id: int, duration_seconds: int = 3600, bot_inst=None) -> str:
    auth = await resolve_group_user_authority(chat_id, caller_id, bot_inst=bot_inst)
    if not auth["can_moderate"]:
        return "❌ شما صلاحیت اجرای فرامین مدیریتی در این گروه را ندارید."

    if is_admin_id(target_user_id) or (await resolve_group_user_authority(chat_id, target_user_id, bot_inst=bot_inst))["is_creator"]:
        return "⛔ این کاربر دارای مصونیت است و قابل میوت شدن نیست."

    if not bot_inst:
        bot_inst = get_bot_instance()
    if not bot_inst:
        bot_inst, _ = await _resolve_live_bot()
    if not bot_inst:
        return "❌ اتصال ربات به تلگرام برقرار نیست."

    try:
        import time as _t
        from telegram import ChatPermissions
        until_ts = int(_t.time()) + max(60, min(86400 * 365, int(duration_seconds or 3600)))
        permissions = ChatPermissions(
            can_send_messages=False
        )
        await bot_inst.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user_id,
            permissions=permissions,
            until_date=until_ts
        )
        mins = int(duration_seconds // 60)
        return f"🔇 کاربر `{target_user_id}` به مدت {mins} دقیقه در گروه در حالت سکوت (Mute) قرار گرفت."
    except Exception as e:
        return f"❌ خطا در اعمال سکوت: {e}"


@register_tool(
    name="group_unmute_member_tool",
    description="رفع سکوت (آنمیوت) کاربر در گروه (مختص اونر، ادمین‌های تلگرام، و ادمین‌های مجازی وایت‌لیست‌شده)",
    category="admin"
)
async def group_unmute_member_tool(chat_id: int, target_user_id: int, caller_id: int, bot_inst=None) -> str:
    auth = await resolve_group_user_authority(chat_id, caller_id, bot_inst=bot_inst)
    if not auth["can_moderate"]:
        return "❌ شما صلاحیت اجرای فرامین مدیریتی در این گروه را ندارید."

    if not bot_inst:
        bot_inst = get_bot_instance()
    if not bot_inst:
        bot_inst, _ = await _resolve_live_bot()
    if not bot_inst:
        return "❌ اتصال ربات به تلگرام برقرار نیست."

    try:
        from telegram import ChatPermissions
        permissions = ChatPermissions(
            can_send_messages=True
        )
        await bot_inst.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_user_id,
            permissions=permissions
        )
        return f"🔊 سکوت کاربر `{target_user_id}` با موفقیت برداشته شد."
    except Exception as e:
        return f"❌ خطا در رفع سکوت: {e}"


@register_tool(
    name="group_pin_message_tool",
    description="سنجاق (پین) کردن پیام در گروه (مختص اونر، ادمین‌های تلگرام، و ادمین‌های مجازی وایت‌لیست‌شده)",
    category="admin"
)
async def group_pin_message_tool(chat_id: int, message_id: int, caller_id: int, notify: bool = False, bot_inst=None) -> str:
    auth = await resolve_group_user_authority(chat_id, caller_id, bot_inst=bot_inst)
    if not auth["can_moderate"]:
        return "❌ شما صلاحیت اجرای فرامین مدیریتی در این گروه را ندارید."

    if not bot_inst:
        bot_inst = get_bot_instance()
    if not bot_inst:
        bot_inst, _ = await _resolve_live_bot()
    if not bot_inst:
        return "❌ اتصال ربات به تلگرام برقرار نیست."

    try:
        await bot_inst.pin_chat_message(chat_id=chat_id, message_id=message_id, disable_notification=not notify)
        return "📌 پیام با موفقیت در گروه سنجاق (پین) گردید."
    except Exception as e:
        return f"❌ خطا در پین کردن پیام: {e}"


@register_tool(
    name="group_unpin_message_tool",
    description="برداشتن سنجاق (آنپین) پیام در گروه (مختص اونر، ادمین‌های تلگرام، و ادمین‌های مجازی وایت‌لیست‌شده)",
    category="admin"
)
async def group_unpin_message_tool(chat_id: int, message_id: int, caller_id: int, bot_inst=None) -> str:
    auth = await resolve_group_user_authority(chat_id, caller_id, bot_inst=bot_inst)
    if not auth["can_moderate"]:
        return "❌ شما صلاحیت اجرای فرامین مدیریتی در این گروه را ندارید."

    if not bot_inst:
        bot_inst = get_bot_instance()
    if not bot_inst:
        bot_inst, _ = await _resolve_live_bot()
    if not bot_inst:
        return "❌ اتصال ربات به تلگرام برقرار نیست."

    try:
        await bot_inst.unpin_chat_message(chat_id=chat_id, message_id=message_id)
        return "📌 سنجاق پیام با موفقیت برداشته شد."
    except Exception as e:
        return f"❌ خطا در آنپین کردن پیام: {e}"


