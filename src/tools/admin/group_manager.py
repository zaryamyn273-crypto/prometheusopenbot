import logging
import asyncio
from typing import Optional

from src.tools.registry import register_tool
from src.core import database
from src.core.config import ADMIN_ID

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
async def list_joined_groups_tool(caller_id: int = 0, is_private_chat: bool = False) -> str:
    if not caller_id or int(caller_id or 0) <= 0 or int(ADMIN_ID or 0) <= 0 or int(caller_id) != int(ADMIN_ID):
        return "❌ این فرمان منحصراً در اختیار فرمانده ارشد سیستم است."

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
    if not caller_id or int(caller_id or 0) <= 0 or int(ADMIN_ID or 0) <= 0 or int(caller_id) != int(ADMIN_ID):
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
    if not caller_id or int(caller_id or 0) <= 0 or int(ADMIN_ID or 0) <= 0 or int(caller_id) != int(ADMIN_ID):
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
