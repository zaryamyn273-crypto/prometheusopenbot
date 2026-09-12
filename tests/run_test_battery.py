#!/usr/bin/env python3
"""
Comprehensive Test and Monitor Suite for Prometheus:
1. Cloudflare D1 Database (store, retrieve, search, list, delete)
2. Cloudflare KV Store (store, retrieve, TTL handling)
3. Search Conversation History (FTS5 search queries, date-filtered, user-filtered)
4. Admin Governance & Moderation (ban, unban, mute, unmute, muted list, banned list)
5. User Identity Resolution (numeric ID, @username, full name)
6. Admin Memory Management (add directive, list directives, remove directive, sync)
7. Group & Channel Governance (list_joined_groups_tool, list_public_channels_tool)
8. Telegram Bot Handlers (simulated Updates for /start, /tools_prometheus, /clear, /admin, /help, natural language calls, Master-Admin STOP switch)
"""
import asyncio
import os
import sys
import time
import json
import re
import traceback
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core import database, config
from src.core.config import ADMIN_ID
from src.tools.database import (
    cloudflare_d1_store_record,
    cloudflare_d1_retrieve_record,
    cloudflare_d1_search_records,
    cloudflare_d1_list_records,
    cloudflare_d1_delete_record,
    cloudflare_kv_store,
    cloudflare_kv_retrieve,
    search_conversation_history,
    manage_admin_memory,
)
from src.tools.system import (
    ban_user_tool,
    unban_user_tool,
    mute_user_tool,
    unmute_user_tool,
    get_muted_users_list_tool,
    get_banned_users_list_tool,
    extract_user_id_tool,
)
from src.tools.admin.group_manager import (
    list_joined_groups_tool,
    list_public_channels_tool,
    set_bot_instance,
)
import bot
from telegram import Update, User, Chat, Message
from telegram.constants import ChatType, ParseMode
from telegram.ext import ContextTypes, ApplicationHandlerStop

results = []

def record(test_name: str, passed: bool, details: str = "", latency_ms: float = 0.0):
    status_str = "PASS" if passed else "FAIL"
    print(f"[{status_str}] {test_name} ({latency_ms:.1f}ms) - {details[:100]}")
    results.append({
        "test": test_name,
        "passed": passed,
        "details": details,
        "latency_ms": latency_ms
    })

async def test_cloudflare_d1():
    print("\n=== Testing Cloudflare D1 Database CRUD ===")
    test_key = f"test_suite_key_{int(time.time())}"
    test_val = "Special payload with UTF-8: تست دیتابیس کلودفلر ۱۲۳۴"
    category = "test_category"

    # 1. Store record
    t0 = time.time()
    try:
        res_store = await cloudflare_d1_store_record(key=test_key, value=test_val, category=category)
        lat = (time.time() - t0) * 1000
        ok = "با موفقیت" in res_store and test_key in res_store
        record("cloudflare_d1_store_record", ok, res_store, lat)
    except Exception as e:
        record("cloudflare_d1_store_record", False, f"Exception: {e}", (time.time() - t0) * 1000)

    # 2. Retrieve record
    t0 = time.time()
    try:
        res_ret = await cloudflare_d1_retrieve_record(key=test_key)
        lat = (time.time() - t0) * 1000
        ok = test_val in res_ret
        record("cloudflare_d1_retrieve_record", ok, res_ret, lat)
    except Exception as e:
        record("cloudflare_d1_retrieve_record", False, f"Exception: {e}", (time.time() - t0) * 1000)

    # 3. Search records
    t0 = time.time()
    try:
        res_search = await cloudflare_d1_search_records(query=test_key)
        lat = (time.time() - t0) * 1000
        ok = test_key in res_search and "نتایج جستجو" in res_search
        record("cloudflare_d1_search_records", ok, res_search, lat)
    except Exception as e:
        record("cloudflare_d1_search_records", False, f"Exception: {e}", (time.time() - t0) * 1000)

    # 4. List records
    t0 = time.time()
    try:
        res_list = await cloudflare_d1_list_records(category=category, limit=10)
        lat = (time.time() - t0) * 1000
        ok = test_key in res_list and "فهرست رکوردهای" in res_list
        record("cloudflare_d1_list_records", ok, res_list, lat)
    except Exception as e:
        record("cloudflare_d1_list_records", False, f"Exception: {e}", (time.time() - t0) * 1000)

    # 5. Delete record
    t0 = time.time()
    try:
        res_del = await cloudflare_d1_delete_record(key=test_key, caller_id=ADMIN_ID)
        lat = (time.time() - t0) * 1000
        ok = "با موفقیت" in res_del and "حذف گردید" in res_del
        record("cloudflare_d1_delete_record", ok, res_del, lat)
    except Exception as e:
        record("cloudflare_d1_delete_record", False, f"Exception: {e}", (time.time() - t0) * 1000)

    # Verify deletion
    res_after_del = await cloudflare_d1_retrieve_record(key=test_key)
    ok_verify = "یافت نشد" in res_after_del
    record("cloudflare_d1_verify_deletion", ok_verify, res_after_del)

async def test_cloudflare_kv():
    print("\n=== Testing Cloudflare Workers KV ===")
    test_key = f"test_suite_kv_{int(time.time())}"
    test_val = "KV cached value 998877"

    # 1. KV Store
    t0 = time.time()
    try:
        res_store = await cloudflare_kv_store(key=test_key, value=test_val, ttl_seconds=300)
        lat = (time.time() - t0) * 1000
        ok = "با موفقیت" in res_store and test_key in res_store
        record("cloudflare_kv_store", ok, res_store, lat)
    except Exception as e:
        record("cloudflare_kv_store", False, f"Exception: {e}", (time.time() - t0) * 1000)

    # 2. KV Retrieve
    t0 = time.time()
    try:
        res_ret = await cloudflare_kv_retrieve(key=test_key)
        lat = (time.time() - t0) * 1000
        ok = test_val in res_ret and "بازیابی‌شده" in res_ret
        record("cloudflare_kv_retrieve", ok, res_ret, lat)
    except Exception as e:
        record("cloudflare_kv_retrieve", False, f"Exception: {e}", (time.time() - t0) * 1000)

async def test_fts5_and_conversation_search():
    print("\n=== Testing FTS5 Conversation History Search ===")
    test_chat_id = -1007788990011
    test_user_id = 9911223344
    unique_keyword = f"تست_کلمه_منحصر_{int(time.time())}"
    iso, time_str, j_date_str = database.get_tehran_timestamps()

    # Direct insert into D1 messages table to test FTS5 and date search reliably
    insert_sql = """
        INSERT INTO messages (chat_id, user_id, role, content, user_name, username, chat_title, chat_type, msg_kind, msg_date, msg_time, created_at)
        VALUES (?, ?, 'user', ?, 'Ali Test', 'alitest99', 'Test Chat FTS', 'supergroup', 'text', ?, ?, ?)
    """
    await database.execute_d1_query(insert_sql, [test_chat_id, test_user_id, f"پیام تستی برای موتور جستجو {unique_keyword}", j_date_str, time_str, iso])

    # 1. Search conversation history by keyword
    t0 = time.time()
    try:
        res_search = await search_conversation_history(query=unique_keyword, chat_id=test_chat_id)
        lat = (time.time() - t0) * 1000
        ok = unique_keyword in res_search and "سوابق بازیابی‌شده" in res_search
        record("search_conversation_history_keyword", ok, res_search, lat)
    except Exception as e:
        record("search_conversation_history_keyword", False, f"Exception: {e}", (time.time() - t0) * 1000)

    # 2. Date-filtered query
    t0 = time.time()
    try:
        res_date = await search_conversation_history(query=unique_keyword, chat_id=test_chat_id, msg_date=j_date_str)
        lat = (time.time() - t0) * 1000
        ok = unique_keyword in res_date and j_date_str in res_date
        record("search_conversation_history_date_filter", ok, res_date, lat)
    except Exception as e:
        record("search_conversation_history_date_filter", False, f"Exception: {e}", (time.time() - t0) * 1000)

    # 3. User-filtered query
    t0 = time.time()
    try:
        res_user = await search_conversation_history(query=unique_keyword, chat_id=test_chat_id, user=str(test_user_id))
        lat = (time.time() - t0) * 1000
        ok = unique_keyword in res_user
        record("search_conversation_history_user_filter", ok, res_user, lat)
    except Exception as e:
        record("search_conversation_history_user_filter", False, f"Exception: {e}", (time.time() - t0) * 1000)

    # Clean up test message from D1
    await database.execute_d1_query("DELETE FROM messages WHERE chat_id = ?", [test_chat_id])

async def test_identity_extraction():
    print("\n=== Testing User ID Resolution & Extraction ===")
    test_id = 9876543210
    test_uname = "pytest_hero_user"
    test_full_name = "پرهام تست‌کننده ارشد"

    # Setup mappings in database
    await database.execute_d1_query("INSERT OR REPLACE INTO user_mappings (username, user_id) VALUES (?, ?)", [test_uname, test_id])
    iso, t_str, j_str = database.get_tehran_timestamps()
    await database.execute_d1_query(
        "INSERT INTO messages (chat_id, user_id, role, content, user_name, username, chat_title, msg_date, msg_time, created_at) VALUES (?, ?, 'user', 'سلام', ?, ?, 'گروه تست', ?, ?, ?)",
        [-10011223344, test_id, test_full_name, test_uname, j_str, t_str, iso]
    )
    # Also populate in-memory structures
    database._USERNAME_TO_ID_MAP[test_uname] = test_id
    norm_fn = re.sub(r"[\s_\-\.]+", " ", test_full_name).lower()
    database._DISPLAY_NAME_TO_ID_MAP[norm_fn] = {
        "user_id": test_id,
        "display_name": test_full_name,
        "username": test_uname,
        "chat_id": -10011223344,
        "chat_title": "گروه تست",
        "updated_at": iso
    }

    # 1. Numeric ID extraction
    t0 = time.time()
    res_num = await extract_user_id_tool(target=str(test_id), caller_id=ADMIN_ID)
    lat = (time.time() - t0) * 1000
    ok = str(test_id) in res_num and "هویت و شناسه عددی" in res_num
    record("extract_user_id_numeric", ok, res_num, lat)

    # 2. @username extraction
    t0 = time.time()
    res_uname = await extract_user_id_tool(target=f"@{test_uname}", caller_id=ADMIN_ID)
    lat = (time.time() - t0) * 1000
    ok = str(test_id) in res_uname and test_uname in res_uname
    record("extract_user_id_username", ok, res_uname, lat)

    # 3. Full name extraction
    t0 = time.time()
    res_name = await extract_user_id_tool(target=test_full_name, caller_id=ADMIN_ID)
    lat = (time.time() - t0) * 1000
    ok = str(test_id) in res_name
    record("extract_user_id_fullname", ok, res_name, lat)

    # Clean up test records
    await database.execute_d1_query("DELETE FROM user_mappings WHERE username = ?", [test_uname])
    await database.execute_d1_query("DELETE FROM messages WHERE user_id = ?", [test_id])
    database._USERNAME_TO_ID_MAP.pop(test_uname, None)
    database._DISPLAY_NAME_TO_ID_MAP.pop(norm_fn, None)

async def test_admin_memory():
    print("\n=== Testing Admin Memory Directives ===")
    test_directive = f"قانون_تستی_جهت_آزمایش_واحد_{int(time.time())}"

    # 1. Add directive
    t0 = time.time()
    res_add = await manage_admin_memory(action="add", directive=test_directive, caller_id=ADMIN_ID)
    lat = (time.time() - t0) * 1000
    ok = "دستور دائمی با موفقیت" in res_add and test_directive in res_add
    record("manage_admin_memory_add", ok, res_add, lat)

    # 2. List directives
    t0 = time.time()
    res_list = await manage_admin_memory(action="list", caller_id=ADMIN_ID)
    lat = (time.time() - t0) * 1000
    ok = test_directive in res_list and "لیست قوانین" in res_list
    record("manage_admin_memory_list", ok, res_list, lat)

    # 3. Remove directive
    t0 = time.time()
    res_rem = await manage_admin_memory(action="remove", directive=test_directive, caller_id=ADMIN_ID)
    lat = (time.time() - t0) * 1000
    ok = "حذف گردید" in res_rem
    record("manage_admin_memory_remove", ok, res_rem, lat)

    # Verify removal
    res_after = await manage_admin_memory(action="list", caller_id=ADMIN_ID)
    ok_verify = test_directive not in res_after
    record("manage_admin_memory_verify_removed", ok_verify, res_after)

    # 4. Non-admin authorization rejection
    res_unauth = await manage_admin_memory(action="add", directive="fake", caller_id=12345)
    ok_unauth = "فقط ادمین ارشد مجاز" in res_unauth
    record("manage_admin_memory_auth_check", ok_unauth, res_unauth)

async def test_moderation_tools():
    print("\n=== Testing Admin Moderation Tools (Ban / Mute) ===")
    test_uid = 5566778899
    test_uname = "temp_bad_actor_99"

    # 1. Ban user
    t0 = time.time()
    res_ban = await ban_user_tool(target=str(test_uid), username=test_uname, reason="تست مسدودسازی ربات", caller_id=ADMIN_ID)
    lat = (time.time() - t0) * 1000
    ok = "با موفقیت در دیتابیس ابدی Cloudflare D1 مسدود گردید" in res_ban and str(test_uid) in res_ban
    record("ban_user_tool", ok, res_ban, lat)

    # Verify is_user_banned
    is_banned = database.is_user_banned(test_uid, test_uname)
    record("is_user_banned_check", is_banned, f"User {test_uid} banned status: {is_banned}")

    # 2. Get banned users list
    t0 = time.time()
    res_blist = await get_banned_users_list_tool(caller_id=ADMIN_ID)
    lat = (time.time() - t0) * 1000
    ok = str(test_uid) in res_blist and "لیست کاربران مسدودشده" in res_blist
    record("get_banned_users_list_tool", ok, res_blist, lat)

    # 3. Unban user
    t0 = time.time()
    res_unban = await unban_user_tool(target=str(test_uid), caller_id=ADMIN_ID)
    lat = (time.time() - t0) * 1000
    ok = "رفع مسدودیت گردید" in res_unban and str(test_uid) in res_unban
    record("unban_user_tool", ok, res_unban, lat)

    # Verify unbanned
    is_banned_post = database.is_user_banned(test_uid, test_uname)
    record("is_user_banned_post_unban", not is_banned_post, f"User {test_uid} banned status: {is_banned_post}")

    # 4. Mute user
    t0 = time.time()
    res_mute = await mute_user_tool(target=str(test_uid), duration_sec=600, reason="تست سکوت موقت", caller_id=ADMIN_ID)
    lat = (time.time() - t0) * 1000
    ok = "سکوت موقت اعمال شد" in res_mute and str(test_uid) in res_mute
    record("mute_user_tool", ok, res_mute, lat)

    # Verify is_user_muted
    muted_remaining = database.is_user_muted(test_uid, test_uname)
    record("is_user_muted_check", muted_remaining > 0, f"Remaining seconds: {muted_remaining}")

    # 5. Get muted users list
    t0 = time.time()
    res_mlist = await get_muted_users_list_tool(caller_id=ADMIN_ID)
    lat = (time.time() - t0) * 1000
    ok = str(test_uid) in res_mlist and "کاربران در سکوت موقت" in res_mlist
    record("get_muted_users_list_tool", ok, res_mlist, lat)

    # 6. Unmute user
    t0 = time.time()
    res_unmute = await unmute_user_tool(target=str(test_uid), caller_id=ADMIN_ID)
    lat = (time.time() - t0) * 1000
    ok = "لغو شد" in res_unmute and str(test_uid) in res_unmute
    record("unmute_user_tool", ok, res_unmute, lat)

    # Verify unmuted
    muted_remaining_post = database.is_user_muted(test_uid, test_uname)
    record("is_user_muted_post_unmute", muted_remaining_post == 0, f"Remaining: {muted_remaining_post}")

    # 7. Immunity check for ADMIN_ID
    res_admin_ban = await ban_user_tool(target=str(ADMIN_ID), caller_id=ADMIN_ID)
    ok_imm_ban = "مصونیت ابدی" in res_admin_ban
    record("admin_ban_immunity", ok_imm_ban, res_admin_ban)

    res_admin_mute = await mute_user_tool(target=str(ADMIN_ID), caller_id=ADMIN_ID)
    ok_imm_mute = "مصونیت ابدی" in res_admin_mute
    record("admin_mute_immunity", ok_imm_mute, res_admin_mute)

async def test_group_and_channel_tools():
    print("\n=== Testing Group & Channel Tools ===")
    
    # 1. list_joined_groups_tool
    t0 = time.time()
    try:
        # Without live Telegram Bot client
        res_groups = await list_joined_groups_tool(caller_id=ADMIN_ID)
        lat = (time.time() - t0) * 1000
        ok = ("لیست گروه‌هایی که ربات" in res_groups or "در هیچ گروهی عضو نیست" in res_groups or "در هیچ گروه فعالی عضو نیست" in res_groups)
        record("list_joined_groups_tool", ok, res_groups, lat)
    except Exception as e:
        record("list_joined_groups_tool", False, f"Exception: {e}", (time.time() - t0) * 1000)

    # 2. list_public_channels_tool
    t0 = time.time()
    try:
        res_ch = await list_public_channels_tool()
        lat = (time.time() - t0) * 1000
        ok = ("کانال‌های عمومی فعال" in res_ch or "کانال عمومی متصل یا ثبت نشده است" in res_ch)
        record("list_public_channels_tool", ok, res_ch, lat)
    except Exception as e:
        record("list_public_channels_tool", False, f"Exception: {e}", (time.time() - t0) * 1000)

async def test_bot_handlers_and_stop_switch():
    print("\n=== Testing Telegram Bot Handlers & STOP Switch ===")

    def make_mock_update(user_id=ADMIN_ID, first_name="Admin", username="admin_user", chat_id=ADMIN_ID, chat_type=ChatType.PRIVATE, text="/start", reply_to=None):
        update = MagicMock(spec=Update)
        user = MagicMock(spec=User)
        user.id = user_id
        user.first_name = first_name
        user.username = username
        user.mention_html.return_value = f'<a href="tg://user?id={user_id}">{first_name}</a>'
        
        chat = MagicMock(spec=Chat)
        chat.id = chat_id
        chat.type = chat_type
        chat.title = "Test Group" if chat_type != ChatType.PRIVATE else ""
        
        message = MagicMock(spec=Message)
        message.message_id = 101
        message.text = text
        message.caption = None
        message.photo = None
        message.voice = None
        message.audio = None
        message.document = None
        message.video = None
        message.video_note = None
        message.sticker = None
        message.location = None
        message.contact = None
        message.poll = None
        message.forward_origin = None
        message.reply_to_message = reply_to
        message.reply_text = AsyncMock()
        message.chat_id = chat_id
        
        update.effective_user = user
        update.effective_chat = chat
        update.effective_message = message
        return update

    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = []
    context.bot = MagicMock()
    context.bot.send_chat_action = AsyncMock()

    # 1. /start command
    up_start = make_mock_update(text="/start")
    await bot.start_command(up_start, context)
    ok_start = up_start.effective_message.reply_text.called
    msg_start = up_start.effective_message.reply_text.call_args[0][0] if ok_start else "Not called"
    record("bot_handler_start_command", ok_start and "پرومته" in msg_start, msg_start)

    # 2. /help command
    up_help = make_mock_update(text="/help")
    await bot.help_command(up_help, context)
    ok_help = up_help.effective_message.reply_text.called
    msg_help = up_help.effective_message.reply_text.call_args[0][0] if ok_help else "Not called"
    record("bot_handler_help_command", ok_help and "راهنمای دستور" in msg_help, msg_help)

    # 3. /tools_prometheus command
    up_tools = make_mock_update(text="/tools_prometheus")
    await bot.tools_command(up_tools, context)
    ok_tools = up_tools.effective_message.reply_text.called
    msg_tools = up_tools.effective_message.reply_text.call_args[0][0] if ok_tools else "Not called"
    record("bot_handler_tools_command", ok_tools and "جعبه ابزار" in msg_tools, msg_tools)

    # 4. /clear command
    up_clear = make_mock_update(user_id=ADMIN_ID, text="/clear")
    await bot.clear_command(up_clear, context)
    ok_clear = up_clear.effective_message.reply_text.called
    msg_clear = up_clear.effective_message.reply_text.call_args[0][0] if ok_clear else "Not called"
    record("bot_handler_clear_command", ok_clear and "کانتکست گفتگو در این چت ریست شد" in msg_clear, msg_clear)

    # 5. /admin command (Admin in PV)
    up_admin_pv = make_mock_update(user_id=ADMIN_ID, chat_type=ChatType.PRIVATE, text="/admin")
    await bot.admin_command(up_admin_pv, context)
    ok_admin = up_admin_pv.effective_message.reply_text.called
    msg_admin = up_admin_pv.effective_message.reply_text.call_args[0][0] if ok_admin else "Not called"
    record("bot_handler_admin_command_pv", ok_admin and "پنل کنترل و فرماندهی" in msg_admin, msg_admin)

    # 6. /admin command (Admin in Group -> Security Guard)
    up_admin_grp = make_mock_update(user_id=ADMIN_ID, chat_type=ChatType.SUPERGROUP, text="/admin")
    await bot.admin_command(up_admin_grp, context)
    ok_admin_grp = up_admin_grp.effective_message.reply_text.called
    msg_admin_grp = up_admin_grp.effective_message.reply_text.call_args[0][0] if ok_admin_grp else "Not called"
    record("bot_handler_admin_group_guard", ok_admin_grp and "تنها در پیوی" in msg_admin_grp, msg_admin_grp)

    # 7. /admin command (Non-admin -> Rejection)
    up_admin_fake = make_mock_update(user_id=1234567, chat_type=ChatType.PRIVATE, text="/admin")
    await bot.admin_command(up_admin_fake, context)
    ok_fake = up_admin_fake.effective_message.reply_text.called
    msg_fake = up_admin_fake.effective_message.reply_text.call_args[0][0] if ok_fake else "Not called"
    record("bot_handler_admin_unauthorized", ok_fake and "دسترسی غیرمجاز" in msg_fake, msg_fake)

    # 8. Master-Admin STOP switch in Group
    test_group_id = -100987654321
    up_stop = make_mock_update(user_id=ADMIN_ID, chat_id=test_group_id, chat_type=ChatType.SUPERGROUP, text="پرومته ساکت")
    await bot.main_message_handler(up_stop, context)
    is_stopped = test_group_id in bot._STOPPED_CHATS
    msg_stop = up_stop.effective_message.reply_text.call_args[0][0] if up_stop.effective_message.reply_text.called else ""
    record("master_admin_stop_switch_activate", is_stopped and "ساکت می‌مونم" in msg_stop, msg_stop)

    # Verify bot ignores message while stopped
    up_during_stop = make_mock_update(user_id=55555, chat_id=test_group_id, chat_type=ChatType.SUPERGROUP, text="پرومته سلام")
    await bot.main_message_handler(up_during_stop, context)
    ignored_during_stop = not up_during_stop.effective_message.reply_text.called
    record("master_admin_stop_switch_enforced", ignored_during_stop, "Bot remained silent while STOP active")

    # Resume from STOP switch
    up_resume = make_mock_update(user_id=ADMIN_ID, chat_id=test_group_id, chat_type=ChatType.SUPERGROUP, text="پرومته ادامه")
    await bot.main_message_handler(up_resume, context)
    is_resumed = test_group_id not in bot._STOPPED_CHATS
    msg_resume = up_resume.effective_message.reply_text.call_args[0][0] if up_resume.effective_message.reply_text.called else ""
    record("master_admin_stop_switch_resume", is_resumed and "برگشتم" in msg_resume, msg_resume)

    # 9. Natural Language Bot Call Detection (Group)
    # When addressed by name in group, bot triggers response pipeline
    up_call = make_mock_update(user_id=12345, chat_id=test_group_id, chat_type=ChatType.SUPERGROUP, text="پرومته وضعیت سرور چطوره؟")
    with patch("src.core.ai_service.generate_response", new_callable=AsyncMock) as mock_ai:
        mock_ai.return_value = ("عالی هستم، همه سرویس‌ها فعالند!", None)
        await bot.main_message_handler(up_call, context)
        ai_called = mock_ai.called
        record("natural_language_name_call_detected", ai_called, "AI generator invoked upon bot name call in group")

    # 10. Global Gatekeeper for Banned User
    banned_test_user_id = 888777666
    database._BANNED_USERS.add(banned_test_user_id)
    up_banned = make_mock_update(user_id=banned_test_user_id, text="/start")
    gatekeeper_blocked = False
    try:
        await bot.global_banned_user_gatekeeper(up_banned, context)
    except ApplicationHandlerStop:
        gatekeeper_blocked = True
    database._BANNED_USERS.remove(banned_test_user_id)
    record("global_banned_user_gatekeeper_drop", gatekeeper_blocked, "ApplicationHandlerStop raised with radio silence")

    # 13. Group slash-command gatekeeper test: foreign command (/clean, /settings)
    up_foreign = make_mock_update(user_id=1234567, chat_type=ChatType.SUPERGROUP, text="/clean")
    foreign_blocked = False
    try:
        await bot.group_command_gatekeeper(up_foreign, context)
    except ApplicationHandlerStop:
        foreign_blocked = True
    record("group_command_gatekeeper_foreign_dropped", foreign_blocked, "Foreign /clean in supergroup halted and archived")

    # 14. Group slash-command gatekeeper test: prometheus-specific command (/tools_prometheus)
    up_prom_cmd = make_mock_update(user_id=1234567, chat_type=ChatType.SUPERGROUP, text="/tools_prometheus")
    prom_cmd_allowed = True
    try:
        await bot.group_command_gatekeeper(up_prom_cmd, context)
    except ApplicationHandlerStop:
        prom_cmd_allowed = False
    record("group_command_gatekeeper_prometheus_passed", prom_cmd_allowed, "Targeted /tools_prometheus allowed through")

    # 15. Group slash-command gatekeeper test: PV command (/clean)
    up_pv_clean = make_mock_update(user_id=ADMIN_ID, chat_type=ChatType.PRIVATE, text="/clean")
    pv_cmd_allowed = True
    try:
        await bot.group_command_gatekeeper(up_pv_clean, context)
    except ApplicationHandlerStop:
        pv_cmd_allowed = False
    record("group_command_gatekeeper_pv_allowed", pv_cmd_allowed, "Commands in PV allowed freely")

async def test_search_and_media_optimizations():
    print("\n=== Testing Digikala, Web Search & Media Optimizations ===")
    from src.tools.web_network.digikala import digikala_search, clean_digikala_query
    from src.tools.web_network import web_search
    from src.tools.media import clean_music_query
    from src.tools.registry import get_smart_tools_for_prompt

    # 1. Digikala Query Cleaning
    clean_q = clean_digikala_query("قیمت گوشی سامسونگ a55 چنده دیجی کالا")
    record("digikala_query_cleaner", "قیمت" not in clean_q and "چنده" not in clean_q, f"Cleaned: '{clean_q}'")

    # 2. Digikala Search Live
    t0 = time.time()
    dk_res = await digikala_search("گوشی سامسونگ")
    lat_dk = (time.time() - t0) * 1000
    record("digikala_search_live", "دیجی‌کالا" in dk_res and "تومان" in dk_res, f"Latency: {lat_dk:.1f}ms | Snippet: {dk_res[:60]}")

    # 3. Digikala L1 RAM Cache (Sub-millisecond)
    t0_c = time.time()
    dk_cached = await digikala_search("گوشی سامسونگ")
    lat_dk_c = (time.time() - t0_c) * 1000
    record("digikala_l1_ram_cache", lat_dk_c < 20.0 and dk_cached == dk_res, f"Cache latency: {lat_dk_c:.2f}ms")

    # 4. Web Search Speculative Racing
    t0_w = time.time()
    w_res = await web_search("پایتون نسخه جدید")
    lat_w = (time.time() - t0_w) * 1000
    record("web_search_speculative_racing", bool(w_res) and "http" in w_res, f"Latency: {lat_w:.1f}ms")

    # 5. Web Search L1 RAM Cache
    t0_wc = time.time()
    w_cached = await web_search("پایتون نسخه جدید")
    lat_wc = (time.time() - t0_wc) * 1000
    record("web_search_l1_ram_cache", lat_wc < 20.0 and w_cached == w_res, f"Cache latency: {lat_wc:.2f}ms")

    # 6. Music Query Cleaner
    mq = clean_music_query("دانلود آهنگ جدید هایده سوغاتی 320 کامل رو بفرست")
    record("music_query_cleaner", "هایده" in mq and "سوغاتی" in mq and "دانلود" not in mq, f"Cleaned: '{mq}'")

    # 7. Admin Tool Schema Isolation (Non-admin must NOT get execute_python_code or ban_user_tool)
    user_tools = get_smart_tools_for_prompt("اجرای کد پایتون و بن کردن کاربر", is_admin=False)
    has_admin_in_user = any(t.get("function", {}).get("name") in ("execute_python_code", "ban_user_tool") for t in user_tools)
    record("admin_tool_schema_isolation", not has_admin_in_user, "Admin tools strictly excluded for non-admin callers")

    # 8. Admin Caller gets admin tools
    admin_tools = get_smart_tools_for_prompt("اجرای کد پایتون و بن کردن کاربر", is_admin=True)
    has_admin_in_admin = any(t.get("function", {}).get("name") in ("execute_python_code", "ban_user_tool") for t in admin_tools)
    record("admin_caller_tool_access", has_admin_in_admin, "Admin tools included for Master Admin caller")



async def main():
    print("================================================================")
    print("  PROMETHEUS COMPREHENSIVE TEST & MONITORING BATTERY")
    print("================================================================")
    
    t_start = time.time()
    await test_cloudflare_d1()
    await test_cloudflare_kv()
    await test_fts5_and_conversation_search()
    await test_identity_extraction()
    await test_admin_memory()
    await test_moderation_tools()
    await test_group_and_channel_tools()
    await test_bot_handlers_and_stop_switch()
    await test_search_and_media_optimizations()
    t_total = time.time() - t_start

    passed_count = sum(1 for r in results if r["passed"])
    failed_count = sum(1 for r in results if not r["passed"])
    total_count = len(results)

    print("\n================================================================")
    print(f"  TOTAL TESTS: {total_count} | PASSED: {passed_count} | FAILED: {failed_count} | TIME: {t_total:.2f}s")
    print("================================================================")

    # Format report
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("PROMETHEUS AUTOMATED VERIFICATION & MONITORING REPORT")
    report_lines.append(f"Generated at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    report_lines.append(f"Total Execution Time: {t_total:.2f}s")
    report_lines.append(f"Success Rate: {passed_count}/{total_count} ({passed_count/total_count*100:.1f}%)")
    report_lines.append("=" * 80)
    report_lines.append("")

    report_lines.append("--- SUMMARY MATRIX ---")
    for r in results:
        mark = "[PASS]" if r["passed"] else "[FAIL]"
        report_lines.append(f"{mark:<7} {r['test']:<42} | Latency: {r['latency_ms']:>6.1f}ms | {r['details'][:80]}")
    report_lines.append("")

    report_lines.append("--- COMPONENT STATUS BREAKDOWN ---")
    
    # Cloudflare D1
    d1_tests = [r for r in results if "cloudflare_d1" in r["test"]]
    d1_ok = all(r["passed"] for r in d1_tests)
    report_lines.append(f"1. Cloudflare D1 Storage: {'HEALTHY & VERIFIED' if d1_ok else 'ATTENTION REQUIRED'}")
    for r in d1_tests:
        report_lines.append(f"   • {r['test']}: {'PASS' if r['passed'] else 'FAIL'} ({r['latency_ms']:.1f}ms)")
    
    # Cloudflare KV
    kv_tests = [r for r in results if "cloudflare_kv" in r["test"]]
    kv_ok = all(r["passed"] for r in kv_tests)
    report_lines.append(f"2. Cloudflare KV Store: {'HEALTHY & VERIFIED' if kv_ok else 'ATTENTION REQUIRED'}")
    for r in kv_tests:
        report_lines.append(f"   • {r['test']}: {'PASS' if r['passed'] else 'FAIL'} ({r['latency_ms']:.1f}ms)")

    # FTS5 & Conversation Search
    fts_tests = [r for r in results if "search_conversation" in r["test"]]
    fts_ok = all(r["passed"] for r in fts_tests)
    report_lines.append(f"3. Conversation Search & FTS5: {'HEALTHY & VERIFIED' if fts_ok else 'ATTENTION REQUIRED'}")
    for r in fts_tests:
        report_lines.append(f"   • {r['test']}: {'PASS' if r['passed'] else 'FAIL'} ({r['latency_ms']:.1f}ms)")

    # Moderation
    mod_tests = [r for r in results if any(k in r["test"] for k in ["ban", "mute", "unban", "unmute"])]
    mod_ok = all(r["passed"] for r in mod_tests)
    report_lines.append(f"4. Admin Moderation & Blacklist: {'HEALTHY & VERIFIED' if mod_ok else 'ATTENTION REQUIRED'}")
    for r in mod_tests:
        report_lines.append(f"   • {r['test']}: {'PASS' if r['passed'] else 'FAIL'} ({r['latency_ms']:.1f}ms)")

    # Identity Resolution
    id_tests = [r for r in results if "extract_user_id" in r["test"]]
    id_ok = all(r["passed"] for r in id_tests)
    report_lines.append(f"5. Identity Resolution Engine: {'HEALTHY & VERIFIED' if id_ok else 'ATTENTION REQUIRED'}")
    for r in id_tests:
        report_lines.append(f"   • {r['test']}: {'PASS' if r['passed'] else 'FAIL'} ({r['latency_ms']:.1f}ms)")

    # Admin Memory
    mem_tests = [r for r in results if "manage_admin_memory" in r["test"]]
    mem_ok = all(r["passed"] for r in mem_tests)
    report_lines.append(f"6. Admin Memory Directives: {'HEALTHY & VERIFIED' if mem_ok else 'ATTENTION REQUIRED'}")
    for r in mem_tests:
        report_lines.append(f"   • {r['test']}: {'PASS' if r['passed'] else 'FAIL'} ({r['latency_ms']:.1f}ms)")

    # Group & Channel
    grp_tests = [r for r in results if any(k in r["test"] for k in ["list_joined_groups", "list_public_channels"])]
    grp_ok = all(r["passed"] for r in grp_tests)
    report_lines.append(f"7. Group & Channel Tools: {'HEALTHY & VERIFIED' if grp_ok else 'ATTENTION REQUIRED'}")
    for r in grp_tests:
        report_lines.append(f"   • {r['test']}: {'PASS' if r['passed'] else 'FAIL'} ({r['latency_ms']:.1f}ms)")

    # Bot Handlers & STOP switch
    bot_tests = [r for r in results if any(k in r["test"] for k in ["bot_handler", "stop_switch", "natural_language", "gatekeeper"])]
    bot_ok = all(r["passed"] for r in bot_tests)
    report_lines.append(f"8. Telegram Bot Handlers & STOP Switch: {'HEALTHY & VERIFIED' if bot_ok else 'ATTENTION REQUIRED'}")
    for r in bot_tests:
        report_lines.append(f"   • {r['test']}: {'PASS' if r['passed'] else 'FAIL'} ({r['latency_ms']:.1f}ms)")

    report_content = "\n".join(report_lines) + "\n"
    
    with open("/tmp/report_db_admin.txt", "w", encoding="utf-8") as f:
        f.write(report_content)
    print("\nReport successfully written to /tmp/report_db_admin.txt")

if __name__ == "__main__":
    asyncio.run(main())
