import io
import logging
import httpx
from src.core.http import shared_client_ctx
from typing import Optional

from src.tools.registry import register_tool
from src.core.config import ROUTER_BASE_URL, ROUTER_API_KEY

logger = logging.getLogger(__name__)

@register_tool(
    name="transcribe_audio_tool",
    description="تبدیل فایل‌های صوتی، وویس و پادکست به متن دقیق فارسی و انگلیسی (Speech to Text)",
    category="media"
)
async def transcribe_audio_tool(audio_url_or_path: str) -> str:
    """
    :param audio_url_or_path: لینک مستقیم فایل صوتی یا وویس تلگرام
    """
    clean_target = audio_url_or_path.strip()
    if not clean_target:
        return "آدرس فایل صوتی خالی است."

    try:
        # Download audio stream
        async with shared_client_ctx("web") as client:
            if clean_target.startswith("http"):
                r = await client.get(clean_target)
                if r.status_code != 200:
                    return f"خطا در دانلود فایل صوتی (کد: {r.status_code})"
                audio_bytes = r.content
            else:
                with open(clean_target, "rb") as f:
                    audio_bytes = f.read()

        # Send to Whisper Transcription endpoint
        headers = {"Authorization": f"Bearer {ROUTER_API_KEY}"}
        files = {"file": ("audio.mp3", io.BytesIO(audio_bytes), "audio/mpeg")}
        data = {"model": "whisper-1"}

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
            return "تبدیل صوت با مدل ویسپر در دسترس نیست یا فرمت صوتی پشتیبانی نمی‌شود."
    except Exception as e:
        return f"خطا در پردازش صوت: {str(e)}"
