"""Offline tests for the deterministic admin-intent router (fa/en, no slash)."""
import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.config import ADMIN_ID
from src.tools.admin import intent_router as ir
import src.tools.admin.group_manager as gm


async def _leave(chat_identifier=None, caller_id=0, **k):
    return f"LEAVE:{chat_identifier}:{caller_id}"


async def _ban(group_name=None, caller_id=0, **k):
    return f"BAN:{group_name}:{caller_id}"


async def _list(caller_id=0, **k):
    return "LIST"


async def main():
    with patch.object(gm, "leave_group_by_admin_tool", _leave), \
         patch.object(gm, "ban_group_by_name_or_id_tool", _ban), \
         patch.object(gm, "list_joined_groups_tool", _list):
        r = await ir.try_admin_intent_async("پرومته از گروه تست خارج شو", int(ADMIN_ID), -1001)
        assert r.startswith("LEAVE:") and "تست" in r, r
        print("1. fa leave: OK")

        r = await ir.try_admin_intent_async("leave group Test", int(ADMIN_ID), -1001)
        assert r.startswith("LEAVE:") and "test" in r, r
        print("2. en leave: OK")

        r = await ir.try_admin_intent_async("leave it", int(ADMIN_ID), -1001)
        assert r.startswith("LEAVE:") is False and "Which group" in r, r
        print("3. vague guard: OK")

        r = await ir.try_admin_intent_async("گروه اسپم را بن کن", int(ADMIN_ID), -1001)
        assert r.startswith("BAN:") and "اسپم" in r, r
        print("4. fa ban: OK")

        r = await ir.try_admin_intent_async("لیست گروه ها", int(ADMIN_ID), -1001)
        assert r == "LIST", r
        print("5. fa list: OK")

        r = await ir.try_admin_intent_async("از گروه تست خارج شو", 12345, -1001)
        assert r is None, r
        print("6. non-admin ignored: OK")

        r = await ir.try_admin_intent_async("سلام چطوری خوبی؟", int(ADMIN_ID), -1001)
        assert r is None, r
        print("7. chatter falls through: OK")

        r = await ir.try_admin_intent_async("سهمیه من", int(ADMIN_ID), -1001)
        assert r is not None and "نامحدود" in r, r
        print("8. quota note: OK")

    print("== test_intent_router DONE ==")


if __name__ == "__main__":
    asyncio.run(main())
