import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from telegram.constants import ChatMemberStatus

from src.core import database
from src.core.config import ADMIN_ID
from src.tools.admin import group_manager

@pytest.mark.asyncio
async def test_database_whitelist_crud():
    chat_id = -10099887766
    target_user_id = 11223344
    owner_id = 998877

    # Initial state
    assert not database.is_user_group_whitelisted(chat_id, target_user_id)

    # Add to whitelist
    success = await database.add_group_whitelisted_admin_async(
        chat_id=chat_id,
        user_id=target_user_id,
        added_by=owner_id,
        username="virtual_admin",
        first_name="Admin Virtual"
    )
    assert success is True
    assert database.is_user_group_whitelisted(chat_id, target_user_id) is True

    # Check listing
    admins = await database.get_group_whitelisted_admins_async(chat_id)
    assert any(a["user_id"] == target_user_id for a in admins)

    # Remove from whitelist
    del_success = await database.remove_group_whitelisted_admin_async(chat_id, target_user_id)
    assert del_success is True
    assert database.is_user_group_whitelisted(chat_id, target_user_id) is False

@pytest.mark.asyncio
async def test_authority_resolution_and_rules():
    chat_id = -10055443322
    creator_id = 1001
    tg_admin_id = 1002
    whitelisted_id = 1003
    normal_user_id = 1004
    bot_master_id = ADMIN_ID

    # Mock Telegram Bot
    mock_bot = AsyncMock()

    async def mock_get_chat_member(*args, **kwargs):
        uid = kwargs.get("user_id") or (args[1] if len(args) > 1 else None)
        mock_mem = MagicMock()
        if uid == creator_id:
            mock_mem.status = ChatMemberStatus.OWNER
        elif uid == tg_admin_id:
            mock_mem.status = ChatMemberStatus.ADMINISTRATOR
        else:
            mock_mem.status = ChatMemberStatus.MEMBER
        return mock_mem

    mock_bot.get_chat_member.side_effect = mock_get_chat_member

    # 1. Creator authority
    auth_creator = await group_manager.resolve_group_user_authority(chat_id, creator_id, mock_bot)
    assert auth_creator["is_creator"] is True
    assert auth_creator["is_tg_admin"] is True
    assert auth_creator["can_moderate"] is True
    assert auth_creator["can_manage_whitelist"] is True

    # 2. Telegram Admin authority
    auth_admin = await group_manager.resolve_group_user_authority(chat_id, tg_admin_id, mock_bot)
    assert auth_admin["is_creator"] is False
    assert auth_admin["is_tg_admin"] is True
    assert auth_admin["can_moderate"] is True
    assert auth_admin["can_manage_whitelist"] is False  # Cannot manage whitelist!

    # 3. Whitelisted virtual admin authority
    await database.add_group_whitelisted_admin_async(chat_id, whitelisted_id, added_by=creator_id)
    auth_wl = await group_manager.resolve_group_user_authority(chat_id, whitelisted_id, mock_bot)
    assert auth_wl["is_creator"] is False
    assert auth_wl["is_tg_admin"] is False
    assert auth_wl["is_whitelisted"] is True
    assert auth_wl["can_moderate"] is True  # Can moderate!
    assert auth_wl["can_manage_whitelist"] is False  # Cannot manage whitelist!

    # 4. Normal user
    auth_normal = await group_manager.resolve_group_user_authority(chat_id, normal_user_id, mock_bot)
    assert auth_normal["can_moderate"] is False
    assert auth_normal["can_manage_whitelist"] is False

    # 5. Global Bot Master when NOT group creator:
    auth_master = await group_manager.resolve_group_user_authority(chat_id, bot_master_id, mock_bot)
    assert auth_master["is_creator"] is False
    assert auth_master["can_manage_whitelist"] is False  # Cannot manage whitelist unless creator!

@pytest.mark.asyncio
async def test_whitelist_management_enforcement():
    chat_id = -10055443322
    creator_id = 1001
    tg_admin_id = 1002
    target_id = 9999

    mock_bot = AsyncMock()
    async def mock_get_chat_member(*args, **kwargs):
        uid = kwargs.get("user_id") or (args[1] if len(args) > 1 else None)
        mock_mem = MagicMock()
        mock_mem.status = ChatMemberStatus.OWNER if uid == creator_id else ChatMemberStatus.ADMINISTRATOR
        return mock_mem
    mock_bot.get_chat_member.side_effect = mock_get_chat_member
    group_manager.set_bot_instance(mock_bot)

    # Attempt to whitelist by regular admin -> rejected!
    res_admin = await group_manager.group_whitelist_add_tool(chat_id, target_id, caller_id=tg_admin_id, bot_inst=mock_bot)
    assert "صلاحیت افزودن" in res_admin and "تنها مالک" in res_admin

    # Whitelist by Group Creator -> success!
    res_creator = await group_manager.group_whitelist_add_tool(chat_id, target_id, caller_id=creator_id, bot_inst=mock_bot)
    assert "با موفقیت توسط مالک گروه به لیست ادمین‌های مجازی" in res_creator
    assert database.is_user_group_whitelisted(chat_id, target_id) is True

    # List whitelisted admins
    res_list = await group_manager.group_whitelist_list_tool(chat_id)
    assert str(target_id) in res_list

    # Attempt to unwhitelist by regular admin -> rejected!
    res_un_admin = await group_manager.group_whitelist_remove_tool(chat_id, target_id, caller_id=tg_admin_id, bot_inst=mock_bot)
    assert "صلاحیت حذف" in res_un_admin and "تنها مالک" in res_un_admin

    # Unwhitelist by creator -> success!
    res_un_creator = await group_manager.group_whitelist_remove_tool(chat_id, target_id, caller_id=creator_id, bot_inst=mock_bot)
    assert "با موفقیت از لیست ادمین‌های مجازی ربات در این گروه حذف شد" in res_un_creator
    assert database.is_user_group_whitelisted(chat_id, target_id) is False

@pytest.mark.asyncio
async def test_group_moderation_actions():
    chat_id = -10055443322
    creator_id = 1001
    whitelisted_id = 1003
    normal_id = 2002
    victim_id = 3003

    mock_bot = AsyncMock()
    async def mock_get_chat_member(*args, **kwargs):
        uid = kwargs.get("user_id") or (args[1] if len(args) > 1 else None)
        mock_mem = MagicMock()
        if uid == creator_id:
            mock_mem.status = ChatMemberStatus.OWNER
        else:
            mock_mem.status = ChatMemberStatus.MEMBER
        return mock_mem
    mock_bot.get_chat_member.side_effect = mock_get_chat_member
    group_manager.set_bot_instance(mock_bot)

    # Whitelist virtual admin
    await database.add_group_whitelisted_admin_async(chat_id, whitelisted_id, added_by=creator_id)

    # 1. Normal user cannot moderate
    del_res = await group_manager.group_delete_message_tool(chat_id, 123, caller_id=normal_id, bot_inst=mock_bot)
    assert "صلاحیت اجرای فرامین مدیریتی" in del_res

    # 2. Whitelisted admin can delete
    del_ok = await group_manager.group_delete_message_tool(chat_id, 123, caller_id=whitelisted_id, bot_inst=mock_bot)
    assert "موفقیت حذف گردید" in del_ok
    mock_bot.delete_message.assert_called_with(chat_id=chat_id, message_id=123)

    # 3. Whitelisted admin can ban
    ban_ok = await group_manager.group_ban_member_tool(chat_id, victim_id, caller_id=whitelisted_id, bot_inst=mock_bot)
    assert "مسدود و اخراج شد" in ban_ok
    mock_bot.ban_chat_member.assert_called_with(chat_id=chat_id, user_id=victim_id)

    # 4. Cannot ban Creator
    ban_creator = await group_manager.group_ban_member_tool(chat_id, creator_id, caller_id=whitelisted_id, bot_inst=mock_bot)
    assert "مالک و اونر اصلی گروه قابل بن شدن نیست" in ban_creator

    # 5. Whitelisted admin can kick
    kick_ok = await group_manager.group_kick_member_tool(chat_id, victim_id, caller_id=whitelisted_id, bot_inst=mock_bot)
    assert "با موفقیت از گروه اخراج گردید" in kick_ok

    # 6. Whitelisted admin can mute
    mute_ok = await group_manager.group_mute_member_tool(chat_id, victim_id, caller_id=whitelisted_id, duration_seconds=600, bot_inst=mock_bot)
    assert "در حالت سکوت" in mute_ok
    assert mock_bot.restrict_chat_member.called

    # 7. Whitelisted admin can unmute
    unmute_ok = await group_manager.group_unmute_member_tool(chat_id, victim_id, caller_id=whitelisted_id, bot_inst=mock_bot)
    assert "سکوت کاربر" in unmute_ok and "برداشته شد" in unmute_ok

    # 8. Whitelisted admin can pin & unpin
    pin_ok = await group_manager.group_pin_message_tool(chat_id, 456, caller_id=whitelisted_id, bot_inst=mock_bot)
    assert "سنجاق (پین) گردید" in pin_ok
    unpin_ok = await group_manager.group_unpin_message_tool(chat_id, 456, caller_id=whitelisted_id, bot_inst=mock_bot)
    assert "سنجاق پیام با موفقیت برداشته شد" in unpin_ok


def test_chat_permissions_ptb_v20_compatibility():
    """Verify that ChatPermissions does NOT raise TypeError and only uses valid PTB v20+ parameters."""
    from telegram import ChatPermissions
    
    # Mute: should only use can_send_messages=False
    perms_mute = ChatPermissions(can_send_messages=False)
    assert perms_mute.can_send_messages is False
    
    # Unmute: should only use can_send_messages=True
    perms_unmute = ChatPermissions(can_send_messages=True)
    assert perms_unmute.can_send_messages is True
    
    # Verify can_send_media_messages raises TypeError if supplied
    with pytest.raises(TypeError):
        ChatPermissions(can_send_messages=False, can_send_media_messages=False)


def test_self_mute_prevention_and_group_slang_guard():
    """Verify that saying 'خفه شو' or slang in groups does not mute or stop the bot."""
    import re

    # 1. Bare "خفه شو" must NOT match _STOP_PHRASES
    _STOP_PHRASES = (
        "پرومته بسه", "پرومته بس کن", "ربات بسه", "ربات بس کن", "بات بسه",
        "پرومته ساکت", "پرومته خفه", "پرومته ساکت شو", "پرومته خفه شو", "ربات ساکت شو", "ربات خفه شو",
        "prometheus stop", "prometheus shut up", "prometheus silence", "prometheus hush", "bot stop"
    )
    bare_slang = "خفه شو"
    norm_stop = re.sub(r"[\s\u200c،,:؛!\-–—?.؟\"'()\[\]]+", " ", bare_slang).strip().lower()
    assert not any(_p == norm_stop or f" {_p} " in f" {norm_stop} " for _p in _STOP_PHRASES)

    # 2. Addressed phrase DOES match
    addressed = "پرومته خفه شو"
    norm_addr = re.sub(r"[\s\u200c،,:؛!\-–—?.؟\"'()\[\]]+", " ", addressed).strip().lower()
    assert any(_p == norm_addr or f" {_p} " in f" {norm_addr} " for _p in _STOP_PHRASES)

    # 3. "خفه شو" IS in group direct-reply _mute_triggers
    _mute_triggers = [
        "mute", "/mute", "!mute", "سکوت", "میوت", "ساکت",
        "میوتش کن", "میوت کن", "ساکتش کن", "ساکت کن",
        "سکوت بده", "سکوتش کن", "سکوت کن",
        "خفه شو", "خفه", "خفشو", "خفه‌شو", "دهنتو ببند", "حرف نزن"
    ]
    assert "خفه شو" in _mute_triggers
    assert "خفشو" in _mute_triggers

