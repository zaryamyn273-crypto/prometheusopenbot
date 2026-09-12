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
    "my quota", "my limit",
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


_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def fa_digits_to_latin(s: object) -> str:
    """Persian/Arabic-Indic digits -> Latin (users type ۱۲۳ as well as 123)."""
    try:
        return str(s or "").translate(_FA_DIGITS)
    except Exception:
        return ""


def _strip_object_marker(t: str) -> str:
    try:
        return re.sub(r"\s+(رو|را)$", "", str(t or "").strip())
    except Exception:
        return str(t or "").strip()


async def _resolve_quota_target(target: str):
    """(uid, display_name) or (None, None) when the user is unresolvable."""
    try:
        from src.core import database as _db
        clean = _strip_object_marker(fa_digits_to_latin(target))
        if not clean:
            return None, None
        uid, uname = await _db.resolve_target_identifier(clean)
        if not uid:
            return None, None
        return int(uid), (f"@{uname}" if uname else f"user {uid}")
    except Exception:
        return None, None


# Set / adjust / clear a user's daily quota (admin only). Signed numbers
# adjust, plain numbers set absolute. Targets: numeric ID, @username, name.
_QUOTA_SET_RES = (
    r"سهمیه\s+(.+?)\s+(?:رو|را)?\s*(?:بکن|کن|بذار|بشه)\s*(\d+)\s*$",
    r"set\s+(?:the\s+)?quota\s+(?:for\s+|of\s+)?(.+?)\s+(?:to\s+|=\s*)?(\d+)\s*$",
    r"set\s+(.+?)(?:'s)?\s+quota\s+(?:to\s+)?(\d+)\s*$",
)
_QUOTA_ADJ_SIGNED_RES = (
    r"سهمیه\s+(.+?)\s*(?:رو|را)?\s*([+\-]\d+)\s*(?:تا\s*)?(?:زیاد|بیشتر|اضافه|کم|کمتر)?\s*(?:کن|بکن)?\s*$",
    r"(.+?)(?:'s)?\s+quota\s*([+\-]\d+)\s*$",
)
_QUOTA_ADJ_VERB_FA_RES = (
    r"سهمیه\s+(.+?)\s+(?:رو|را)?\s*(\d+)\s*تا\s*(زیاد|بیشتر|اضافه|کم|کمتر)\s*(?:کن|بکن)?\s*$",
)
_QUOTA_ADJ_VERB_EN_RES = (
    r"(increase|decrease)\s+(.+?)(?:'s)?\s+quota\s+by\s+(\d+)\s*$",
)
_QUOTA_CLEAR_RES = (
    r"سهمیه\s+(.+?)\s*(?:رو|را)?\s*(?:حذف|پاک|ریست|پیش.?فرض)\s*کن\s*$",
    r"(?:clear|reset|remove)\s+(.+?)(?:'s)?\s+quota\s*$",
)


async def try_admin_intent_async(user_text: str, caller_id: int, current_chat_id=None):
    """Execute the admin's intent from natural text. Returns reply or None."""
    try:
        if int(caller_id or 0) != int(ADMIN_ID):
            return None
    except Exception:
        return None
    norm = _normalize(fa_digits_to_latin(user_text))
    if not norm:
        return None
    try:
        from src.core.i18n import t as _t, detect_lang as _dl
        _d = _dl(user_text)
        _nlang = _d if _d in ("fa", "en") else "fa"
    except Exception:
        from src.core.i18n import t as _t
        _nlang = "fa"

    # 1) List groups (exact phrases only — never guess).
    if norm in _LIST_PHRASES:
        try:
            from src.tools.admin import group_manager as _gm
            return await _gm.list_joined_groups_tool(caller_id=int(ADMIN_ID))
        except Exception as e:
            logger.warning(f"intent list-groups failed: {e}")
            return None

    # 2) Quota note (admin is unlimited; users have /limit).
    # EXACT phrases only: asking about anyone/anything else's quota
    # ("سهمیه بنزین چقدره؟") must NEVER show the user's bot quota.
    if norm in _QUOTA_PHRASES:
        try:
            return _t(_nlang, "limit_admin")
        except Exception:
            return None

    # 2b) Set a user's daily quota (admin raises/lowers per-user limits).
    for pat in _QUOTA_SET_RES:
        try:
            m = re.search(pat, norm, flags=re.IGNORECASE)
        except Exception:
            continue
        if not m:
            continue
        target = _strip_object_marker(_clean_target(m.group(1)))
        try:
            n = int(m.group(2))
        except Exception:
            continue
        uid, name = await _resolve_quota_target(target)
        if not uid:
            return _t(_nlang, "quota_need_target")
        try:
            from src.core import database as _db
            if await _db.set_user_quota_async(uid, n):
                return _t(_nlang, "quota_set", name=name, uid=uid, limit=n)
            return _t(_nlang, "quota_invalid")
        except Exception as e:
            logger.warning(f"intent quota-set failed: {e}")
            return None

    # 2c) Adjust a user's quota relatively (+N / -N / verb-based).
    for pat in _QUOTA_ADJ_SIGNED_RES:
        try:
            m = re.search(pat, norm, flags=re.IGNORECASE)
        except Exception:
            continue
        if not m:
            continue
        target = _strip_object_marker(_clean_target(m.group(1)))
        try:
            delta = int(m.group(2))
        except Exception:
            continue
        if delta == 0:
            continue
        uid, name = await _resolve_quota_target(target)
        if not uid:
            return _t(_nlang, "quota_need_target")
        try:
            from src.core import database as _db
            new_n = await _db.adjust_user_quota_async(uid, delta)
            if new_n is not None:
                return _t(_nlang, "quota_adjusted", name=name, uid=uid, delta=delta, limit=new_n)
            return _t(_nlang, "quota_invalid")
        except Exception as e:
            logger.warning(f"intent quota-adjust failed: {e}")
            return None
    for pat in _QUOTA_ADJ_VERB_FA_RES:
        try:
            m = re.search(pat, norm, flags=re.IGNORECASE)
        except Exception:
            continue
        if not m:
            continue
        target = _strip_object_marker(_clean_target(m.group(1)))
        try:
            n = int(m.group(2))
        except Exception:
            continue
        delta = n if m.group(3) in ("زیاد", "بیشتر", "اضافه") else -n
        uid, name = await _resolve_quota_target(target)
        if not uid:
            return _t(_nlang, "quota_need_target")
        try:
            from src.core import database as _db
            new_n = await _db.adjust_user_quota_async(uid, delta)
            if new_n is not None:
                return _t(_nlang, "quota_adjusted", name=name, uid=uid, delta=delta, limit=new_n)
            return _t(_nlang, "quota_invalid")
        except Exception as e:
            logger.warning(f"intent quota-adjust failed: {e}")
            return None
    for pat in _QUOTA_ADJ_VERB_EN_RES:
        try:
            m = re.search(pat, norm, flags=re.IGNORECASE)
        except Exception:
            continue
        if not m:
            continue
        target = _strip_object_marker(_clean_target(m.group(2)))
        try:
            n = int(m.group(3))
        except Exception:
            continue
        delta = n if m.group(1) == "increase" else -n
        uid, name = await _resolve_quota_target(target)
        if not uid:
            return _t(_nlang, "quota_need_target")
        try:
            from src.core import database as _db
            new_n = await _db.adjust_user_quota_async(uid, delta)
            if new_n is not None:
                return _t(_nlang, "quota_adjusted", name=name, uid=uid, delta=delta, limit=new_n)
            return _t(_nlang, "quota_invalid")
        except Exception as e:
            logger.warning(f"intent quota-adjust failed: {e}")
            return None

    # 2d) Clear a user's override (back to global default).
    for pat in _QUOTA_CLEAR_RES:
        try:
            m = re.search(pat, norm, flags=re.IGNORECASE)
        except Exception:
            continue
        if not m:
            continue
        target = _strip_object_marker(_clean_target(m.group(1)))
        uid, name = await _resolve_quota_target(target)
        if not uid:
            return _t(_nlang, "quota_need_target")
        try:
            from src.core import database as _db
            await _db.clear_user_quota_async(uid)
            return _t(_nlang, "quota_cleared", name=name, uid=uid, limit=_db.get_user_limit(uid))
        except Exception as e:
            logger.warning(f"intent quota-clear failed: {e}")
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
