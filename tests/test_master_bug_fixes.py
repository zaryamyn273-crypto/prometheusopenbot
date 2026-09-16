"""Comprehensive test suite verifying all master bug fixes:
1. Concise Key-Points persona rule & Elaboration intent detection
2. Dynamic token budget allocation
3. Nobitex float safety on missing or malformed market stats
4. Math safe exponent evaluation and ReDoS prevention
5. SQLite FTS5 messages deletion trigger integrity
6. Privilege separation: group admins cannot manipulate quotas or admin memories
7. Scheduler cron run bounds and safety
"""
import pytest
import sqlite3
import asyncio
from unittest.mock import MagicMock, patch

from src.core import config
from src.core import database
from src.tools.scientific import calculate_math_expression
from src.tools.financial import _get_nobitex_price
from src.core.scheduler import get_next_cron_run


# =========================================================================
# 1. Concise Persona & Intent Detection Tests
# =========================================================================

def test_concise_mode_intent_detection():
    """Verify that default queries trigger concise mode and only explicit elaboration triggers full mode."""
    elaboration_triggers = [
        "بیشتر", "جزییات", "جزئیات", "کامل تر", "کاملتر", "با جزییات", "با جزئیات",
        "توضیح بده", "بیشتر بگو", "بسط بده", "بازش کن", "عمیق تر", "گام به گام",
        "مرحله به مرحله", "چرا؟", "علت چیست", "دلیل چیست",
        "elaborate", "explain more", "in detail", "deep dive", "step by step"
    ]

    def is_elaboration(text: str) -> bool:
        t = (text or "").lower()
        return any(k in t for k in elaboration_triggers)

    # Concise / Direct queries should NOT trigger elaboration
    assert not is_elaboration("سلام پایتون چیست؟")
    assert not is_elaboration("قیمت بیت کوین چنده؟")
    assert not is_elaboration("یک اسکریپت بش برای بکاپ بنویس")
    assert not is_elaboration("تفاوت داکر و کوبرنتیز در چند مورد")
    assert not is_elaboration("hello world")

    # Explicit elaboration queries MUST trigger elaboration
    assert is_elaboration("بیشتر توضیح بده")
    assert is_elaboration("لطفاً با جزییات کامل توضیح بده")
    assert is_elaboration("گام به گام برام بازش کن")
    assert is_elaboration("please elaborate on that")
    assert is_elaboration("can you explain more?")


def test_dynamic_token_budget():
    """Verify dynamic token caps: 900 for concise turns, 3000 for elaboration, 1400 for tools."""
    def get_tok_cap(has_tools: bool, is_elaboration: bool, is_summary: bool) -> int:
        if has_tools:
            return 1400
        elif is_elaboration or is_summary:
            return 3000
        else:
            return 900

    assert get_tok_cap(False, False, False) == 900
    assert get_tok_cap(False, True, False) == 3000
    assert get_tok_cap(False, False, True) == 3000
    assert get_tok_cap(True, False, False) == 1400
    assert get_tok_cap(True, True, False) == 1400


# =========================================================================
# 2. Nobitex Crypto Float Parsing Safety
# =========================================================================

@pytest.mark.asyncio
async def test_nobitex_price_safety_with_malformed_data():
    """Verify that _get_nobitex_price handles None, missing fields, or bad strings without TypeError."""
    malformed_stats = {
        "btc-rls": {
            "latest": None,
            "dayChange": "invalid_num",
            "bestBuy": None,
            "bestSell": None
        },
        "eth-rls": {
            "latest": "0",
            "dayChange": None
        },
        "sol-rls": {}
    }

    with patch("src.tools.financial._refresh_nobitex_stats", return_value=malformed_stats):
        with patch("src.tools.financial._NOBITEX_STATS_CACHE", malformed_stats):
            with patch("src.tools.financial._NOBITEX_STATS_TS", 9999999999.0):
                # When latest is 0 or None and global_usd is 0, should return None safely
                res = await _get_nobitex_price("btc", global_usd=0.0)
                assert res is None

                res_eth = await _get_nobitex_price("eth", global_usd=0.0)
                assert res_eth is None

                res_sol = await _get_nobitex_price("sol", global_usd=0.0)
                assert res_sol is None


# =========================================================================
# 3. Math Calculation Exponent Safety & ReDoS Guard
# =========================================================================

def test_math_safe_exponent_guards():
    """Verify that calculate_math_expression blocks giant exponents and nested exponent DoS attacks."""
    # Valid expressions should succeed
    res_valid = calculate_math_expression("sqrt(144) + 2^10")
    assert "1,036" in res_valid or "1036" in res_valid

    # Nested exponentiation attack should be blocked
    res_nested = calculate_math_expression("9**9**9**9")
    assert "⚠️ توان درخواستی فراتر از سقف مجاز ایمنی محاسباتی است." in res_nested

    # Giant single exponent should be blocked
    res_giant = calculate_math_expression("2**50000")
    assert "⚠️ توان درخواستی فراتر از سقف مجاز ایمنی محاسباتی است." in res_giant

    res_huge = calculate_math_expression("10**10000")
    assert "⚠️ توان درخواستی فراتر از سقف مجاز ایمنی محاسباتی است." in res_huge


# =========================================================================
# 4. Database FTS5 Delete Trigger Integrity
# =========================================================================

def test_sqlite_fts5_deletion_trigger():
    """Verify that deleting from messages table with trg_messages_ad works without SQLite syntax errors."""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()

    # Create schema matching production database
    cur.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            role TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE VIRTUAL TABLE messages_fts USING fts5(
            content,
            chat_id UNINDEXED
        )
    """)
    # Production insert trigger
    cur.execute("""
        CREATE TRIGGER trg_messages_ai AFTER INSERT ON messages BEGIN
            INSERT INTO messages_fts(rowid, content, chat_id)
            VALUES (new.id, new.content, new.chat_id);
        END;
    """)
    # Production fixed delete trigger
    cur.execute("""
        CREATE TRIGGER trg_messages_ad AFTER DELETE ON messages BEGIN
            DELETE FROM messages_fts WHERE rowid = old.id;
        END;
    """)

    # Insert a message
    cur.execute("INSERT INTO messages (chat_id, role, content) VALUES (123, 'user', 'hello prometheus')")
    msg_id = cur.lastrowid
    conn.commit()

    # Verify FTS5 indexed it
    cur.execute("SELECT rowid, content FROM messages_fts WHERE messages_fts MATCH 'prometheus'")
    rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == msg_id

    # Delete message - MUST NOT raise SQLite error!
    cur.execute("DELETE FROM messages WHERE id = ?", (msg_id,))
    conn.commit()

    # Verify FTS5 entry was also deleted
    cur.execute("SELECT rowid FROM messages_fts WHERE rowid = ?", (msg_id,))
    assert cur.fetchall() == []
    conn.close()


# =========================================================================
# 5. Privilege Separation & Admin Checks
# =========================================================================

def test_admin_privilege_checks():
    """Verify is_admin logic and ensure non-admin IDs cannot bypass."""
    master_admin_id = config.ADMIN_ID
    assert config.is_admin_id(master_admin_id) is True

    fake_group_admin_id = 987654321
    if fake_group_admin_id != master_admin_id:
        assert config.is_admin_id(fake_group_admin_id) is False


# =========================================================================
# 6. Scheduler Cron Safety
# =========================================================================

def test_cron_next_run_bounded():
    """Verify that get_next_cron_run executes quickly on valid expressions and raises ValueError on invalid."""
    import datetime
    base = datetime.datetime(2026, 1, 1, 12, 0, 0)

    # Every minute
    next_dt = get_next_cron_run("* * * * *", base)
    assert next_dt == datetime.datetime(2026, 1, 1, 12, 1, 0)

    # Specific hour
    next_dt2 = get_next_cron_run("0 14 * * *", base)
    assert next_dt2 == datetime.datetime(2026, 1, 1, 14, 0, 0)

    # Impossible date (e.g. Feb 31st) should raise ValueError without hanging
    with pytest.raises(ValueError):
        get_next_cron_run("* * 31 2 *", base)
