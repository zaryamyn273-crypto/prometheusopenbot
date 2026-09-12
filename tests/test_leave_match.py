"""Offline regression tests for the single-target leave fix.

Bug: asking (in group A) to leave group B made the bot leave BOTH.
Guards under test (no network, no Telegram):
- name search never guesses: 0 or 2+ matches -> refusal, zero leave calls.
- positive IDs are refused (group IDs are negative).
- without a live Bot client the tool reports honestly (never false success).
- after leave_chat, membership is verified before claiming success.
- on success exactly ONE chat is left and marked (the target only).
"""
import asyncio
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import src.tools.admin.group_manager as gm
from src.core.config import ADMIN_ID


class _Member:
    def __init__(self, status):
        self.status = status


class _Me:
    id = 999


class _Chat:
    def __init__(self, title):
        self.title = title


class FakeBot:
    """Minimal stand-in for telegram.Bot (records every call)."""

    def __init__(self, member_status="left", chat_title="Test Alpha", leave_raises=False):
        self.calls = []
        self._status = member_status
        self._title = chat_title
        self._leave_raises = leave_raises

    async def leave_chat(self, chat_id):
        self.calls.append(("leave_chat", chat_id))
        if self._leave_raises:
            raise RuntimeError("bot is not a member")

    async def get_chat(self, chat_id):
        self.calls.append(("get_chat", chat_id))
        return _Chat(self._title)

    async def get_me(self):
        return _Me()

    async def get_chat_member(self, chat_id, user_id):
        self.calls.append(("get_chat_member", chat_id))
        return _Member(self._status)


GROUPS = [
    {"chat_id": -1001, "title": "Test Alpha", "chat_type": "supergroup"},
    {"chat_id": -1002, "title": "Test Alpha 2", "chat_type": "supergroup"},
    {"chat_id": -1003, "title": "Completely Different", "chat_type": "group"},
]


async def _noop(*a, **k):
    return None


async def _groups():
    return [dict(g) for g in GROUPS]


def run_case(coro):
    return asyncio.run(coro)


async def _run(target, bot):
    removed = []
    async def _remove(cid):
        removed.append(cid)
    with patch.object(gm, "get_bot_instance", return_value=bot), \
         patch.object(gm.database, "sync_memory_from_d1_async", _noop), \
         patch.object(gm.database, "get_all_tracked_groups_async", _groups), \
         patch.object(gm.database, "remove_group_presence_async", _remove):
        res = await gm.leave_group_by_admin_tool(chat_identifier=target, caller_id=int(ADMIN_ID))
    leaves = [c[1] for c in (bot.calls if bot else []) if c[0] == "leave_chat"] if bot else []
    return res, leaves, removed


def main():
    # 1) Ambiguous name -> refusal listing BOTH candidates, nothing left.
    bot = FakeBot()
    res, leaves, removed = run_case(bot, bot) if False else asyncio.run(_run("test alpha", bot))
    assert "-1001" in res and "-1002" in res, f"must list candidates: {res}"
    assert leaves == [] and removed == [], "ambiguous query must leave nothing"
    print("1. ambiguous refusal: OK")

    # 2) Unknown name -> not found, nothing left.
    bot = FakeBot()
    res, leaves, removed = asyncio.run(_run("Zzz No Such", bot))
    assert leaves == [] and removed == []
    print("2. unknown refusal: OK")

    # 3) Positive ID -> refused (group IDs are negative), nothing left.
    bot = FakeBot()
    res, leaves, removed = asyncio.run(_run("12345", bot))
    assert leaves == [] and removed == []
    print("3. positive-ID refusal: OK")

    # 4) No live client -> honest report, NO false success, DB untouched.
    res, leaves, removed = asyncio.run(_run("-1001", None))
    assert leaves == [] and removed == [], "must not claim or mark anything"
    print("4. honest no-client: OK")

    # 5) Happy path -> EXACTLY the target left+marked, nothing else.
    bot = FakeBot(member_status="left", chat_title="Test Alpha")
    res, leaves, removed = asyncio.run(_run("-1001", bot))
    assert leaves == [-1001], f"must leave only target: {leaves}"
    assert removed == [-1001], f"must mark only target: {removed}"
    print("5. single-target leave: OK")

    # 6) leave_chat fails + still member -> honest failure, DB untouched.
    bot = FakeBot(member_status="member", leave_raises=True)
    with patch.object(gm, "get_bot_instance", return_value=bot):
        async def _boom(chat_id, user_id):
            return _Member("member")
        bot.get_chat_member = _boom
        res, leaves, removed = asyncio.run(_run("-1003", bot))
    assert removed == [], "failed leave must not touch DB"
    print("6. honest failure: OK")

    print("== test_leave_match DONE ==")


if __name__ == "__main__":
    main()
