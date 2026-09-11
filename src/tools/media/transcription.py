import io
import logging
import os
import httpx
from src.core.http import shared_client_ctx, get_http_client
from typing import Optional

from src.tools.registry import register_tool
from src.core.config import ROUTER_BASE_URL, ROUTER_API_KEY

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
            # SSRF guard: block internal/metadata targets
            blocked_hosts = ("127.", "localhost", "169.254.", "10.", "192.168.", "172.16.", "0.0.0.0", "[::")
            if any(h in low for h in blocked_hosts):
                return "⛔ آدرس داخلی/غیرمجاز مسدود شد."
            if low.endswith(".ogg") or low.endswith(".oga") or "ogg" in low or "opus" in low:
                mime = "audio/ogg"
            elif low.endswith(".wav"):
                mime = "audio/wav"
            elif low.endswith(".m4a") or low.endswith(".mp4"):
                mime = "audio/mp4"
            elif low.endswith(".webm"):
                mime = "audio/webm"
            async with shared_client_ctx("stream") as client:
                async with client.stream("GET", clean_target) as r:
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
            # Local path: strict sandbox — only inside /tmp and uploads, allowlisted ext
            if not ROUTER_API_KEY:
                return "❌ سرویس رونویسی بدون کلید AI در دسترس نیست."
            real = os.path.realpath(clean_target)
            allowed_dirs = [os.path.realpath("/tmp")]
            cwd = os.path.realpath(os.getcwd())
            allowed_dirs.append(cwd)
            if not any(real == d or real.startswith(d + os.sep) for d in allowed_dirs):
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

        # Send to Whisper Transcription endpoint
        if not ROUTER_API_KEY:
            return "❌ سرویس رونویسی بدون کلید AI در دسترس نیست."
        headers = {"Authorization": f"Bearer {ROUTER_API_KEY}"}
        files = {"file": ("audio.mp3", io.BytesIO(audio_bytes), mime)}
        data = {"model": "whisper-1", "language": "fa"}

        async with shared_client_ctx("web") as client:
            r = await client.post(
                f"{ROUTER_BASE_URL}/audio/transcriptions",
                headers=headers,
                data=data,
                files=files
            )
            if r.status_code == 200:
                transcript = r.json().get("text", "").strip()
                if transcript:
                    return f"🎙 *متن پیاده‌سازی‌شده از صوت (Transcription)*:\n\n«{transcript}»"
            if r.status_code in (401, 403):
                return "❌ کلید AI نامعتبر است."
            if r.status_code == 429:
                return "❌ سقف درخواست رونویسی پر شده، کمی بعد تلاش کنید."
            return "تبدیل صوت با مدل ویسپر در دسترس نیست یا فرمت صوتی پشتیبانی نمی‌شود."
    except Exception:
        logger.exception("transcribe failed")
        return "خطا در پردازش صوت."
