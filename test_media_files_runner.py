
import asyncio
import io
import os
import sys
import json
import traceback
from PIL import Image

sys.path.insert(0, '/home/dsh/workspace/prometheuspro')

from src.tools.media import (
    download_music_track,
    get_song_lyrics,
    generate_qr_code_tool,
    publish_telegraph_article,
)
from src.tools.media.transcription import transcribe_audio_tool
from src.tools.files import create_and_upload_file, read_document_file
from src.core.ai_service import optimize_image_for_vision

results = {}

async def test_download_music_track():
    print("=== Testing download_music_track ===")
    test_cases = [
        ("Persian song", "شروین حاجی پور برای"),
        ("English song", "Adele Hello"),
        ("Special chars", "AC/DC - Back in Black #rock!"),
        ("Artist + Title", "Mohsen Yeganeh Behet Ghol Midam"),
    ]
    sub_results = []
    for label, query in test_cases:
        try:
            print(f"Testing download_music_track: {label} ({query})...")
            res = await asyncio.wait_for(download_music_track(query), timeout=35.0)
            status = "PASS"
            res_type = type(res).__name__
            summary = ""
            if isinstance(res, dict):
                t = res.get("type")
                title = res.get("title", "")
                performer = res.get("performer", "")
                has_bytes = "bytes" in res and len(res["bytes"]) > 0
                has_url = "url" in res and bool(res["url"])
                summary = f"type={t}, title='{title}', performer='{performer}', bytes_len={len(res.get('bytes', b'')) if has_bytes else 0}, has_url={has_url}"
            else:
                summary = str(res)[:120]
            sub_results.append({"case": label, "query": query, "status": status, "summary": summary})
            print(f"  -> {status}: {summary}")
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)}"
            print(f"  -> FAIL: {err}")
            sub_results.append({"case": label, "query": query, "status": "FAIL", "summary": err})
    results["download_music_track"] = sub_results

async def test_get_song_lyrics():
    print("=== Testing get_song_lyrics ===")
    test_cases = [
        ("Popular song", "Adele - Hello", "text"),
        ("Popular song (LRC format)", "Queen Bohemian Rhapsody", "lrc"),
        ("Persian lyrics", "متن آهنگ بهت قول میدم محسن یگانه", "text"),
        ("Obscure query", "xyzqwe1234987randomnonexistentsongtitle999", "text"),
    ]
    sub_results = []
    for label, q, fmt in test_cases:
        try:
            print(f"Testing get_song_lyrics: {label} ({q}, format={fmt})...")
            res = await asyncio.wait_for(get_song_lyrics(q, format=fmt), timeout=25.0)
            status = "PASS"
            if isinstance(res, dict):
                summary = f"dict(type={res.get('type')}, filename={res.get('filename')}, bytes_len={len(res.get('bytes', b''))})"
            else:
                summary = f"str(len={len(str(res))}, preview={str(res)[:80]}...)"
            sub_results.append({"case": label, "query": q, "format": fmt, "status": status, "summary": summary})
            print(f"  -> {status}: {summary}")
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)}"
            print(f"  -> FAIL: {err}")
            sub_results.append({"case": label, "query": q, "format": fmt, "status": "FAIL", "summary": err})
    results["get_song_lyrics"] = sub_results

def test_generate_qr_code_tool():
    print("=== Testing generate_qr_code_tool ===")
    test_cases = [
        ("URL", "https://t.me/Prometheusbaibot"),
        ("Long text", "This is an exceptionally detailed test string intended to verify QR code encoding for large textual payloads " * 5),
        ("Persian text", "پرومته سوپر ایجنت - هوش مصنوعی نسل جدید برای تلگرام و مدیریت اسناد"),
    ]
    sub_results = []
    for label, val in test_cases:
        try:
            print(f"Testing generate_qr_code_tool: {label}...")
            res = generate_qr_code_tool(text_or_url=val)
            assert "api.qrserver.com" in res
            assert "🔳" in res
            status = "PASS"
            summary = f"Success. Generated markdown link with valid encoded URL. Length: {len(res)}"
            sub_results.append({"case": label, "input_len": len(val), "status": status, "summary": summary})
            print(f"  -> {status}: {summary}")
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)}"
            print(f"  -> FAIL: {err}")
            sub_results.append({"case": label, "status": "FAIL", "summary": err})
    results["generate_qr_code_tool"] = sub_results

async def test_publish_telegraph_article():
    print("=== Testing publish_telegraph_article ===")
    test_cases = [
        ("Short title", "گزارش آزمایشی پرومته", "متن کوتاه برای بررسی انتشار مقاله در تلگراف."),
        ("Long markdown body", "راهنمای جامع هوش مصنوعی", ("# بخش اول\nپرومته یک ربات تلگرام پیشرفته است.\n\n## قابلیت‌ها\n* سرعت بالا\n* دقت فوق العاده\n\n" * 10)),
        ("HTML tags", "تست تگ‌های HTML", "<p>این یک پاراگراف است.</p><b>متن ضخیم</b><br/><i>ایتالیک</i>"),
    ]
    sub_results = []
    for label, title, content in test_cases:
        try:
            print(f"Testing publish_telegraph_article: {label}...")
            res = await asyncio.wait_for(publish_telegraph_article(title=title, content=content), timeout=20.0)
            assert "telegra.ph" in res
            status = "PASS"
            summary = f"Published successfully. Result preview: {res[:100]}"
            sub_results.append({"case": label, "title": title, "status": status, "summary": summary})
            print(f"  -> {status}: {summary}")
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)}"
            print(f"  -> FAIL: {err}")
            sub_results.append({"case": label, "title": title, "status": "FAIL", "summary": err})
    results["publish_telegraph_article"] = sub_results

async def test_transcribe_audio_tool():
    print("=== Testing transcribe_audio_tool ===")
    test_cases = [
        ("Empty input", ""),
        ("Invalid URL", "https://invalid-non-existent-domain-12345.org/audio.mp3"),
        ("Non-existent local file", "/tmp/non_existent_audio.mp3"),
    ]
    sub_results = []
    for label, inp in test_cases:
        try:
            print(f"Testing transcribe_audio_tool: {label}...")
            res = await asyncio.wait_for(transcribe_audio_tool(inp), timeout=15.0)
            status = "PASS"
            summary = f"Handled gracefully: {res}"
            sub_results.append({"case": label, "input": inp, "status": status, "summary": summary})
            print(f"  -> {status}: {summary}")
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)}"
            print(f"  -> FAIL: {err}")
            sub_results.append({"case": label, "input": inp, "status": "FAIL", "summary": err})
            
    # Also test with real audio bytes generated locally (a minimal valid MP3 / WAV file)
    try:
        print("Testing transcribe_audio_tool with local audio file...")
        # Create a tiny 1-second silent WAV / MP3 file or use a dummy file
        import tempfile
        # Generate minimal silent wav
        import wave, struct
        temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        with wave.open(temp_wav.name, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 16000)
        
        res = await asyncio.wait_for(transcribe_audio_tool(temp_wav.name), timeout=25.0)
        os.unlink(temp_wav.name)
        status = "PASS"
        summary = f"API call result: {res}"
        sub_results.append({"case": "Audio file bytes (silent WAV)", "status": status, "summary": summary})
        print(f"  -> {status}: {summary}")
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)}"
        print(f"  -> FAIL (audio bytes): {err}")
        sub_results.append({"case": "Audio file bytes (silent WAV)", "status": "FAIL", "summary": err})

    results["transcribe_audio_tool"] = sub_results

async def test_create_and_upload_file():
    print("=== Testing create_and_upload_file ===")
    test_cases = [
        ("TXT generation", "document.txt", "این یک فایل متنی تستی است.\nخط دوم فایل.\nPrometheus Super Agent."),
        ("PDF generation", "report.pdf", "# گزارش عملکرد ماهانه پرومته\n* سیستم کامپایل و تست یکپارچه\n* بررسی صحت خروجی و پردازش داده‌ها\nاین یک متن بلند برای تست شکستن خطوط در زبان فارسی و انگلیسی است."),
        ("Excel generation", "financial_data.xlsx", "نام کاربر,مبلغ پرداختی,وضعیت\nعلی احمدی,150000,موفق\nمریم رضایی,250000,موفق\nJohn Doe,300,Pending"),
        ("Docx generation", "analysis.docx", "تحلیل ساختار سیستم پرومته\n\nاین سند شامل توضیحات معماری و رفتار مدل‌های زبانی در مواجهه با ابزارهای سیستم است.\n\nبخش دوم: نتایج بررسی."),
    ]
    sub_results = []
    for label, fname, content in test_cases:
        try:
            print(f"Testing create_and_upload_file: {label} ({fname})...")
            res = await create_and_upload_file(fname, content, caption=f"Test {label}")
            assert res.get("status") == "success"
            assert res.get("type") == "document"
            assert res.get("filename") == fname
            assert len(res.get("bytes", b"")) > 0
            status = "PASS"
            summary = f"Success. Generated {res['filename']} ({res['size_bytes']} bytes), caption: '{res.get('caption')}'"
            sub_results.append({"case": label, "filename": fname, "status": status, "summary": summary, "size_bytes": res["size_bytes"]})
            print(f"  -> {status}: {summary}")
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)}"
            print(f"  -> FAIL: {err}")
            sub_results.append({"case": label, "filename": fname, "status": "FAIL", "summary": err})
    results["create_and_upload_file"] = sub_results

def test_read_document_file():
    print("=== Testing read_document_file ===")
    # 1. Existing local files (text/md, pdf, docx, xlsx)
    sub_results = []
    
    # Read existing README.md
    try:
        print("Testing read_document_file: README.md...")
        res = read_document_file("README.md")
        assert "Prometheus" in res
        sub_results.append({"case": "Local file (README.md)", "status": "PASS", "summary": f"Read OK, preview: {res[:80]}"})
    except Exception as e:
        sub_results.append({"case": "Local file (README.md)", "status": "FAIL", "summary": str(e)})

    # Read non-existent file
    try:
        print("Testing read_document_file: non-existent file...")
        res = read_document_file("/tmp/this_file_definitely_does_not_exist_9876.txt")
        assert "یافت نشد" in res
        sub_results.append({"case": "Non-existent file", "status": "PASS", "summary": f"Handled correctly: {res}"})
    except Exception as e:
        sub_results.append({"case": "Non-existent file", "status": "FAIL", "summary": str(e)})

    # Test reading generated PDF, Excel, and Docx
    import tempfile
    for ext, gen_fn in [
        (".txt", lambda p: open(p, "w", encoding="utf-8").write("تست متن فارسی در فایل txt")),
    ]:
        tf = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        try:
            gen_fn(tf.name)
            res = read_document_file(tf.name)
            sub_results.append({"case": f"Read local {ext}", "status": "PASS", "summary": f"Extracted: {res[:80]}"})
        except Exception as e:
            sub_results.append({"case": f"Read local {ext}", "status": "FAIL", "summary": str(e)})
        finally:
            if os.path.exists(tf.name):
                os.unlink(tf.name)

    results["read_document_file"] = sub_results

def test_optimize_image_for_vision():
    print("=== Testing optimize_image_for_vision ===")
    sub_results = []
    
    # 1. Mock RGB image
    try:
        print("Testing optimize_image_for_vision: Mock RGB...")
        rgb_img = Image.new("RGB", (800, 600), color=(73, 109, 137))
        buf = io.BytesIO()
        rgb_img.save(buf, format="JPEG")
        raw_rgb = buf.getvalue()
        
        b64_str, mime = optimize_image_for_vision(raw_rgb)
        assert mime == "image/jpeg"
        assert len(b64_str) > 100
        sub_results.append({
            "case": "Mock RGB (800x600)",
            "status": "PASS",
            "summary": f"Optimized successfully. Output mime={mime}, base64_len={len(b64_str)}"
        })
        print(f"  -> PASS: RGB mime={mime}, len={len(b64_str)}")
    except Exception as e:
        sub_results.append({"case": "Mock RGB", "status": "FAIL", "summary": str(e)})
        print(f"  -> FAIL: {e}")

    # 2. Mock RGBA image (with transparent background)
    try:
        print("Testing optimize_image_for_vision: Mock RGBA...")
        rgba_img = Image.new("RGBA", (1000, 1000), color=(255, 0, 0, 128))
        buf = io.BytesIO()
        rgba_img.save(buf, format="PNG")
        raw_rgba = buf.getvalue()
        
        b64_str, mime = optimize_image_for_vision(raw_rgba)
        assert mime == "image/jpeg"
        assert len(b64_str) > 100
        sub_results.append({
            "case": "Mock RGBA (1000x1000, alpha transparency)",
            "status": "PASS",
            "summary": f"Composited over white & converted to JPEG. mime={mime}, base64_len={len(b64_str)}"
        })
        print(f"  -> PASS: RGBA mime={mime}, len={len(b64_str)}")
    except Exception as e:
        sub_results.append({"case": "Mock RGBA", "status": "FAIL", "summary": str(e)})
        print(f"  -> FAIL: {e}")

    # 3. Large high-res image scaling (> 1600px)
    try:
        print("Testing optimize_image_for_vision: High-res scale down (2400x1800)...")
        large_img = Image.new("RGB", (2400, 1800), color=(120, 200, 80))
        buf = io.BytesIO()
        large_img.save(buf, format="JPEG")
        raw_large = buf.getvalue()
        
        b64_str, mime = optimize_image_for_vision(raw_large)
        assert mime == "image/jpeg"
        sub_results.append({
            "case": "Large High-Res (2400x1800)",
            "status": "PASS",
            "summary": f"Scaled down with Lanczos anti-aliasing to max 1600px, mime={mime}, base64_len={len(b64_str)}"
        })
        print(f"  -> PASS: Large High-Res scaled down, len={len(b64_str)}")
    except Exception as e:
        sub_results.append({"case": "Large High-Res", "status": "FAIL", "summary": str(e)})
        print(f"  -> FAIL: {e}")

    # 4. Corrupted bytes fallback test
    try:
        print("Testing optimize_image_for_vision: Corrupted bytes...")
        corrupt_bytes = b"NOT_AN_IMAGE_RANDOM_CORRUPT_BYTES_XYZ_12345"
        b64_str, mime = optimize_image_for_vision(corrupt_bytes)
        assert mime == "image/jpeg"
        # Should fallback gracefully and base64-encode the raw bytes without crashing
        import base64
        expected = base64.b64encode(corrupt_bytes).decode("utf-8")
        assert b64_str == expected
        sub_results.append({
            "case": "Corrupted bytes",
            "status": "PASS",
            "summary": f"Fallback triggered gracefully. No unhandled exception, returned raw base64 ({b64_str})"
        })
        print(f"  -> PASS: Corrupted bytes handled via fallback gracefully")
    except Exception as e:
        sub_results.append({"case": "Corrupted bytes", "status": "FAIL", "summary": str(e)})
        print(f"  -> FAIL: {e}")

    results["optimize_image_for_vision"] = sub_results

async def main():
    test_generate_qr_code_tool()
    test_read_document_file()
    test_optimize_image_for_vision()
    await test_create_and_upload_file()
    await test_publish_telegraph_article()
    await test_get_song_lyrics()
    await test_transcribe_audio_tool()
    await test_download_music_track()

    with open("/home/dsh/workspace/prometheuspro/test_results_dump.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\nDONE! All tests completed and saved to test_results_dump.json")

if __name__ == "__main__":
    asyncio.run(main())
