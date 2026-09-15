import os
import pytest
import time
from unittest.mock import MagicMock

from src.core import config
from src.core.config import _parse_admin_id, _parse_admin_ids, get_admin_ids, is_admin_id, SYSTEM_PROMPT
import bot


def test_parse_admin_ids():
    # Single and multi-format parsing
    assert _parse_admin_ids("123, 456; 789\n101112") == {123, 456, 789, 101112}
    assert _parse_admin_ids([123, "456", 0, -5, "bad"]) == {123, 456}
    assert _parse_admin_ids((999, 888)) == {999, 888}
    assert _parse_admin_ids("") == set()
    assert _parse_admin_ids(None) == set()
    # Bool protection
    assert _parse_admin_ids(True) == set()
    assert _parse_admin_ids(False) == set()
    assert _parse_admin_id(True) == 0
    assert _parse_admin_id(False) == 0


def test_is_admin_id_and_dynamic_reload():
    # Setup test env
    old_id = os.environ.get("ADMIN_ID")
    old_ids = os.environ.get("ADMIN_IDS")
    try:
        os.environ["ADMIN_ID"] = "11111"
        os.environ["ADMIN_IDS"] = "22222, 33333"

        # Reload
        admins = get_admin_ids()
        assert 11111 in admins
        assert 22222 in admins
        assert 33333 in admins

        assert is_admin_id(11111) is True
        assert is_admin_id("11111") is True
        assert is_admin_id(22222) is True
        assert is_admin_id("33333") is True
        assert is_admin_id(44444) is False
        assert is_admin_id(0) is False
        assert is_admin_id(-1) is False
        assert is_admin_id(None) is False
        assert is_admin_id("invalid") is False
        # Bool privilege escalation protection
        assert is_admin_id(True) is False
        assert is_admin_id(False) is False

        # Dynamic update without restart
        os.environ["ADMIN_IDS"] = "22222, 44444"
        assert is_admin_id(44444) is True

    finally:
        if old_id is not None:
            os.environ["ADMIN_ID"] = old_id
        else:
            os.environ.pop("ADMIN_ID", None)
        if old_ids is not None:
            os.environ["ADMIN_IDS"] = old_ids
        else:
            os.environ.pop("ADMIN_IDS", None)
        get_admin_ids()


def test_bot_is_admin():
    # Test bot.is_admin delegate and bool safety
    assert bot.is_admin(True) is False
    assert bot.is_admin(False) is False
    assert bot.is_admin(0) is False
    assert bot.is_admin(None) is False
    assert bot.is_admin("bad") is False

    admin_ids = get_admin_ids()
    if admin_ids:
        sample_id = next(iter(admin_ids))
        assert bot.is_admin(sample_id) is True
        assert bot.is_admin(str(sample_id)) is True


@pytest.mark.asyncio
async def test_fast_paths_whoami():
    # Mock admin user
    admin_user = MagicMock()
    admin_user.id = config.ADMIN_ID or 99999
    admin_user.first_name = "Commander"
    admin_user.last_name = "Owner"
    admin_user.username = "commander_boss"
    admin_user.full_name = "Commander Owner"

    # Ensure admin_user.id is in admin set for testing
    old_id = os.environ.get("ADMIN_ID")
    os.environ["ADMIN_ID"] = str(admin_user.id)
    get_admin_ids()

    mock_chat = MagicMock()
    mock_msg = MagicMock()

    whoami_queries = [
        "من کی هستم", "من کیم", "من چه کسیم", "مشخصات من", "اطلاعات من",
        "شناسه من", "آیدی من", "ایدی من", "یوزر آیدی من",
        "whoami", "who am i", "my id", "my profile"
    ]

    for q in whoami_queries:
        res = await bot._triage_fast_turn(
            mock_msg, mock_chat, admin_user, q, "Commander", "fa", None, False
        )
        assert res is not None, f"Failed for query: {q}"
        text, extra = res
        assert extra is None
        assert str(admin_user.id) in text
        assert "فرمانده ارشد" in text or "Master Admin" in text
        assert "@commander_boss" in text

    # Standard User
    norm_user = MagicMock()
    norm_user.id = 88888888
    norm_user.first_name = "Normal"
    norm_user.last_name = "User"
    norm_user.username = "normal_user"
    norm_user.full_name = "Normal User"

    res_norm = await bot._triage_fast_turn(
        mock_msg, mock_chat, norm_user, "من کیم", "Normal", "fa", None, False
    )
    assert res_norm is not None
    text_norm, _ = res_norm
    assert "88888888" in text_norm
    assert "کاربر عمومی" in text_norm or "کاربر" in text_norm
    assert "@normal_user" in text_norm

    if old_id:
        os.environ["ADMIN_ID"] = old_id
        get_admin_ids()


@pytest.mark.asyncio
async def test_fast_paths_admin_inquiry():
    mock_user = MagicMock()
    mock_user.id = 12345
    mock_chat = MagicMock()
    mock_msg = MagicMock()

    queries = [
        "ادمین کیه", "ادمین کیست", "فرمانده کیه", "فرمانده کیست",
        "مالک کیه", "سازنده کیه", "خالق کیه", "رئیس کیه",
        "who is admin", "who is owner"
    ]

    for q in queries:
        res = await bot._triage_fast_turn(
            mock_msg, mock_chat, mock_user, q, "User", "fa", None, False
        )
        assert res is not None, f"Failed inquiry for {q}"
        text, _ = res
        assert "فرمانده" in text or "Master Admin" in text or "Admin" in text
        assert str(config.ADMIN_ID) in text


@pytest.mark.asyncio
async def test_fast_paths_bot_identity():
    mock_user = MagicMock()
    mock_user.id = 12345
    mock_chat = MagicMock()
    mock_msg = MagicMock()

    queries = ["تو کی هستی", "تو کیستی", "معرفی کن", "who are you"]

    for q in queries:
        res = await bot._triage_fast_turn(
            mock_msg, mock_chat, mock_user, q, "User", "fa", None, False
        )
        assert res is not None, f"Failed bot identity for {q}"
        text, _ = res
        assert "پرومته" in text or "Prometheus" in text


@pytest.mark.asyncio
async def test_fast_paths_ping():
    mock_user = MagicMock()
    mock_user.id = 12345
    mock_chat = MagicMock()
    mock_msg = MagicMock()

    queries = ["پینگ", "ping", "ربات بیداری", "پرومته بیداری", "بیداری", "تست سرعت"]

    for q in queries:
        res = await bot._triage_fast_turn(
            mock_msg, mock_chat, mock_user, q, "User", "fa", None, False
        )
        assert res is not None, f"Failed ping for {q}"
        text, _ = res
        assert "پونگ" in text or "Pong" in text or "بیدار" in text


@pytest.mark.asyncio
async def test_fast_paths_admin_diagnostics():
    admin_user = MagicMock()
    admin_user.id = config.ADMIN_ID or 7777777

    old_id = os.environ.get("ADMIN_ID")
    os.environ["ADMIN_ID"] = str(admin_user.id)
    get_admin_ids()

    mock_chat = MagicMock()
    mock_msg = MagicMock()

    diag_queries = ["وضعیت سرور", "تله متری", "تلهمتری", "استاتوس سرور", "server status"]

    for q in diag_queries:
        res = await bot._triage_fast_turn(
            mock_msg, mock_chat, admin_user, q, "Commander", "fa", None, False
        )
        assert res is not None, f"Failed admin diagnostics for {q}"
        text, _ = res
        # Diagnostics returns CPU / RAM / disk info
        assert "CPU" in text or "پردازنده" in text or "RAM" in text or "تله‌متری" in text or "سیستم" in text

    # Verify non-admin is NOT answered by admin diagnostics fast path
    non_admin = MagicMock()
    non_admin.id = 555555
    res_non_adm = await bot._triage_fast_turn(
        mock_msg, mock_chat, non_admin, "وضعیت سرور", "NonAdmin", "fa", None, False
    )
    # Non-admin does not hit admin fast-path (returns None to fall through to AI/standard flow)
    assert res_non_adm is None

    if old_id:
        os.environ["ADMIN_ID"] = old_id
        get_admin_ids()


def test_system_prompt_optimized():
    # Verify prompt is lean, contains all red lines and security guards
    assert "توکن‌ها" in SYSTEM_PROMPT or "سورس" in SYSTEM_PROMPT
    assert "جیل‌بریک" in SYSTEM_PROMPT
    assert "شل مخرب" in SYSTEM_PROMPT
    assert "ban_user_tool" in SYSTEM_PROMPT
    assert "extract_user_id_tool" in SYSTEM_PROMPT
    assert "generate_ai_image" in SYSTEM_PROMPT
    assert "execute_python_code" in SYSTEM_PROMPT
    assert "schedule_task_tool" in SYSTEM_PROMPT
    # Verify optimized character length (significantly less than 10,000 chars)
    assert len(SYSTEM_PROMPT) < 6000


@pytest.mark.asyncio
async def test_ai_service_caller_info_enrichment(monkeypatch):
    from src.core import ai_service
    from unittest.mock import AsyncMock

    captured_payloads = []

    # Mock client
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "درود بر شما"
            }
        }],
        "usage": {"total_tokens": 50}
    }

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(ai_service, "get_shared_client", lambda: mock_client)
    monkeypatch.setattr(config, "ROUTER_API_KEY", "test-key")
    monkeypatch.setenv("ROUTER_API_KEY", "test-key")

    # Set admin
    monkeypatch.setenv("ADMIN_ID", "987654")
    get_admin_ids()

    # Call with Admin
    await ai_service.generate_response(
        chat_id=123,
        user_prompt="سلام پرومته",
        caller_user_id=987654,
        caller_name="Master Architect",
        caller_username="master_owner",
        is_private_chat=True
    )

    admin_payload = mock_client.post.call_args[1]["json"]
    sys_msg = admin_payload["messages"][0]["content"]

    # Verify admin enrichment
    assert "Master Architect" in sys_msg
    assert "@master_owner" in sys_msg
    assert "987654" in sys_msg
    assert "فرمانده ارشد" in sys_msg
    assert "مالک و معمار کل" in sys_msg

    # Call with Non-Admin
    await ai_service.generate_response(
        chat_id=123,
        user_prompt="سلام پرومته",
        caller_user_id=55555,
        caller_name="Normal User",
        caller_username="norm_guy",
        is_private_chat=True
    )

    norm_payload = mock_client.post.call_args[1]["json"]
    sys_msg_norm = norm_payload["messages"][0]["content"]

    # Verify non-admin enrichment
    assert "Normal User" in sys_msg_norm
    assert "@norm_guy" in sys_msg_norm
    assert "55555" in sys_msg_norm
    assert "کاربر عمومی (ادمین نیست)" in sys_msg_norm


@pytest.mark.asyncio
async def test_expanded_social_greetings_and_help_fastpaths():
    class DummyUser:
        id = 12345
        first_name = "Reza"
        last_name = "Tehrani"
        username = "rezat"

    class DummyChat:
        id = 999

    class DummyMessage:
        message_id = 1
        reply_to_message = None

    # Test greetings
    greetings = ["سلام", "سلام پرومته", "سلام خوبی", "چطوری", "صبح بخیر", "شب بخیر", "خسته نباشی", "ممنون", "دستت درد نکنه"]
    for g in greetings:
        res = await bot._triage_fast_turn(DummyMessage(), DummyChat(), DummyUser(), g, "Reza", "fa", None, False)
        assert res is not None, f"Greeting failed: {g}"
        reply, extra = res
        assert extra is None
        assert len(reply) > 3

    # Test Bot Identity & Capabilities
    cap_queries = ["تو کی هستی", "اسمت چیه", "چیکار میتونی بکنی", "قابلیت هات چیه", "راهنما", "/help", "help"]
    for cq in cap_queries:
        res = await bot._triage_fast_turn(DummyMessage(), DummyChat(), DummyUser(), cq, "Reza", "fa", None, False)
        assert res is not None, f"Capability/Identity query failed: {cq}"
        reply, _ = res
        assert ("پرومته" in reply or "Prometheus" in reply or "قابلیت" in reply)

    # Test Date & Time queries
    dt_queries = ["ساعت چنده", "ساعت چند است", "الان ساعت چنده", "امروز چه روزیه", "امروز چند شنبه است", "تاریخ امروز"]
    for dt in dt_queries:
        res = await bot._triage_fast_turn(DummyMessage(), DummyChat(), DummyUser(), dt, "Reza", "fa", None, False)
        assert res is not None, f"Date/Time query failed: {dt}"
        reply, _ = res
        assert ("⏰" in reply or "📅" in reply)


def test_smart_tools_conceptual_zero_overhead():
    from src.tools.registry import get_smart_tools_for_prompt

    # Conceptual questions must attach ZERO tools
    assert get_smart_tools_for_prompt("پایتون چیه؟") == []
    assert get_smart_tools_for_prompt("هوش مصنوعی چیست") == []
    assert get_smart_tools_for_prompt("سلام چطوری") == []
    assert get_smart_tools_for_prompt("فرق لینوکس با ویندوز چیه") == []

    # Real-time / shopping queries must attach proper tools
    price_tools = [t["function"]["name"] for t in get_smart_tools_for_prompt("قیمت دلار چنده الان؟")]
    assert any("price" in pt or "forex" in pt or "dollar" in pt for pt in price_tools)

    shop_tools = [t["function"]["name"] for t in get_smart_tools_for_prompt("خرید گوشی سامسونگ از دیجیکالا")]
    assert "digikala_search" in shop_tools


@pytest.mark.asyncio
async def test_adaptive_model_routing_and_reasoning_effort(monkeypatch):
    """Verify dynamic model switching is completely removed and locked to 3.8-low."""
    from unittest.mock import AsyncMock
    from src.core import ai_service

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"choices": [{"message": {"content": "پاسخ سریع"}}]}'

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(ai_service, "get_shared_client", lambda: mock_client)
    monkeypatch.setattr(config, "ROUTER_API_KEY", "test-key")
    monkeypatch.setenv("ROUTER_API_KEY", "test-key")
    monkeypatch.setenv("ROUTER_MODEL", "3.8-low")

    # 1. Standard question -> should use 3.8-low directly with reasoning_effort="low"
    await ai_service.generate_response(
        chat_id=123,
        user_prompt="پایتون چیه؟",
        caller_user_id=12345,
        caller_name="User",
        caller_username="user1",
        is_private_chat=True
    )
    payload_std = mock_client.post.call_args[1]["json"]
    assert payload_std["model"] == "3.8-low"
    assert payload_std.get("reasoning_effort") == "low"
    # Empty tools should not have tools key
    assert "tools" not in payload_std

    # 2. Deep coding task (contains code block) -> strictly locked to 3.8-low (NO dynamic switching/escalation)
    await ai_service.generate_response(
        chat_id=123,
        user_prompt="```python\ndef buggy():\n    pass\n```\nاین کد رو دیباگ کن",
        caller_user_id=12345,
        caller_name="User",
        caller_username="user1",
        is_private_chat=True
    )
    payload_deep = mock_client.post.call_args[1]["json"]
    assert payload_deep["model"] == "3.8-low"
    assert payload_deep.get("reasoning_effort") == "low"

    # 3. Vision / Image turn -> strictly locked to 3.8-low (NO switching to 'Good')
    await ai_service.generate_response(
        chat_id=123,
        user_prompt="این عکس چیه؟",
        caller_user_id=12345,
        caller_name="User",
        caller_username="user1",
        is_private_chat=True,
        image_bytes=b"fake_image_content"
    )
    payload_vision = mock_client.post.call_args[1]["json"]
    assert payload_vision["model"] == "3.8-low"
    assert payload_vision.get("reasoning_effort") == "low"


