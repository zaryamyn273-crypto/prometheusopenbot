import time
import pytest
from unittest.mock import MagicMock

from src.core import config
import bot


class MockUser:
    def __init__(self, uid=12345, first_name="Ali", last_name="Rezaei", username="alireza"):
        self.id = uid
        self.first_name = first_name
        self.last_name = last_name
        self.username = username
        self.language_code = "fa"


class MockChat:
    def __init__(self, cid=1001, title="TestChat"):
        self.id = cid
        self.title = title


class MockMessage:
    def __init__(self):
        self.reply_to_message = None


@pytest.mark.asyncio
async def test_fastpath_common_greetings():
    """Verify all required common greetings resolve instantly without network/LLM."""
    chat = MockChat()
    msg = MockMessage()
    user = MockUser()

    greetings = [
        "سلام", "درود", "سلام علیک", "سلام پرومته", "سلام خوبی",
        "چطوری", "خوبی", "صبح بخیر", "عصر بخیر", "شب بخیر",
        "خسته نباشی", "ممنون", "تشکر", "دمت گرم", "مرسی",
        "دستت درد نکنه", "سپاس", "hi", "hello", "hey",
        "good morning", "good evening"
    ]

    # Test with Persian and English punctuations
    punctuations = ["", "!", "؟", "?", "...", " :", " !", " :)"]

    for g in greetings:
        for p in punctuations:
            query = f"{g}{p}"
            t0 = time.perf_counter()
            res = await bot._triage_fast_turn(
                msg, chat, user, query, user.first_name, "fa", None, False
            )
            elapsed = time.perf_counter() - t0

            assert res is not None, f"Greeting fast-path missed for '{query}'"
            reply_text, extra = res
            assert extra is None
            assert isinstance(reply_text, str) and len(reply_text) > 0
            assert elapsed < 0.025, f"Execution too slow ({elapsed*1000:.2f}ms) for '{query}'"


@pytest.mark.asyncio
async def test_fastpath_bot_identity_and_capabilities():
    """Verify bot identity and capabilities queries return structured attractive cards."""
    chat = MockChat()
    msg = MockMessage()
    user = MockUser()

    identity_queries = [
        "تو کی هستی", "تو کیستی", "اسمت چیه", "نامت چیه",
        "معرفی کن", "کی هستی"
    ]
    for q in identity_queries:
        t0 = time.perf_counter()
        res = await bot._triage_fast_turn(
            msg, chat, user, q, user.first_name, "fa", None, False
        )
        elapsed = time.perf_counter() - t0
        assert res is not None, f"Identity fast-path missed for '{q}'"
        text, _ = res
        assert "پرومته" in text or "Prometheus" in text
        assert elapsed < 0.025

    capabilities_queries = [
        "چیکار میتونی بکنی", "چه کارهایی بلدی", "قابلیت هات چیه",
        "امکاناتت چیه", "راهنما", "help", "/help", "دستورات", "منو"
    ]
    for q in capabilities_queries:
        t0 = time.perf_counter()
        res = await bot._triage_fast_turn(
            msg, chat, user, q, user.first_name, "fa", None, False
        )
        elapsed = time.perf_counter() - t0
        assert res is not None, f"Capabilities fast-path missed for '{q}'"
        text, _ = res
        assert "قابلیت" in text or "راهنما" in text or "Capabilities" in text or "پرومته" in text
        assert elapsed < 0.025


@pytest.mark.asyncio
async def test_fastpath_live_date_and_time():
    """Verify dynamic date and time calculations resolve deterministically in Python."""
    chat = MockChat()
    msg = MockMessage()
    user = MockUser()

    time_queries = ["ساعت چنده", "ساعت چند است", "الان ساعت چنده", "ساعت", "time"]
    for q in time_queries:
        t0 = time.perf_counter()
        res = await bot._triage_fast_turn(
            msg, chat, user, q, user.first_name, "fa", None, False
        )
        elapsed = time.perf_counter() - t0
        assert res is not None, f"Time fast-path missed for '{q}'"
        text, _ = res
        assert text.startswith("⏰")
        assert "تهران" in text or "Tehran" in text
        assert elapsed < 0.025

    date_queries = [
        "امروز چه روزیه", "امروز چندمه", "تاریخ امروز", "امروز چند شنبه است",
        "امروز چندشنبه است", "امروز چندم است", "تاریخ"
    ]
    for q in date_queries:
        t0 = time.perf_counter()
        res = await bot._triage_fast_turn(
            msg, chat, user, q, user.first_name, "fa", None, False
        )
        elapsed = time.perf_counter() - t0
        assert res is not None, f"Date fast-path missed for '{q}'"
        text, _ = res
        assert "📅" in text
        assert "خورشیدی" in text or "Jalali" in text
        assert "میلادی" in text or "Gregorian" in text
        # Verify weekday is present for 'چه روزیه' / 'چند شنبه است'
        assert any(w in text for w in ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه"])
        assert elapsed < 0.025


@pytest.mark.asyncio
async def test_fastpath_creator_and_admin_info():
    """Verify creator and admin identity queries return the admin identity card."""
    chat = MockChat()
    msg = MockMessage()
    user = MockUser()

    admin_queries = [
        "ادمین کیه", "مدیر کیه", "رییس کیه", "رئیس کیه", "سازندت کیه", "خالقت کیه"
    ]
    for q in admin_queries:
        t0 = time.perf_counter()
        res = await bot._triage_fast_turn(
            msg, chat, user, q, user.first_name, "fa", None, False
        )
        elapsed = time.perf_counter() - t0
        assert res is not None, f"Admin info fast-path missed for '{q}'"
        text, _ = res
        assert "فرمانده ارشد" in text or "Master Admin" in text or "مالک" in text
        assert str(config.ADMIN_ID) in text
        assert elapsed < 0.025


@pytest.mark.asyncio
async def test_fastpath_clean_normalization():
    """Verify stripping bot mentions, names, whitespace, and punctuation."""
    chat = MockChat()
    msg = MockMessage()
    user = MockUser()

    queries_with_noise = [
        ("سلام پرومته!", "سلام"),
        ("@Prometheusbaibot چیکار میتونی بکنی؟", "قابلیت"),
        ("پرومته ساعت چنده؟!", "ساعت"),
        ("بات امروز چه روزیه؟", "امروز"),
        ("  سلام خوبی ؟!  ", "سلام"),
        ("@bot مدیر کیه؟؟", "فرمانده"),
        ("پرومته تو کی هستی", "پرومته"),
        ("خسته نباشی بات", "سلامت"),
        ("دمت گرم پرومته!!", "وظیفه"),
    ]

    for raw_q, expected_word in queries_with_noise:
        t0 = time.perf_counter()
        res = await bot._triage_fast_turn(
            msg, chat, user, raw_q, user.first_name, "fa", None, False
        )
        elapsed = time.perf_counter() - t0
        assert res is not None, f"Failed for noisy query: '{raw_q}'"
        text, _ = res
        assert expected_word in text
        assert elapsed < 0.025


@pytest.mark.asyncio
async def test_fastpath_strict_sub_millisecond_benchmark():
    """Benchmark high-speed execution (<0.001s = 1ms per call) over 1000 repetitions."""
    chat = MockChat()
    msg = MockMessage()
    user = MockUser()

    sample_queries = [
        "سلام", "صبح بخیر", "ساعت چنده", "امروز چندمه", "تو کی هستی",
        "چیکار میتونی بکنی", "ادمین کیه", "who are you", "what time is it"
    ]

    for q in sample_queries:
        # Warmup
        await bot._triage_fast_turn(msg, chat, user, q, user.first_name, "fa", None, False)

        N = 100
        t0 = time.perf_counter()
        for _ in range(N):
            await bot._triage_fast_turn(msg, chat, user, q, user.first_name, "fa", None, False)
        avg_time = (time.perf_counter() - t0) / N

        assert avg_time < 0.001, f"Average execution for '{q}' exceeded 1ms: {avg_time*1000:.3f}ms"


@pytest.mark.asyncio
async def test_fastpath_gates_and_fallthrough():
    """Verify that turns needing Tier 2 (images, replies, long text) return None."""
    chat = MockChat()
    msg = MockMessage()
    user = MockUser()

    # Image attachment
    assert await bot._triage_fast_turn(msg, chat, user, "سلام", user.first_name, "fa", b"fake_img", False) is None

    # Reply to another message
    assert await bot._triage_fast_turn(msg, chat, user, "سلام", user.first_name, "fa", None, True) is None

    # Text >= 120 chars
    long_text = "سلام " * 30
    assert await bot._triage_fast_turn(msg, chat, user, long_text, user.first_name, "fa", None, False) is None

    # Complex / non-fastpath queries
    assert await bot._triage_fast_turn(msg, chat, user, "یک مقاله ۵۰۰ کلمه‌ای در مورد اقتصاد بنویس", user.first_name, "fa", None, False) is None
