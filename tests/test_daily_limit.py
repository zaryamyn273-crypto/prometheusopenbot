"""Offline tests for the daily per-user quota (24h auto-reset, UTC day buckets).

Hot path is pure RAM; D1 is stubbed out here to prove graceful offline
behavior (RAM still enforces the limit for the process lifetime).
"""
import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core import database


async def _d1_fail(sql, params=None):
    return {"success": False, "results": []}


async def main():
    database.DAILY_USER_LIMIT = 3
    uid = 9100001
    with patch.object(database, "execute_d1_query", _d1_fail):
        for i in range(1, 4):
            allowed, used, lim = await database.bump_daily_usage_async(uid)
            assert allowed and used == i and lim == 3, (allowed, used, lim)
        allowed, used, lim = await database.bump_daily_usage_async(uid)
        assert not allowed and used == 4 and lim == 3, (allowed, used, lim)
        used2, lim2 = await database.get_daily_usage_async(uid)
        assert used2 == 4 and lim2 == 3, (used2, lim2)
        assert database.get_daily_used(uid) == 4
    print("1. bump/refuse/read: OK")

    s = database.seconds_until_daily_reset()
    assert 0 < s <= 86400, s
    print("2. reset countdown range: OK")

    # Isolation between users.
    with patch.object(database, "execute_d1_query", _d1_fail):
        allowed, used, _ = await database.bump_daily_usage_async(9100002)
        assert allowed and used == 1, (allowed, used)
    print("3. per-user isolation: OK")

    print("== test_daily_limit DONE ==")


if __name__ == "__main__":
    asyncio.run(main())
