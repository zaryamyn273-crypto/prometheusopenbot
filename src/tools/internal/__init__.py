"""Internal background/self-use tools for the bot itself (category=internal).

These tools are NEVER shown to the AI model — they are hidden from schemas
but executable via execute_registered_tool for self-diagnosis, caching,
query normalization, fallback orchestration and output compaction.
"""
import logging
import re
import time
from typing import Any, Dict, Optional

from src.tools.registry import register_tool

logger = logging.getLogger(__name__)

_RATE_BUCKETS: Dict[int, Any] = {}


@register_tool(
    name="bot_self_diagnose",
    description="SYSTEM ONLY: background self-diagnosis of cache, DB and queue health",
    category="internal",
)
async def bot_self_diagnose() -> str:
    """
    :param dummy: unused
    """
    try:
        from src.core import database
        h = await database.get_cache_health_async()
        return (
            "🤖 *خودعیبیابی پس‌زمینه ربات*:\n"
            f"• *کلیدهای L1*: `{h.get('l1_keys')}`\n"
            f"• *مدار KV باز*: `{h.get('kv_circuit_open')}`\n"
            f"• *خطای KV*: `{h.get('kv_last_cloud_error')}`\n"
            f"• *عمق صف D1*: `{h.get('d1_queue_depth')}`\n"
            f"• *ورکر D1 زنده*: `{h.get('d1_batch_worker_alive')}`\n"
            f"• *دسترسی D1*: `{h.get('d1_reachable')}`"
        )
    except Exception as e:
        return f"خطا در خودعیبیابی: {e}"


@register_tool(
    name="bot_tool_health_probe",
    description="SYSTEM ONLY: probe whether a named tool exists and its category",
    category="internal",
)
async def bot_tool_health_probe(tool_name: str = "") -> str:
    """
    :param tool_name: نام ابزار برای بررسی سلامت
    """
    try:
        from src.tools.registry import REGISTRY
        clean = (tool_name or "").strip()
        if clean:
            meta = REGISTRY.get(clean)
            if meta:
                return f"✅ ابزار `{clean}` سالم است (دسته `{meta.get('category')}`)."
            return f"❌ ابزار `{clean}` در رجیستری یافت نشد."
        cats: Dict[str, int] = {}
        for meta in REGISTRY.values():
            cats[meta.get("category", "?")] = cats.get(meta.get("category", "?"), 0) + 1
        total = sum(cats.values())
        detail = ", ".join(f"{k}:{v}" for k, v in sorted(cats.items()))
        return f"🧰 *سلامت ابزارها*: مجموع `{total}` — {detail}"
    except Exception as e:
        return f"خطا در بررسی سلامت ابزار: {e}"


@register_tool(
    name="bot_smart_cache_get",
    description="SYSTEM ONLY: fast smart-cache read with SMARTBOT_ prefix",
    category="internal",
)
async def bot_smart_cache_get(key: str = "") -> str:
    """
    :param key: کلید کش هوشمند
    """
    try:
        from src.core import database
        clean = (key or "").strip().replace(" ", "_")
        if not clean:
            return "کلید کش خالی است."
        val = await database.kv_get_cache_async(f"SMARTBOT_{clean}")
        return val if val is not None else "هیچ داده‌ای در کش هوشمند یافت نشد."
    except Exception as e:
        return f"خطا در خواندن کش هوشمند: {e}"


@register_tool(
    name="bot_smart_cache_put",
    description="SYSTEM ONLY: fast smart-cache write with SMARTBOT_ prefix",
    category="internal",
)
async def bot_smart_cache_put(key: str = "", value: str = "") -> str:
    """
    :param key: کلید کش هوشمند
    :param value: مقدار متنی برای ذخیره
    """
    try:
        from src.core import database
        clean = (key or "").strip().replace(" ", "_")
        if not clean:
            return "کلید کش خالی است."
        await database.kv_set_cache_async(f"SMARTBOT_{clean}", str(value or ""), expiration_ttl=600)
        return f"✅ در کش هوشمند ذخیره شد: `{clean}`"
    except Exception as e:
        return f"خطا در نوشتن کش هوشمند: {e}"


_PINGPONG_WORDS = {
    "سلام", "درود", "هی", "های", "hello", "hi", "hey", "salam", "drood",
    "خوبی", "چطوری", "چه خبر", "خسته نباشی", "ممنون", "مرسی",
    "باشه", "اوکی", "ok", "okay", "بله", "نه", "آره", "اره",
    "چشم", "حله", "دمت گرم", "حاجی",
}


@register_tool(
    name="bot_query_rewriter",
    description="SYSTEM ONLY: normalize Persian query (spacing, ye/ke, duplicates, ping/pong)",
    category="internal",
)
def bot_query_rewriter(query: str = "") -> str:
    """
    :param query: عبارت ورودی کاربر برای نرمال‌سازی
    """
    try:
        q = (query or "").strip()
        q = q.replace("\u064a", "\u06cc").replace("\u0643", "\u06a9")
        q = re.sub(r"\s+", " ", q)
        seen = set()
        out_words = []
        for w in q.split(" "):
            lw = w.lower()
            if lw not in seen:
                seen.add(lw)
                out_words.append(w)
        norm = " ".join(out_words).strip()
        # Ping/pong marker: pure social chatter — downstream skips tools entirely.
        if norm and norm.lower() in _PINGPONG_WORDS:
            return f"__PINGPONG__ {norm}"
        return norm or "عبارت ورودی خالی است."
    except Exception as e:
        return f"خطا در بازنویسی کوئری: {e}"


@register_tool(
    name="bot_intent_splitter",
    description="SYSTEM ONLY: split multi-intent prompt into numbered intents",
    category="internal",
)
def bot_intent_splitter(prompt: str = "") -> str:
    """
    :param prompt: پیام چندمنظوره کاربر
    """
    try:
        p = (prompt or "").strip()
        if not p:
            return "پیام ورودی خالی است."
        # Conjunction-aware split: و / then / «هم» join independent intents.
        p2 = re.sub(r"\s+(و|بعدش|بعد|then|and)\s+", "\n", p)
        parts = [x.strip() for x in re.split(r"[\n\u060c,;؛؟?]+", p2) if x.strip()]
        if not parts:
            return p
        # Numbered + tagged: each intent carries its guessed tool family.
        try:
            tagged = []
            for i, part in enumerate(parts[:8]):
                fam = bot_tool_picker(part)
                tagged.append(f"{i + 1}. [{fam}] {part}")
            return "\n".join(tagged)
        except Exception:
            return "\n".join(f"{i + 1}. {x}" for i, x in enumerate(parts[:8]))
    except Exception as e:
        return f"خطا در تفکیک نیت: {e}"


@register_tool(
    name="bot_tool_picker",
    description="SYSTEM ONLY: keyword mapping from query to best tool names",
    category="internal",
)
def bot_tool_picker(query: str = "") -> str:
    """
    :param query: عبارت کاربر برای انتخاب ابزار
    """
    try:
        from src.tools.registry import CATEGORY_KEYWORDS as _CKW
        q = (query or "").lower()
        # Score every category by keyword hits, then map top categories to
        # their flagship tool. Mirrors get_smart_tools_for_prompt so the two
        # brains never disagree.
        _FLAGSHIP = {
            "financial": "get_price", "crypto": "get_price",
            "weather": "get_weather", "media": "download_music_track",
            "search": "web_search", "network": "check_website_status",
            "security": "generate_hash_digest", "scientific": "calculate_math_expression",
            "github": "github_search_repositories", "admin": "admin_system_diagnostics",
            "files": "create_and_upload_file", "math": "calculate_math_expression",
            "time": "get_current_datetime_info", "database": "search_conversation_history",
            "dev": "reddit_search",
        }
        scored = []
        for _cat, _kws in _CKW.items():
            if _cat in ("internal", "github_legacy_placeholder"):
                continue
            _hits = 0
            for _kw in _kws:
                # Mirror _kw_hit_compiled exactly: word boundaries ONLY for
                # short Latin tokens; everything else is substring match.
                if re.match(r"^[a-z]{1,4}$", _kw):
                    if re.search(rf"(?<![a-z]){re.escape(_kw)}(?![a-z])", q):
                        _hits += 1
                elif _kw in q:
                    _hits += 1
            if _hits:
                scored.append((_hits, _cat))
        scored.sort(reverse=True)
        picks = []
        for _hits, _cat in scored[:3]:
            _tool = _FLAGSHIP.get(_cat)
            if _tool and _tool not in picks:
                picks.append(_tool)
        # Same implicit-verb boost as the registry: bare send/play verbs +
        # any Latin music token mean music even without Persian anchors.
        if any(v in q for v in ("play", "پلی")) or any(
            tok in q for tok in ("hello", "song", "music", "audio", "mp3")
        ):
            if "download_music_track" not in picks:
                picks.insert(0, "download_music_track")
        if not picks:
            picks.append("web_search")
        return ", ".join(picks)
    except Exception as e:
        return f"خطا در انتخاب ابزار: {e}"


@register_tool(
    name="bot_fallback_search",
    description="SYSTEM ONLY: multi-layer web fallback search",
    category="internal",
)
async def bot_fallback_search(query: str = "") -> str:
    """
    :param query: عبارت جستجو برای موتور پشتیبان
    """
    try:
        from src.tools import web_network as _web
        clean = (query or "").strip()
        if not clean:
            return "عبارت جستجو خالی است."
        try:
            r1 = await _web.web_search(clean, max_results=5)
            if r1 and "\u06cc\u0627\u0641\u062a \u0646\u0634\u062f" not in r1 and len(r1) > 50:
                return r1
        except Exception:
            pass
        try:
            r2 = await _web.deep_search_and_read(clean, max_pages=2)
            if r2 and "\u06cc\u0627\u0641\u062a \u0646\u0634\u062f" not in r2 and len(r2) > 50:
                return r2
        except Exception:
            pass
        try:
            r3 = await _web.live_news(clean)
            if r3 and len(r3) > 30:
                return r3
        except Exception:
            pass
        return f"اطلاعات تکمیلی برای «{clean}» در دسترس قرار نگرفت."
    except Exception as e:
        return f"خطا در جستجوی پشتیبان: {e}"


@register_tool(
    name="bot_news_fallback",
    description="SYSTEM ONLY: news fallback via live_news then web_search",
    category="internal",
)
async def bot_news_fallback(topic: str = "general") -> str:
    """
    :param topic: موضوع خبری
    """
    try:
        from src.tools import web_network as _web
        clean = (topic or "general").strip()
        try:
            r1 = await _web.live_news(clean)
            if r1 and "\u06cc\u0627\u0641\u062a \u0646\u0634\u062f" not in r1 and len(r1) > 50:
                return r1
        except Exception:
            pass
        try:
            r2 = await _web.web_search(f"\u0627\u062e\u0628\u0627\u0631 {clean}", max_results=5)
            if r2 and len(r2) > 50:
                return r2
        except Exception:
            pass
        return f"اخبار زنده برای «{clean}» در دسترس نیست."
    except Exception as e:
        return f"خطا در اخبار پشتیبان: {e}"


@register_tool(
    name="bot_music_fallback",
    description="SYSTEM ONLY: music fallback via YouTube 320kbps extraction",
    category="internal",
)
async def bot_music_fallback(query: str = "") -> Any:
    """
    :param query: نام آهنگ یا خواننده
    """
    try:
        from src.tools import media as _media
        clean = (query or "").strip()
        if not clean:
            return "لطفاً نام موزیک را مشخص فرمایید."
        try:
            res = await _media.download_music_track(clean)
            if isinstance(res, dict) and res.get("type") in ("audio", "audio_bytes"):
                return res
        except Exception:
            pass
        try:
            from src.tools.media import youtube_audio as _yt
            from src.tools.media import _tokenize_fa
            yt_res = await _yt.youtube_download_full_track(clean, _tokenize_fa(clean), None)
            if yt_res and yt_res.get("audio_bytes"):
                return {
                    "type": "audio_bytes",
                    "bytes": yt_res["audio_bytes"],
                    "title": yt_res.get("title", clean),
                    "performer": yt_res.get("performer", "\u0647\u0646\u0631\u0645\u0646\u062f"),
                    "thumb": yt_res.get("cover", ""),
                    "duration": yt_res.get("duration_sec", 0),
                    "caption": f"🎵 *{yt_res.get('title', clean)}* — *{yt_res.get('performer', '')}*",
                }
        except Exception as e:
            logger.debug(f"music fallback yt error: {e}")
        return f"نسخه صوتی کامل برای «{clean}» در پایگاه‌های موسیقی یافت نشد."
    except Exception as e:
        return f"خطا در موزیک پشتیبان: {e}"


@register_tool(
    name="bot_lyrics_fallback",
    description="SYSTEM ONLY: lyrics fallback via web search",
    category="internal",
)
async def bot_lyrics_fallback(song_title: str = "") -> str:
    """
    :param song_title: عنوان آهنگ برای متن ترانه
    """
    try:
        from src.tools import media as _media
        clean = (song_title or "").strip()
        if not clean:
            return "عنوان آهنگ خالی است."
        try:
            r1 = await _media.get_song_lyrics(clean)
            if isinstance(r1, str) and "\u06cc\u0627\u0641\u062a \u0646\u0634\u062f" not in r1:
                return r1
            if isinstance(r1, dict):
                return r1
        except Exception:
            pass
        try:
            from src.tools import web_network as _web
            r2 = await _web.web_search(f"\u0645\u062a\u0646 \u0622\u0647\u0646\u06af {clean}", max_results=4)
            if r2 and len(r2) > 50:
                return f"📜 *\u0645\u062a\u0646 \u062a\u0631\u0627\u0646\u0647 (\u0627\u0632 \u0648\u0628)* «{clean}»:\n\n{r2}"
        except Exception:
            pass
        return f"متن ترانه برای «{clean}» یافت نشد."
    except Exception as e:
        return f"خطا در لیریکس پشتیبان: {e}"


@register_tool(
    name="bot_file_fallback_publish",
    description="SYSTEM ONLY: publish long text via telegraph with file fallback hint",
    category="internal",
)
async def bot_file_fallback_publish(title: str = "", content: str = "") -> str:
    """
    :param title: عنوان مقاله
    :param content: متن کامل مقاله
    """
    try:
        from src.tools import media as _media
        t = (title or "\u0645\u0642\u0627\u0644\u0647 \u067e\u0631\u0648\u0645\u062a\u0647").strip()
        c = (content or "").strip()
        if not c:
            return "متن مقاله خالی است."
        try:
            r1 = await _media.publish_telegraph_article(t, c)
            if r1 and "telegra.ph" in r1:
                return r1
        except Exception:
            pass
        return f"📝 *{t}*:\n\n{c[:2500]}"
    except Exception as e:
        return f"خطا در انتشار پشتیبان: {e}"


@register_tool(
    name="bot_qr_fallback",
    description="SYSTEM ONLY: QR code generation fallback",
    category="internal",
)
def bot_qr_fallback(text_or_url: str = "") -> str:
    """
    :param text_or_url: متن یا آدرس برای QR
    """
    try:
        from src.tools import media as _media
        return _media.generate_qr_code_tool(text_or_url or "https://t.me")
    except Exception:
        try:
            import urllib.parse
            raw = (text_or_url or "https://t.me").strip()
            encoded = urllib.parse.quote(raw)
            qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=500x500&data={encoded}"
            return f"🔳 *بارکد دوبعدی QR Code*:\n\n• *داده*: `{raw}`\n\n🔗 [مشاهده QR]({qr_url})"
        except Exception as e:
            return f"خطا در تولید QR پشتیبان: {e}"


@register_tool(
    name="bot_d1_remember",
    description="SYSTEM ONLY: persist key/value into D1 custom records",
    category="internal",
)
async def bot_d1_remember(key: str = "", value: str = "", category: str = "general") -> str:
    """
    :param key: کلید یکتا برای ذخیره
    :param value: مقدار متنی برای ذخیره ابدی
    :param category: دسته‌بندی اختیاری
    """
    try:
        from src.core import database
        clean = (key or "").strip()
        if not clean:
            return "کلید داده خالی است."
        ok = await database.store_custom_record_d1(clean, str(value or ""), category or "general")
        return f"💾 در حافظه دائمی ذخیره شد: `{clean}`" if ok else "خطا در ذخیره‌سازی D1."
    except Exception as e:
        return f"خطا در ذخیره D1: {e}"


@register_tool(
    name="bot_d1_recall",
    description="SYSTEM ONLY: recall key/value from D1 custom records",
    category="internal",
)
async def bot_d1_recall(key: str = "") -> str:
    """
    :param key: کلید داده ذخیره‌شده
    """
    try:
        from src.core import database
        clean = (key or "").strip()
        if not clean:
            return "کلید داده خالی است."
        val = await database.retrieve_custom_record_d1(clean)
        return f"📦 `{clean}`:\n\n{val}" if val is not None else f"هیچ رکوردی با کلید `{clean}` یافت نشد."
    except Exception as e:
        return f"خطا در بازیابی D1: {e}"


@register_tool(
    name="bot_history_recall",
    description="SYSTEM ONLY: recall group chat history from D1",
    category="internal",
)
async def bot_history_recall(query: str = "", chat_id: int = 0) -> str:
    """
    :param query: عبارت جستجو در تاریخچه
    :param chat_id: شناسه عددی گروه
    """
    try:
        from src.core import database
        clean = (query or "").strip()
        if not clean:
            return "عبارت جستجو خالی است."
        results = await database.search_group_memory(int(chat_id or 0), clean, limit=6)
        if results:
            lines = [f"🔍 *سوابق «{clean}»*:\n"]
            for r in results:
                lines.append(f"• {str(r.get('content', ''))[:160]}")
            return "\n".join(lines)
        return f"هیچ پیامی حاوی «{clean}» در تاریخچه یافت نشد."
    except Exception as e:
        return f"خطا در بازیابی تاریخچه: {e}"


@register_tool(
    name="bot_rate_guard",
    description="SYSTEM ONLY: in-memory per-user rate guard (60s window)",
    category="internal",
)
def bot_rate_guard(user_id: int = 0, limit: int = 8) -> str:
    """
    :param user_id: شناسه عددی کاربر
    :param limit: سقف پیام در دقیقه
    """
    try:
        now = time.time()
        uid = int(user_id or 0)
        lim = max(1, int(limit or 8))
        bucket = _RATE_BUCKETS.get(uid)
        if not bucket or now > bucket.get("reset", 0):
            _RATE_BUCKETS[uid] = {"count": 1, "reset": now + 60.0}
            return "ok"
        bucket["count"] = bucket.get("count", 0) + 1
        if bucket["count"] > lim:
            return "limited"
        return "ok"
    except Exception:
        return "ok"


@register_tool(
    name="bot_output_compactor",
    description="SYSTEM ONLY: compact long tool outputs preserving head and tail",
    category="internal",
)
def bot_output_compactor(text: str = "", max_chars: int = 3000) -> str:
    """
    :param text: متن بلند خروجی ابزار
    :param max_chars: حداکثر طول مجاز
    """
    try:
        t = str(text or "")
        m = max(500, int(max_chars or 3000))
        if len(t) <= m:
            return t
        head = m * 2 // 3
        tail = m - head - 40
        return t[:head] + f"\n\n… *[ادامه حذف شد: {len(t) - m} نویسه]* …\n\n" + t[-tail:]
    except Exception as e:
        return f"خطا در فشرده‌سازی خروجی: {e}"


@register_tool(
    name="bot_prompt_token_saver",
    description="SYSTEM ONLY: squeeze whitespace to save inference tokens",
    category="internal",
)
def bot_prompt_token_saver(prompt: str = "", max_chars: int = 600) -> str:
    """
    :param prompt: پرامپت ورودی برای فشرده‌سازی
    :param max_chars: حداکثر طول مجاز
    """
    try:
        p = re.sub(r"\s+", " ", str(prompt or "")).strip()
        m = max(100, int(max_chars or 600))
        return p[:m] if len(p) > m else p
    except Exception:
        return str(prompt or "")[:600]


@register_tool(
    name="bot_alias_resolver",
    description="SYSTEM ONLY: fuzzy-match mistyped tool name to registry",
    category="internal",
)
async def bot_alias_resolver(name: str = "") -> str:
    """
    :param name: نام ناقص یا اشتباه ابزار
    """
    try:
        import difflib
        from src.tools.registry import REGISTRY
        clean = (name or "").strip()
        if not clean:
            return "نام ابزار خالی است."
        if clean in REGISTRY:
            return clean
        matches = difflib.get_close_matches(clean, list(REGISTRY.keys()), n=1, cutoff=0.4)
        return matches[0] if matches else ""
    except Exception as e:
        return f"خطا در تطبیق نام ابزار: {e}"
