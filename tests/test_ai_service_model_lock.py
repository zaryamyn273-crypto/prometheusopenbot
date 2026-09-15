import os
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.core import config, ai_service
from src.core.settings import Settings


def test_config_and_settings_model_lock():
    """Verify config and settings default to 3.8-low."""
    # Ensure default in config
    assert config.ROUTER_MODEL == "3.8-low"
    assert getattr(config, "ROUTER_FAST_MODEL", "") == "3.8-low"

    # Ensure Settings schema defaults to 3.8-low
    if Settings is not object:
        # Create minimal settings mock
        os.environ["TELEGRAM_BOT_TOKEN"] = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz123456"
        os.environ["ADMIN_ID"] = "8814471014"
        if "ROUTER_MODEL" in os.environ:
            del os.environ["ROUTER_MODEL"]
        s = Settings()
        assert s.ROUTER_MODEL == "3.8-low"


@pytest.mark.asyncio
async def test_generate_response_locked_to_low_latency_model(monkeypatch):
    """Verify that every prompt directly uses 3.8-low with reasoning_effort='low' and no model switching."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"choices": [{"message": {"content": "پاسخ مدل"}}]}'
    mock_resp.json.return_value = {"choices": [{"message": {"content": "پاسخ مدل"}}]}

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(ai_service, "get_shared_client", lambda: mock_client)
    monkeypatch.setattr(config, "ROUTER_API_KEY", "test-key")
    monkeypatch.setenv("ROUTER_API_KEY", "test-key")
    monkeypatch.delenv("ROUTER_MODEL", raising=False)

    # 1. Simple conversation
    await ai_service.generate_response(
        chat_id=101,
        user_prompt="سلام چطوری؟",
        caller_user_id=1001,
        is_private_chat=True
    )
    payload1 = mock_client.post.call_args[1]["json"]
    assert payload1["model"] == "3.8-low"
    assert payload1["reasoning_effort"] == "low"

    # 2. Code execution query (previously would switch to High/medium)
    await ai_service.generate_response(
        chat_id=101,
        user_prompt="یک اسکریپت پایتون کامل برای پردازش دیتا بنویس و اجرا کن",
        caller_user_id=1001,
        is_private_chat=True
    )
    payload2 = mock_client.post.call_args[1]["json"]
    assert payload2["model"] == "3.8-low"
    assert payload2["reasoning_effort"] == "low"

    # 3. Deep math query (previously would switch to High)
    await ai_service.generate_response(
        chat_id=101,
        user_prompt="معادله دیفرانسیل مرتبه دوم ناهمگن را با روش تغییر پارامترها حل کن",
        caller_user_id=1001,
        is_private_chat=True
    )
    payload3 = mock_client.post.call_args[1]["json"]
    assert payload3["model"] == "3.8-low"
    assert payload3["reasoning_effort"] == "low"

    # 4. Long prompt (>1500 chars) with code block (previously would switch to High)
    long_code_prompt = "```python\n" + ("x = 1\n" * 350) + "```\nاین کد رو کامل بررسی کن"
    assert len(long_code_prompt) > 1500
    await ai_service.generate_response(
        chat_id=101,
        user_prompt=long_code_prompt,
        caller_user_id=1001,
        is_private_chat=True
    )
    payload4 = mock_client.post.call_args[1]["json"]
    assert payload4["model"] == "3.8-low"
    assert payload4["reasoning_effort"] == "low"

    # 5. Multimodal Vision turn (previously would switch to 'Good')
    await ai_service.generate_response(
        chat_id=101,
        user_prompt="این عکس رو تحلیل کن",
        caller_user_id=1001,
        is_private_chat=True,
        image_bytes=b"GIF89a..."
    )
    payload5 = mock_client.post.call_args[1]["json"]
    assert payload5["model"] == "3.8-low"
    assert payload5["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_translate_text_uses_locked_model(monkeypatch):
    """Verify translate_text locks to 3.8-low model."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": [{"message": {"content": "Hello world"}}]}

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(ai_service, "get_shared_client", lambda: mock_client)
    monkeypatch.setattr(config, "ROUTER_API_KEY", "test-key")
    monkeypatch.setenv("ROUTER_API_KEY", "test-key")
    monkeypatch.delenv("ROUTER_MODEL", raising=False)

    res = await ai_service.translate_text("سلام دنیا", "English")
    assert res == "Hello world"
    payload = mock_client.post.call_args[1]["json"]
    assert payload["model"] == "3.8-low"


def test_endpoint_failure_and_cooldown_resilience(monkeypatch):
    """Verify that failed/timeout endpoints are cooled down and excluded from candidate list."""
    import time
    from src.core.ai_service import mark_endpoint_failure, mark_endpoint_success, _get_target_router_endpoints, _FAILED_ENDPOINTS

    bad_ep = "http://bad-router.railway.internal:20128/v1"
    good_ep = "https://good-proxy.com/v1"

    monkeypatch.setattr(config, "ROUTER_INTERNAL_BASE_URL", bad_ep)
    monkeypatch.setattr(config, "ROUTER_BASE_URL", good_ep)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")

    # Initial state: bad_ep might be attempted first
    mark_endpoint_failure(bad_ep, cooldown_sec=120.0)
    eps = _get_target_router_endpoints()
    assert bad_ep not in eps
    assert good_ep in eps

    # Success marks endpoint healthy
    mark_endpoint_success(good_ep)
    assert good_ep not in _FAILED_ENDPOINTS
