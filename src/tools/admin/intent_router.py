"""Deterministic multilingual admin-intent router.

The Master Admin speaks naturally (Persian, English, ...) — with or without a
slash — and the bot executes the needed command itself. This runs BEFORE the
heavy AI turn: zero LLM cost and zero ambiguity for destructive actions.

Only the admin's intents execute here (caller must be ADMIN_ID). Anything
unrecognized returns None and falls through to the normal AI pipeline.

Covered intents: leave-group, ban-group, list-groups, my-quota.
"""

import logging
import re

from src.core.config import ADMIN_ID

logger = logging.getLogger(__name__)

_CALL_NAMES = ("پرومته", "prometheus", "پرومتئوس", "پرومتیوس", "پرومتيوس", "پرومتـه")

_HERE_WORDS = frozenset({
    "this group", "this chat", "here", "current group",
    "اینجا", "این گروه", "این چت", "همین گروه", "همینجا",
})

# Vague targets must NEVER resolve to a group — ask instead of guessing.
_VAGUE_WORDS = frozenset({
    "it", "this", "that", "them", "him", "her", "you", "me",
    "group", "chat", "one", "that one",
    "او", "این", "اون", "آن", "ایشون", "شما", "من",
    "گروه", "چت", "یکی",
})
_CLARIFY = "کدام گروه؟ شناسه عددی یا نام دقیق را بگو. (Which group? Send the ID or exact name.)"

_LIST_PHRASES = frozenset({
    "لیست گروه ها", "لیست گروهها", "لیست گروه",
    "گروه ها", "گروهها", "گروهام", "گروه هام",
    "نمایش گروه ها", "گروه ها کجان", "گروه ها را نشان بده",
    "list groups", "show groups", "my groups", "groups list", "list my groups",
})

_QUOTA_PHRASES = frozenset({
    "سهمیه", "سهمیه من", "سهمیه ام", "لیمیت", "لیمیت من",
    "سهمیه چقدر است", "سهمیه چقدره", "چقدر سهمیه دارم",
    "quota", "my quota", "my limit", "usage", "my usage",
})

_LEAVE_RES = (
    r"از\s+(?:گروه\s+|چت\s+)?(.+?)\s+(خارج\s*شو|برو\s*بیرون|ترک\s*کن|خارج\s*کن|لف\s*کن)\s*$",
    r"^(?:گروه\s+|چت\s+)?(.+?)\s+(?:رو|را)\s+(ترک\s*کن|خارج\s*کن)\s*$",
    r"^(?:خارج\s*شو\s+از\s+|برو\s*بیرون\s+از\s+)(?:گروه\s+|چت\s+)?(.+?)\s*$",
    r"(?:leave|exit|quit)\s+(?:from\s+)?(?:the\s+)?(?:group\s+|chat\s+)?(.+?)\s*$",
    r"(?:remove\s+yourself\s+from|get\s+out\s+of)\s+(?:the\s+)?(?:group\s+|chat\s+)?(.+?)\s*$",
)

_BAN_RES = (
    r"^(?:گروه\s+|چت\s+)?(.+?)\s+(?:رو|را)\s+(بن|مسدود)\s*کن\s*$",
    r"^بن\s*کن\s+(?:گروه\s+|چت\s+)?(.+?)\s*$",
    r"^مسدود\s*کن\s+(?:گروه\s+|چت\s+)?(.+?)\s*$",
    r"^ban\s+(?:the\s+)?(?:group\s+|chat\s+)?(.+?)\s*$",
)


def _normalize(text: str) -> str:
    try:
        t = str(text or "")
    except Exception:
        return ""
    t = t.replace("‌", " ")  # ZWNJ -> space (user keyboards vary)
    t = re.sub(r"[@#]", " ", t)
    for name in _CALL_NAMES:
        t = re.sub(rf"^{re.escape(name)}([\s:,!؟?\-–—]+|$)", " ", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"[`*_~]+", " ", t)
    t = re.sub(r"[\s،,:؛!?.؟\"'()\[\]]+", " ", t).strip().lower()
    return re.sub(r"\s+", " ", t)


def _clean_target(raw: str) -> str:
    try:
        t = str(raw or "").strip().strip("`\"'").strip()
    except Exception:
        return ""
    t = re.sub(r"\s+", " ", t)
    return t[:100]


async def try_admin_intent_async(user_text: str, caller_id: int, current_chat_id=None):
    """Execute the admin's intent from natural text. Returns reply or None."""
    try:
        if int(caller_id or 0) != int(ADMIN_ID):
            return None
    except Exception:
        return None
    norm = _normalize(user_text)
    if not norm:
        return None

    # 1) List groups (exact phrases only — never guess).
    if norm in _LIST_PHRASES:
        try:
            from src.tools.admin import group_manager as _gm
            return await _gm.list_joined_groups_tool(caller_id=int(ADMIN_ID))
        except Exception as e:
            logger.warning(f"intent list-groups failed: {e}")
            return None

    # 2) Quota note (admin is unlimited; users have /limit).
    if norm in _QUOTA_PHRASES:
        try:
            from src.core.i18n import t as _t
            return _t("fa", "limit_admin")
        except Exception:
            return None

    # 3) Leave a group (single explicit target only).
    for pat in _LEAVE_RES:
        try:
            m = re.search(pat, norm, flags=re.IGNORECASE)
        except Exception:
            continue
        if not m:
            continue
        target = _clean_target(m.group(1))
        if not target:
            continue
        if target in _HERE_WORDS and current_chat_id:
            target = str(int(current_chat_id))
        if target in _VAGUE_WORDS or (len(target) < 2 and not target.lstrip("-").isdigit()):
            return _CLARIFY
        try:
            from src.tools.admin import group_manager as _gm
            return await _gm.leave_group_by_admin_tool(chat_identifier=target, caller_id=int(ADMIN_ID))
        except Exception as e:
            logger.warning(f"intent leave failed: {e}")
            return None

    # 4) Ban a group (single explicit target only).
    for pat in _BAN_RES:
        try:
            m = re.search(pat, norm, flags=re.IGNORECASE)
        except Exception:
            continue
        if not m:
            continue
        target = _clean_target(m.group(1))
        if not target:
            continue
        if target in _HERE_WORDS and current_chat_id:
            target = str(int(current_chat_id))
        if target in _VAGUE_WORDS or (len(target) < 2 and not target.lstrip("-").isdigit()):
            return _CLARIFY
        try:
            from src.tools.admin import group_manager as _gm
            return await _gm.ban_group_by_name_or_id_tool(group_name=target, caller_id=int(ADMIN_ID))
        except Exception as e:
            logger.warning(f"intent ban failed: {e}")
            return None

    return None
