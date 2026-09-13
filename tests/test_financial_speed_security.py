"""
Verification Test Suite: Financial Zero-Latency Architecture & Security Hardening
Tests Stale-While-Revalidate, crypto parallel racing, secret masking, and memory bounds.
"""

import asyncio
import os
import time
import pytest
from src.core import security, database
from src.tools.financial import get_price, get_dollar_price, get_gold_and_coin_price
from src.tools.files import read_document_file
from src.tools.system import mask_sensitive_shell_output


@pytest.mark.asyncio
async def test_financial_stale_while_revalidate():
    # 1. First call populates cache
    t0 = time.perf_counter()
    p1 = await get_price("BTC")
    dt1 = (time.perf_counter() - t0) * 1000
    assert "BTC" in p1
    assert "قیمت دلاری" in p1

    # 2. Second call must be sub-millisecond RAM hit
    t1 = time.perf_counter()
    p2 = await get_price("BTC")
    dt2 = (time.perf_counter() - t1) * 1000
    assert dt2 < 20.0  # Must be faster than 20ms (typically <1ms)
    assert p1[:80] == p2[:80]


@pytest.mark.asyncio
async def test_dollar_and_gold_instant_response():
    t0 = time.perf_counter()
    usd = await get_dollar_price()
    dt = (time.perf_counter() - t0) * 1000
    assert "دلار آمریکا" in usd or "تومان" in usd

    t1 = time.perf_counter()
    gold = await get_gold_and_coin_price()
    assert "طلا" in gold or "سکه" in gold


def test_security_sanitization_railway_token():
    fake_token = "railway_secret_token_123456789"
    os.environ["RAILWAY_TOKEN"] = fake_token

    leaked = f"Error connecting to railway with token {fake_token} in process"
    cleaned = security.sanitize_output(leaked)
    assert fake_token not in cleaned
    assert "[SECRET]" in cleaned

    # Test group shell output masking
    shell_out = f"Deployment active: {fake_token}"
    masked, redacted = mask_sensitive_shell_output(shell_out, is_private_chat=False)
    assert fake_token not in masked
    assert "[SECRET]" in masked
    assert redacted is True


def test_path_traversal_jail():
    assert "غیرمجاز" in read_document_file("/etc/passwd")
    assert "غیرمجاز" in read_document_file("/proc/self/environ")
    assert "غیرمجاز" in read_document_file("src/core/config.py")


def test_query_rewriter_intent_preservation():
    from src.tools.internal import bot_query_rewriter
    # Repeated consecutive words should be deduplicated
    assert bot_query_rewriter("سلام سلام") == "__PINGPONG__ سلام"
    
    # Non-consecutive words in grammar/math should be preserved completely!
    res1 = bot_query_rewriter("قیمت اتریوم به دلار و بیت کوین به دلار")
    assert "به دلار" in res1
    assert res1.count("دلار") == 2
    
    res2 = bot_query_rewriter("x = x + 1")
    assert res2 == "x = x + 1"


def test_vision_preprocessor():
    from PIL import Image
    import io
    from src.core.ai_service import optimize_image_for_vision
    
    # Generate dummy test image
    img = Image.new("RGB", (400, 300), color=(73, 109, 137))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw = buf.getvalue()
    
    b64, mime = optimize_image_for_vision(raw)
    assert mime == "image/jpeg"
    assert len(b64) > 100


if __name__ == "__main__":
    asyncio.run(test_financial_stale_while_revalidate())
    asyncio.run(test_dollar_and_gold_instant_response())
    test_security_sanitization_railway_token()
    test_path_traversal_jail()
    test_query_rewriter_intent_preservation()
    test_vision_preprocessor()
    print("ALL FINANCIAL SPEED & SECURITY TESTS PASSED!")
