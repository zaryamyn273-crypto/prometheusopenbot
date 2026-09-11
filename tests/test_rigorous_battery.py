import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
"""
Exhaustive Multi-Domain Tool and Agent Rigorous Testing Battery.
Executes deep stress tests, edge-case evaluations, and boundary tests for all registered tools.
Logs detailed diagnostics to /tmp/test_battery_results.json
"""
import asyncio
import json
import time
import sys
import os

from src.core.config import ADMIN_ID
from src.tools.registry import REGISTRY, execute_registered_tool

# Comprehensive dictionary of deep, difficult, and edge-case inputs for all 96 tools
DIFFICULT_TEST_CASES = {
    # --- 1. Financial & Crypto (Volatile markets, exotic coins, currency converters) ---
    "get_price": [
        {"symbol": "BTC"},
        {"symbol": "SOL"},
        {"symbol": "TON"},
        {"symbol": "NONEXISTENT_COIN_XYZ_123"},
        {"symbol": "eth"}
    ],
    "get_crypto_overview": [
        {}
    ],
    "get_gold_and_coin_price": [
        {}
    ],
    "get_fiat_overview": [
        {}
    ],
    "get_dollar_price": [
        {"force_refresh": True},
        {"force_refresh": False}
    ],
    "get_global_forex_rates": [
        {"base": "USD"},
        {"base": "EUR"},
        {"base": "AED"}
    ],

    # --- 2. Web Search & Intelligence (Unicode, Persian, long queries, complex filters) ---
    "web_search": [
        {"query": "قیمت خودرو صفر امروز در تهران", "max_results": 3},
        {"query": "Python 3.12 asyncio event loop changes", "max_results": 2},
        {"query": "تست کاراکترهای خاص !@#$%^&*()_+-=", "max_results": 1}
    ],
    "deep_search_and_read": [
        {"query": "هوش مصنوعی و پردازنده‌های عصبی NPU", "max_pages": 1}
    ],
    "tavily_search": [
        {"query": "OpenAI GPT-5 announcement news", "max_results": 2},
        {"query": "قیمت سکه بهار آزادی امروز", "max_results": 2}
    ],
    "live_news": [
        {"topic": "technology"},
        {"topic": "crypto"},
        {"topic": "iran"}
    ],
    "fetch_webpage_content": [
        {"url": "https://httpbin.org/html", "max_chars": 1500},
        {"url": "https://invalid-nonexistent-domain-404-xyz.com", "max_chars": 1000}
    ],
    "twitter_search": [
        {"query": "Bitcoin ETF", "max_results": 2},
        {"query": "هوش مصنوعی", "max_results": 2}
    ],
    "reddit_search": [
        {"query": "python asyncio", "max_results": 2}
    ],
    "stackoverflow_search": [
        {"query": "python telegram bot send photo", "max_results": 2},
        {"query": "asyncio gather exception handling", "max_results": 2}
    ],
    "digikala_search": [
        {"query": "مک بوک ایر m3", "max_results": 2},
        {"query": "کالای_خیلی_عجیب_غریب_ناموجود_۹۹", "max_results": 2}
    ],

    # --- 3. Network & Infrastructure Security ---
    "check_website_status": [
        {"url": "https://google.com"},
        {"url": "https://1.1.1.1"},
        {"url": "http://invalid-dead-domain-test-xyz.org"}
    ],
    "get_ip_info": [
        {"target": "8.8.8.8"},
        {"target": "1.1.1.1"},
        {"target": "google.com"}
    ],
    "resolve_dns": [
        {"domain": "cloudflare.com"},
        {"domain": "google.com"}
    ],
    "check_ssl_certificate": [
        {"domain": "github.com"},
        {"domain": "google.com"}
    ],
    "quick_http_inspect_tool": [
        {"url": "https://google.com"}
    ],

    # --- 4. Scientific, Math & Utilities ---
    "calculate_math_expression": [
        {"expression": "sqrt(144) + 2**10"},
        {"expression": "sin(pi / 2) * cos(0)"},
        {"expression": "100 / 0"},  # division by zero check
        {"expression": "2**100"},
        {"expression": "9**9**9**9"}  # blocked power test
    ],
    "statistics_summary": [
        {"numbers": [10, 20, 30, 40, 50, 60, 70]},
        {"numbers": [5, 5, 5, 5]}
    ],
    "convert_units": [
        {"value": 100, "from_unit": "km", "to_unit": "mile"},
        {"value": 37, "from_unit": "c", "to_unit": "f"},
        {"value": 1024, "from_unit": "mb", "to_unit": "gb"}
    ],
    "color_converter_tool": [
        {"color": "#FF5733"},
        {"color": "rgb(0, 128, 255)"}
    ],
    "generate_hash_digest": [
        {"text": "Prometheus Super Agent 2026", "algorithm": "sha256"},
        {"text": "SecurePassword123", "algorithm": "md5"}
    ],
    "base64_encode_decode": [
        {"text": "سلام جهان! Hello World", "mode": "encode"},
        {"text": "2LPZhNin2YUg2KzZh9in2YYhIEhlbGxvIFdvcmxk", "mode": "decode"}
    ],
    "url_encode_decode": [
        {"text": "https://google.com/search?q=تست پرومته", "mode": "encode"},
        {"text": "https%3A//google.com/search%3Fq%3D%D8%AA%D8%B3%D8%AA", "mode": "decode"}
    ],
    "generate_uuid": [
        {}
    ],
    "json_formatter_validator": [
        {"text": '{"name": "Prometheus", "version": 5.0, "active": true}'},
        {"text": '{invalid json string:'}
    ],
    "get_current_datetime_info": [
        {}
    ],
    "get_weather": [
        {"city": "Tehran"},
        {"city": "Isfahan"},
        {"city": "London"}
    ],

    # --- 5. Media, Audio & File Engines ---
    "get_song_lyrics": [
        {"song_title": "Adele Hello"}
    ],
    "generate_qr_code_tool": [
        {"text_or_url": "https://t.me/Prometheusbaibot"}
    ],
    "publish_telegraph_article": [
        {"title": "گزارش تست پرومته", "content": "این یک مقاله آزمایشی برای تست پایداری تلگراف است." * 5}
    ],
    "transcribe_audio_tool": [
        {"audio_url_or_path": ""}  # Empty input safe check
    ],
    "download_music_track": [
        {"query": "Adele Skyfall"}
    ],

    # --- 6. GitHub Intelligence Suite ---
    "github_search_repositories": [
        {"query": "telegram bot python", "max_results": 2}
    ],
    "github_repo_info": [
        {"repo": "python/cpython"}
    ],
    "github_repo_commits": [
        {"repo": "python/cpython", "max_results": 2}
    ],
    "github_repo_issues": [
        {"repo": "python/cpython", "max_results": 2}
    ],
    "github_repo_releases": [
        {"repo": "python/cpython", "max_results": 2}
    ],
    "github_repo_stats": [
        {"repo": "python/cpython"}
    ],
    "github_user_info": [
        {"username": "torvalds"}
    ],
    "github_search_code": [
        {"query": "asyncio.create_task", "max_results": 2}
    ],
    "github_issues_search": [
        {"query": "IndexError", "max_results": 2}
    ],
    "github_read_readme": [
        {"repo": "python/cpython"}
    ],
    "github_read_file": [
        {"repo": "python/cpython", "filepath": "README.rst"}
    ],
    "github_list_tree": [
        {"repo": "python/cpython", "path": ""}
    ],
    "github_trending": [
        {}
    ],

    # --- 7. Cloudflare D1 Database & Storage Subsystem ---
    "cloudflare_d1_store_record": [
        {"key": "test_battery_k1", "value": "test_battery_v1"}
    ],
    "cloudflare_d1_retrieve_record": [
        {"key": "test_battery_k1"}
    ],
    "cloudflare_d1_search_records": [
        {"query": "test_battery"}
    ],
    "cloudflare_d1_list_records": [
        {"limit": 3}
    ],
    "cloudflare_d1_delete_record": [
        {"key": "test_battery_k1"}
    ],
    "cloudflare_kv_store": [
        {"key": "test_kv_battery", "value": "12345"}
    ],
    "cloudflare_kv_retrieve": [
        {"key": "test_kv_battery"}
    ],
    "search_conversation_history": [
        {"query": "سلام", "chat_id": 0}
    ],

    # --- 8. System, Developer & Admin Capabilities ---
    "execute_python_code": [
        {"code": "import math; print([math.factorial(i) for i in range(6)])", "caller_id": ADMIN_ID, "is_private_chat": True},
        {"code": "import os; print(os.name)", "caller_id": ADMIN_ID, "is_private_chat": True},
        {"code": "print(10/0)", "caller_id": ADMIN_ID, "is_private_chat": True}  # Error handling in sandbox
    ],
    "admin_system_diagnostics": [
        {}
    ],
    "ban_user_tool": [
        {"target": "111222333", "reason": "test battery ban", "caller_id": ADMIN_ID}
    ],
    "unban_user_tool": [
        {"target": "111222333", "caller_id": ADMIN_ID}
    ],
    "mute_user_tool": [
        {"target": "444555666", "duration_minutes": 2, "reason": "test battery mute", "caller_id": ADMIN_ID}
    ],
    "unmute_user_tool": [
        {"target": "444555666", "caller_id": ADMIN_ID}
    ],
    "get_muted_users_list_tool": [
        {"caller_id": ADMIN_ID}
    ],
    "get_banned_users_list_tool": [
        {"caller_id": ADMIN_ID}
    ],
    "extract_user_id_tool": [
        {"target": "mohtorb", "caller_id": ADMIN_ID}
    ],
    "manage_admin_memory": [
        {"action": "list"}
    ],
    "list_joined_groups_tool": [
        {"caller_id": ADMIN_ID}
    ],
    "list_public_channels_tool": [
        {"caller_id": ADMIN_ID}
    ],
    "create_and_upload_file": [
        {"filename": "test_battery.txt", "content": "Sample file content", "caption": "Battery test"}
    ],
    "read_document_file": [
        {"file_path": "requirements.txt"}
    ],

    # --- 9. Internal Intelligent Fallbacks & Daemons ---
    "bot_self_diagnose": [{}],
    "bot_tool_health_probe": [{"tool_name": "web_search"}],
    "bot_smart_cache_put": [{"key": "batt_cache", "value": "val123"}],
    "bot_smart_cache_get": [{"key": "batt_cache"}],
    "bot_query_rewriter": [{"query": "نرخ تتر و بیت‌کوین چنده؟"}],
    "bot_intent_splitter": [{"prompt": "قیمت دلار و وضعیت هوای مشهد"}],
    "bot_tool_picker": [{"query": "دانلود آهنگ Hello Adele"}],
    "bot_fallback_search": [{"query": "تکنولوژی کوانتوم"}],
    "bot_news_fallback": [{"topic": "هوش مصنوعی"}],
    "bot_music_fallback": [{"query": "Adele Skyfall"}],
    "bot_lyrics_fallback": [{"song_title": "Adele Skyfall"}],
    "bot_file_fallback_publish": [{"title": "گزارش", "content": "متن تستی آزمون"}],
    "bot_qr_fallback": [{"text_or_url": "https://google.com"}],
    "bot_history_recall": [{"query": "سلام", "chat_id": 0}],
}

async def run_tool_test(tool_name, case, sem):
    async with sem:
        t0 = time.time()
        try:
            res = await asyncio.wait_for(
                execute_registered_tool(
                    tool_name,
                    dict(case),
                    caller_id=case.get("caller_id", ADMIN_ID),
                    is_private_chat=case.get("is_private_chat", True)
                ),
                timeout=45.0
            )
            dt = time.time() - t0
            
            # Evaluate output validity
            if res is None:
                return {"tool": tool_name, "case": case, "status": "FAIL", "reason": "Result is None", "duration": dt}
            
            if isinstance(res, dict) and res.get("type") == "error":
                return {"tool": tool_name, "case": case, "status": "FAIL", "reason": res.get("message", "Error dict returned"), "duration": dt}
            
            res_str = str(res)
            # Acceptable error strings for intentional edge cases (like division by zero, invalid domain, etc.)
            # Check if internal python traceback occurred in tool execution (not fetched content)
            if tool_name not in ("github_issues_search", "stackoverflow_search", "web_search", "deep_search_and_read") and "Traceback (most recent call last):" in res_str:
                return {"tool": tool_name, "case": case, "status": "FAIL", "reason": res_str[:160], "duration": dt}
            
            return {"tool": tool_name, "case": case, "status": "PASS", "output_preview": res_str[:100], "duration": dt}
        except asyncio.TimeoutError:
            return {"tool": tool_name, "case": case, "status": "TIMEOUT", "reason": "Exceeded 45s", "duration": 45.0}
        except Exception as e:
            return {"tool": tool_name, "case": case, "status": "ERROR", "reason": f"{type(e).__name__}: {str(e)}", "duration": time.time() - t0}

async def main():
    import src.tools  # Ensure all tools registered
    sem = asyncio.Semaphore(8)  # High concurrency
    tasks = []
    
    for tool_name, cases in DIFFICULT_TEST_CASES.items():
        if tool_name not in REGISTRY:
            print(f"Warning: {tool_name} not in registry!")
            continue
        for c in cases:
            tasks.append(run_tool_test(tool_name, c, sem))
            
    print(f"Executing {len(tasks)} rigorous edge-case tests across {len(DIFFICULT_TEST_CASES)} tools...")
    results = await asyncio.gather(*tasks)
    
    passed = [r for r in results if r["status"] == "PASS"]
    failed = [r for r in results if r["status"] != "PASS"]
    
    summary = {
        "total_tests": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "failures": failed
    }
    
    with open("/tmp/test_battery_results.json", "w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False, indent=2)
        
    print(f"=== Battery Finished: {len(passed)} PASS / {len(failed)} FAIL out of {len(results)} tests ===")
    if failed:
        print("FAILURES SUMMARY:")
        for f in failed:
            print(f"  [{f['status']}] {f['tool']}: {f['reason']} (input: {f['case']})")

if __name__ == "__main__":
    asyncio.run(main())
