import io
import logging
import os
import urllib.parse
from src.core.http import shared_client_ctx

from src.tools.registry import register_tool
from src.core import config as _config

logger = logging.getLogger(__name__)

_MAX_AUDIO_BYTES = 25 * 1024 * 1024
_ALLOWED_AUDIO_EXT = (".mp3", ".ogg", ".oga", ".wav", ".m4a", ".mp4", ".mpeg", ".mpga", ".webm")

@register_tool(
    name="transcribe_audio_tool",
    description="تبدیل فایل‌های صوتی، وویس و پادکست به متن دقیق فارسی و انگلیسی (Speech to Text)",
    category="media"
)
async def transcribe_audio_tool(audio_url_or_path: str) -> str:
    """
    :param audio_url_or_path: لینک مستقیم فایل صوتی یا وویس تلگرام
    """
    clean_target = (audio_url_or_path or "").strip()
    if not clean_target:
        return "آدرس فایل صوتی خالی است."

    try:
        # Download audio stream (hardened: no arbitrary local paths, size cap)
        audio_bytes: bytes = b""
        mime = "audio/mpeg"
        low = clean_target.lower()
        if low.startswith("http://") or low.startswith("https://"):
            # Robust SSRF guard: full DNS resolution check & hop-by-hop redirect verification
            try:
                from src.utils.net_guard import assert_public_url as _assert_url, safe_stream_get as _safe_stream
                clean_target = _assert_url(clean_target)
            except Exception as e:
                return f"⛔ آدرس صوتی نامعتبر یا غیرمجاز است: {str(e)}"
            if low.endswith(".ogg") or low.endswith(".oga") or "ogg" in low or "opus" in low:
                mime = "audio/ogg"
            elif low.endswith(".wav"):
                mime = "audio/wav"
            elif low.endswith(".m4a") or low.endswith(".mp4"):
                mime = "audio/mp4"
            elif low.endswith(".webm"):
                mime = "audio/webm"
            async with shared_client_ctx("stream") as client:
                async with _safe_stream(client, clean_target) as r:
                    if r.status_code != 200:
                        return f"خطا در دانلود فایل صوتی (کد: {r.status_code})"
                    chunks = []
                    total = 0
                    async for chunk in r.aiter_bytes(65536):
                        total += len(chunk)
                        if total > _MAX_AUDIO_BYTES:
                            return "❌ حجم فایل صوتی بیش از سقف ۲۵MB است."
                        chunks.append(chunk)
                    audio_bytes = b"".join(chunks)
        else:
            # Local path: strict sandbox — only inside /tmp (Telegram voice
            # arrives in memory; nothing legit reads audio from the repo dir).
            if not (_config.ROUTER_API_KEY or "").strip():
                return "❌ سرویس رونویسی بدون کلید AI در دسترس نیست."
            real = os.path.realpath(clean_target)
            _tmp = os.path.realpath("/tmp")
            if not (real == _tmp or real.startswith(_tmp + os.sep)):
                return "⛔ دسترسی به این مسیر فایل مجاز نیست."
            if os.path.splitext(real)[1].lower() not in _ALLOWED_AUDIO_EXT:
                return "⛔ فرمت صوتی پشتیبانی نمی‌شود."
            try:
                if os.path.getsize(real) > _MAX_AUDIO_BYTES:
                    return "❌ حجم فایل صوتی بیش از سقف ۲۵MB است."
            except Exception:
                return "فایل صوتی یافت نشد."
            with open(real, "rb") as f:
                audio_bytes = f.read(_MAX_AUDIO_BYTES + 1)
                if len(audio_bytes) > _MAX_AUDIO_BYTES:
                    return "❌ حجم فایل صوتی بیش از سقف ۲۵MB است."
                if real.lower().endswith((".ogg", ".oga")):
                    mime = "audio/ogg"

        if not audio_bytes:
            return "فایل صوتی خالی است."

        _rkey = (_config.ROUTER_API_KEY or "").strip()
        if not _rkey:
            return "❌ سرویس رونویسی بدون کلید AI در دسترس نیست."

        from src.core.stt import transcribe_audio_bytes
        transcript = await transcribe_audio_bytes(
            raw_bytes=audio_bytes,
            mime_type=mime,
            filename=f"audio{os.path.splitext(clean_target)[1] or '.mp3'}"
        )
        if transcript:
            return f"🎙 *متن پیاده‌سازی‌شده از صوت (Transcription)*:\n\n«{transcript}»"

        return "تبدیل صوت با اختلال مواجه شد یا فایل فاقد گفتار واضح بود."
    except Exception:
        logger.exception("transcribe failed")
        return "خطا در پردازش صوت."
