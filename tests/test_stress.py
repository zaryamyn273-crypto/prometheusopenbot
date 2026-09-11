import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
"""Heavy stress test: EVERY registered tool gets executed.
Public tools: called with realistic args (admin-gated ones use ADMIN_ID).
Internal bot_*: called directly (system-only path, as bot would).
Reports PASS/FAIL/ERROR per tool + category summary. Does NOT send Telegram messages.
"""
import asyncio
import sys
import time
import traceback

from src.core.config import ADMIN_ID
ADMIN = ADMIN_ID or 123456789

from src.tools.registry import REGISTRY, execute_registered_tool

# Realistic args per tool: (kwargs, max_seconds)
CASES = {
    # --- financial ---
    "get_price": ({"symbol": "BTC"}, 40),
    "get_crypto_overview": ({}, 60),
    "get_gold_and_coin_price": ({}, 40),
    "get_fiat_overview": ({}, 40),
    "get_global_forex_rates": ({"base": "USD"}, 40),
    # --- weather / time ---
    "get_weather": ({"city": "Tehran"}, 40),
    "get_current_datetime_info": ({}, 15),
    # --- search ---
    "web_search": ({"query": "قیمت دلار امروز", "max_results": 3}, 60),
    "tavily_search": ({"query": "اخبار هوش مصنوعی", "max_results": 3}, 40),
    "digikala_search": ({"query": "گوشی سامسونگ", "max_results": 3}, 40),
    "get_dollar_price": ({}, 40),
    "deep_search_and_read": ({"query": "هوش مصنوعی", "max_pages": 1}, 90),
    "live_news": ({"topic": "technology"}, 60),
    "fetch_webpage_content": ({"url": "https://example.com", "max_chars": 2000}, 40),
    "twitter_search": ({"query": "AI", "max_results": 3}, 60),
    "reddit_search": ({"query": "python", "max_results": 3}, 60),
    "stackoverflow_search": ({"query": "python list", "max_results": 3}, 60),
    # --- network ---
    "check_website_status": ({"target": "google.com"}, 40),
    "get_ip_info": ({"target": "1.1.1.1"}, 40),
    "resolve_dns": ({"domain": "google.com"}, 40),
    "check_ssl_certificate": ({"domain": "github.com"}, 40),
    "quick_http_inspect_tool": ({"url": "https://example.com"}, 40),
    # --- media ---
    "download_music_track": ({"query": "Hello Adele"}, 150),
    "get_song_lyrics": ({"song_title": "Hello Adele"}, 90),
    "transcribe_audio_tool": ({"audio_url_or_path": ""}, 30),
    "generate_qr_code_tool": ({"text_or_url": "https://t.me"}, 30),
    "publish_telegraph_article": ({"title": "تست استرس", "content": "متن تستی برای انتشار تلگراف. " * 10}, 60),
    "internal_resilient_fallback_search": ({"query": "تست"}, 60),
    # --- security ---
    "generate_hash_digest": ({"text": "hello", "algorithm": "sha256"}, 20),
    "base64_encode_decode": ({"text": "hello", "mode": "encode"}, 20),
    "url_encode_decode": ({"text": "hello world", "mode": "encode"}, 20),
    "generate_uuid": ({}, 20),
    "darkweb_search": ({"query": "test"}, 60),
    # --- scientific / math ---
    "calculate_math_expression": ({"expression": "2+3*4"}, 20),
    "statistics_summary": ({"numbers": [1, 2, 3, 4, 5]}, 20),
    "convert_units": ({"value": 100, "from_unit": "c", "to_unit": "f"}, 20),
    "color_converter_tool": ({"color_code": "#ff0000"}, 20),
    "json_formatter_validator": ({"json_text": '{"a": 1}'}, 20),
    # --- github ---
    "github_search_repositories": ({"query": "telegram bot", "max_results": 2}, 60),
    "github_repo_info": ({"repo": "python/cpython"}, 60),
    "github_repo_commits": ({"repo": "python/cpython", "max_results": 2}, 60),
    "github_repo_issues": ({"repo": "python/cpython", "max_results": 2}, 60),
    "github_repo_releases": ({"repo": "python/cpython", "max_results": 2}, 60),
    "github_repo_stats": ({"repo": "python/cpython"}, 60),
    "github_user_info": ({"username": "torvalds"}, 60),
    "github_search_code": ({"query": "asyncio", "max_results": 2}, 60),
    "github_issues_search": ({"query": "crash", "max_results": 2}, 60),
    "github_read_readme": ({"repo": "python/cpython"}, 60),
    "github_read_file": ({"repo": "python/cpython", "filepath": "README.rst", "path": "README.rst"}, 60),
    "github_list_tree": ({"repo": "python/cpython", "path": ""}, 60),
    "github_trending": ({}, 60),
    # --- dev ---
    "execute_python_code": ({"code": "print(2+2)", "caller_id": ADMIN, "is_private_chat": True}, 30),
    "autonomous_system_health_check": ({}, 30),
    # --- e2b cloud sandbox (graceful without key: tools return Persian guide, still counts as handled) ---
    "e2b_run_code": ({"code": "print(2+2)", "language": "python", "timeout_sec": 20, "caller_id": ADMIN}, 60),
    "e2b_run_command": ({"command": "python --version", "timeout_sec": 20, "caller_id": ADMIN}, 60),
    "e2b_status": ({"caller_id": ADMIN}, 60),
    # --- files ---
    "create_and_upload_file": ({"filename": "stress.txt", "content": "hello stress", "caption": "stress"}, 40),
    "read_document_file": ({"file_path": "README.md"}, 40),
    # --- database ---
    "cloudflare_d1_store_record": ({"key": "stress_key", "value": "stress_val"}, 40),
    "cloudflare_d1_retrieve_record": ({"key": "stress_key"}, 40),
    "cloudflare_d1_search_records": ({"query": "stress"}, 40),
    "cloudflare_d1_list_records": ({"limit": 3}, 40),
    "cloudflare_d1_delete_record": ({"key": "stress_key"}, 40),
    "cloudflare_kv_store": ({"key": "stress_k", "value": "v"}, 40),
    "cloudflare_kv_retrieve": ({"key": "stress_k"}, 40),
    "search_conversation_history": ({"query": "سلام", "chat_id": 0}, 40),
    # --- admin (use ADMIN caller) ---
    "admin_system_diagnostics": ({}, 20),
    "ban_user_tool": ({"target": "555444333", "caller_id": ADMIN, "reason": "stress-test (reban)"}, 40),
    "unban_user_tool": ({"target": "555444333", "caller_id": ADMIN}, 40),
    "extract_user_id_tool": ({"target": "imnotokyt", "caller_id": ADMIN}, 40),  # real user seen in D1 history
    "get_banned_users_list_tool": ({"caller_id": ADMIN}, 40),
    "mute_user_tool": ({"target": "999888777", "duration_minutes": 1, "reason": "stress-test", "caller_id": ADMIN}, 30),
    "unmute_user_tool": ({"target": "999888777", "caller_id": ADMIN}, 30),
    "get_muted_users_list_tool": ({"caller_id": ADMIN}, 30),
    "manage_admin_memory": ({"action": "list"}, 40),
    "list_joined_groups_tool": ({"caller_id": ADMIN}, 40),
    "leave_group_by_admin_tool": ({"target": "__dry__", "caller_id": ADMIN}, 30),
    "ban_group_by_name_or_id_tool": ({"target": "__dry__nonexistent__", "caller_id": ADMIN}, 30),  # EXPECT-FAIL: dry-run, no such group
    "list_public_channels_tool": ({"caller_id": ADMIN}, 40),
    # --- internal bot_* (system-only direct calls) ---
    "bot_self_diagnose": ({}, 30),
    "bot_tool_health_probe": ({"tool_name": "web_search"}, 20),
    "bot_smart_cache_put": ({"key": "stress", "value": "v"}, 30),
    "bot_smart_cache_get": ({"key": "stress"}, 30),
    "bot_query_rewriter": ({"query": "قیمت  دلار"}, 15),
    "bot_intent_splitter": ({"prompt": "قیمت دلار و هوای تهران"}, 15),
    "bot_tool_picker": ({"query": "قیمت دلار"}, 15),
    "bot_fallback_search": ({"query": "تست"}, 60),
    "bot_news_fallback": ({"topic": "AI"}, 60),
    "bot_music_fallback": ({"query": "Hello Adele"}, 150),
    "bot_lyrics_fallback": ({"song_title": "Hello Adele"}, 90),
    "bot_file_fallback_publish": ({"title": "t", "content": "متن تست"}, 60),
    "bot_qr_fallback": ({"text_or_url": "https://t.me"}, 30),
    "bot_d1_remember": ({"key": "stress_bot", "value": "v"}, 40),
    "bot_d1_recall": ({"key": "stress_bot"}, 40),
    "bot_history_recall": ({"query": "سلام", "chat_id": 0}, 40),
    "bot_rate_guard": ({"user_id": 12345}, 15),
    "bot_output_compactor": ({"text": "x" * 5000}, 15),
    "bot_prompt_token_saver": ({"prompt": "a  b  c"}, 15),
    "bot_alias_resolver": ({"name": "web_serch"}, 15),
}

FAILURE_HINTS = ("اختلال", "در دسترس نیست", "موجود نیست", "موفق نشد", "خطا در اجرا", "Traceback")
# NOTE: "یافت نشد" alone is NOT failure — graceful fallbacks legitimately
# contain it while delivering real data (e.g. darkweb clearnet fallback).
SOFT_OK_MARKERS = ("اما اطلاعات مرتبط", "بازیابی خودکار")


EXPECTED_FAIL = {"ban_group_by_name_or_id_tool", "leave_group_by_admin_tool"}  # dry-run guards: PASS = correct refusal


def _verdict(name, out):
    if isinstance(out, dict):
        t = out.get("type")
        if t == "error":
            return ("FAIL", f"error-type: {str(out.get('message', out))[:120]}")
        if t in ("audio", "audio_bytes", "document", "voice"):
            n = len(out.get("bytes", b"")) if out.get("bytes") else 0
            return ("PASS", f"media:{t} bytes={n} url={bool(out.get('url'))}")
        return ("PASS", f"dict keys={list(out.keys())[:5]}")
    s = str(out or "")
    if not s.strip():
        return ("FAIL", "empty output")
    if any(ok in s for ok in SOFT_OK_MARKERS):
        return ("PASS", f"{len(s)} chars (graceful fallback): {s[:90].replace(chr(10), ' ')}")
    if any(h in s for h in FAILURE_HINTS):
        return ("FAIL", s[:140].replace("\n", " "))
    return ("PASS", f"{len(s)} chars: {s[:90].replace(chr(10), ' ')}")


async def run_one(name, sem):
    from src.tools import internal  # noqa: ensure internal registered  # pylint: disable=unused-import
    kwargs, timeout = CASES.get(name, ({}, 30))
    t0 = time.time()
    async with sem:
        try:
            out = await asyncio.wait_for(
                execute_registered_tool(name, dict(kwargs), caller_id=kwargs.get("caller_id", 0),
                                        is_private_chat=bool(kwargs.get("is_private_chat", False))),
                timeout=timeout,
            )
            dt = time.time() - t0
            status, detail = _verdict(name, out)
            if name in EXPECTED_FAIL and status == "FAIL":
                status = "PASS"
                detail = f"(expected dry-run refusal) {detail}"
            return (name, status, f"{dt:.1f}s", detail)
        except asyncio.TimeoutError:
            return (name, "TIMEOUT", f">={timeout}s", "exceeded budget")
        except Exception as e:
            return (name, "ERROR", f"{time.time()-t0:.1f}s", f"{type(e).__name__}: {e}"[:140])


async def main():
    import src.tools  # noqa: ensure all tool packages registered
    names = sorted(REGISTRY.keys())
    missing = [n for n in names if n not in CASES]
    sem = asyncio.Semaphore(6)  # heavy but bounded parallelism
    t0 = time.time()
    results = await asyncio.gather(*[run_one(n, sem) for n in names])
    total_dt = time.time() - t0
    npass = sum(1 for r in results if r[1] == "PASS")
    nfail = sum(1 for r in results if r[1] == "FAIL")
    nerr = sum(1 for r in results if r[1] not in ("PASS", "FAIL"))
    print(f"\n===== STRESS RESULT: {npass} PASS / {nfail} FAIL / {nerr} ERROR-TIMEOUT out of {len(results)} tools in {total_dt:.0f}s =====")
    if missing:
        print("NO-CASE:", ", ".join(missing))
    print("\n--- FAILURES & ERRORS ---")
    for name, status, dt, detail in results:
        if status != "PASS":
            cat = REGISTRY[name].get("category", "?")
            print(f"[{status}] {name} ({cat}) [{dt}] :: {detail}")
    print("\n--- SLOWEST 10 ---")
    def _sec(x):
        try:
            return float(x[2].rstrip("s").lstrip(">="))
        except Exception:
            return 0.0
    for name, status, dt, detail in sorted(results, key=_sec, reverse=True)[:10]:
        print(f"{dt:>8} {status:<7} {name} :: {detail[:80]}")
    print("\n--- ALL PASS (name [time]) ---")
    print(", ".join(f"{n}[{d}]" for n, s, d, _ in results if s == "PASS"))
    return 0 if (nfail + nerr) == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
