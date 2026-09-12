"""Offline tests for admin-adjustable per-user quotas + tight quota triggers."""
import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core import database
from src.core.config import ADMIN_ID
from src.tools.admin import intent_router as ir


async def _d1_fail(sql, params=None):
    return {"success": False, "results": []}


def _d1_sync_fail(sql, params=None):
    return {"success": False, "results": []}


async def main():
    assert ir.fa_digits_to_latin("۱۲۳۴۵ و ٦٧") == "12345 و 67", ir.fa_digits_to_latin("۱۲۳۴۵")
    print("1. fa digits: OK")

    uid = 9200001
    with patch.object(database, "execute_d1_query", _d1_fail):
        assert database.get_user_limit(uid) == database.DAILY_USER_LIMIT
        assert await database.set_user_quota_async(uid, 100) is True
        assert database.get_user_limit(uid) == 100
        assert await database.set_user_quota_async(uid, 0) is False
        assert await database.set_user_quota_async(uid, 10001) is False
        assert database.get_user_limit(uid) == 100
        assert await database.adjust_user_quota_async(uid, 20) == 120
        assert await database.adjust_user_quota_async(uid, -30) == 90
        assert await database.adjust_user_quota_async(uid, -100) is None
        assert database.get_user_limit(uid) == 90
        # bump honors the override, not the global default
        for _ in range(90):
            allowed, _, _ = await database.bump_daily_usage_async(uid)
            assert allowed
        allowed, used, lim = await database.bump_daily_usage_async(uid)
        assert not allowed and lim == 90, (allowed, used, lim)
        assert await database.clear_user_quota_async(uid) is True
        assert database.get_user_limit(uid) == database.DAILY_USER_LIMIT
    print("2. set/adjust/clear/bump: OK")

    with patch.object(database, "execute_d1_query", _d1_fail):
        r = await ir.try_admin_intent_async("سهمیه 9300001 رو بکن ۱۰۰", int(ADMIN_ID), -1001)
        assert "100" in r and "9300001" in r, r
        assert database.get_user_limit(9300001) == 100
        print("3. fa set (persian digits): OK")

        r = await ir.try_admin_intent_async("سهمیه 9300001 +20", int(ADMIN_ID), -1001)
        assert "120" in r, r
        print("4. fa adjust signed: OK")

        r = await ir.try_admin_intent_async("سهمیه 9300001 رو ۱۰ تا زیاد کن", int(ADMIN_ID), -1001)
        assert "130" in r, r
        print("5. fa adjust verb: OK")

        r = await ir.try_admin_intent_async("set quota for 9300002 to 55", int(ADMIN_ID), -1001)
        assert "55" in r and database.get_user_limit(9300002) == 55, r
        print("6. en set: OK")

        r = await ir.try_admin_intent_async("decrease 9300002 quota by 5", int(ADMIN_ID), -1001)
        assert "50" in r, r
        print("7. en adjust verb: OK")

        r = await ir.try_admin_intent_async("سهمیه 9300001 رو حذف کن", int(ADMIN_ID), -1001)
        assert database.get_user_limit(9300001) == database.DAILY_USER_LIMIT, r
        print("8. fa clear: OK")

        # Quota OF something else must NEVER show/touch quotas.
        for q in ["سهمیه بنزین چقدره؟", "سهمیه اینترنت چقدر شد", "سهمیه کنکور", "usage", "quota"]:
            r = await ir.try_admin_intent_async(q, int(ADMIN_ID), -1001)
            assert r is None, (q, r)
        print("9. no false positives: OK")

        r = await ir.try_admin_intent_async("سهمیه", int(ADMIN_ID), -1001)
        assert r is not None and "نامحدود" in r, r
        r = await ir.try_admin_intent_async("سهمیه XyzUnknown رو بکن ۵۰", int(ADMIN_ID), -1001)
        assert "ریپلای" in r, r
        print("10. note + unresolvable: OK")

    print("== test_quota_override DONE ==")


if __name__ == "__main__":
    asyncio.run(main())
