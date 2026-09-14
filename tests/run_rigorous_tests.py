import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
#!/usr/bin/env python3
"""
Rigorous Test Suite for Prometheus Bot Web Search, External Intelligence, and Network Tools.
Tests:
1. web_search (complex Persian queries, unicode punctuation, English technical queries)
2. deep_search_and_read (multi-page fetching, content extraction)
3. tavily_search (time_range, queries with special characters, news)
4. live_news (topics: technology, crypto, general, iran)
5. fetch_webpage_content (valid URLs, 404 URLs, dead domains, heavy pages)
6. twitter_search (search queries, empty results)
7. reddit_search (queries, subreddits, sorting, empty results)
8. stackoverflow_search (questions with accepted answers, questions without answers)
9. digikala_search (real products, completely nonexistent product queries)
10. check_website_status (valid http/https, dead IP, invalid domains)
11. get_ip_info (public IP 1.1.1.1, private IP 192.168.1.1, domain target)
12. resolve_dns (valid A/AAAA/MX records, nonexistent domains)
13. check_ssl_certificate (valid SSL, self-signed/expired or invalid host)
14. quick_http_inspect_tool (valid URLs, error URLs, invalid domains)
"""

import asyncio
import time
import json
import traceback
from typing import Dict, Any, List

from src.tools.web_network import (
    web_search,
    deep_search_and_read,
    tavily_search,
    live_news,
    fetch_webpage_content,
    twitter_search,
    check_website_status,
    get_ip_info,
    resolve_dns,
    check_ssl_certificate
)
from src.tools.web_network.digikala import digikala_search
from src.tools.dev import (
    reddit_search,
    stackoverflow_search,
    quick_http_inspect_tool
)

results: List[Dict[str, Any]] = []

async def run_case(tool_name: str, case_name: str, coro_fn, *args, **kwargs) -> Dict[str, Any]:
    start = time.perf_counter()
    success = False
    err_msg = ""
    ret_val = None
    ret_type = ""
    
    try:
        ret_val = await coro_fn(*args, **kwargs)
        ret_type = type(ret_val).__name__
        success = True
    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e)}"
        ret_type = "Exception"
        traceback.print_exc()
        
    duration = time.perf_counter() - start
    
    # Analyze output
    summary = ""
    if isinstance(ret_val, str):
        summary = ret_val[:200].replace("\n", " ")
        out_len = len(ret_val)
    elif ret_val is not None:
        summary = str(ret_val)[:200]
        out_len = len(str(ret_val))
    else:
        out_len = 0

    record = {
        "tool": tool_name,
        "case": case_name,
        "args": str(args),
        "kwargs": str(kwargs),
        "duration_sec": round(duration, 3),
        "success": success,
        "return_type": ret_type,
        "length": out_len,
        "summary": summary,
        "error": err_msg,
        "full_output": ret_val if isinstance(ret_val, str) else str(ret_val)
    }
    results.append(record)
    status_sym = "✅ PASS" if success else "❌ FAIL"
    print(f"[{status_sym}] {tool_name} :: {case_name} ({duration:.2f}s, len={out_len})")
    return record

async def main():
    print("==================================================")
    print("STARTING RIGOROUS SEARCH & NETWORK TOOLS TEST SUITE")
    print("==================================================")

    # 1. web_search
    print("\n--- Testing: web_search ---")
    await run_case("web_search", "Persian Complex Query", web_search, "بررسی جدیدترین تحولات هوش مصنوعی و مدل‌های زبانی بزرگ در سال ۲۰۲۵", force_refresh=True)
    await run_case("web_search", "Unicode & Punctuation Query", web_search, "قیمت طلا ۱۸ عیار؛ «سکه امامی» & نیم‌سکه؟ (امروز)!", force_refresh=True)
    await run_case("web_search", "English Technical Query", web_search, "PostgreSQL 16 logical replication conflict resolution high availability", force_refresh=True)
    await run_case("web_search", "Empty Query Handling", web_search, "")

    # 2. deep_search_and_read
    print("\n--- Testing: deep_search_and_read ---")
    await run_case("deep_search_and_read", "Multi-page fetch & extraction", deep_search_and_read, "کوانتوم کامپیوتر و نحوه کار کیوبیت ها", max_pages=2)
    await run_case("deep_search_and_read", "English Deep Research", deep_search_and_read, "Transformer architecture attention mechanism explained", max_pages=2)
    await run_case("deep_search_and_read", "Empty Research Query", deep_search_and_read, "")

    # 3. tavily_search
    print("\n--- Testing: tavily_search ---")
    await run_case("tavily_search", "News Time Range: day", tavily_search, "NVIDIA latest GPU release news", max_results=3, time_range="day")
    await run_case("tavily_search", "Special Characters Query", tavily_search, "C++20 vs Rust: std::atomic<T*> & memory_order_relaxed!?", max_results=3)
    await run_case("tavily_search", "Persian News Query", tavily_search, "آخرین وضعیت هواشناسی و بارش باران در تهران", max_results=3, time_range="week")
    await run_case("tavily_search", "Empty Query", tavily_search, "")

    # 4. live_news
    print("\n--- Testing: live_news ---")
    await run_case("live_news", "Topic: technology", live_news, topic="tech")
    await run_case("live_news", "Topic: crypto", live_news, topic="crypto")
    await run_case("live_news", "Topic: general", live_news, topic="general")
    await run_case("live_news", "Topic: iran", live_news, topic="iran")
    await run_case("live_news", "Topic: invalid/custom topic", live_news, topic="robotics_automation")

    # 5. fetch_webpage_content
    print("\n--- Testing: fetch_webpage_content ---")
    await run_case("fetch_webpage_content", "Valid URL", fetch_webpage_content, "https://example.com")
    await run_case("fetch_webpage_content", "Valid Complex Iranian URL", fetch_webpage_content, "https://fa.wikipedia.org/wiki/ایران")
    await run_case("fetch_webpage_content", "404 Not Found URL", fetch_webpage_content, "https://httpbin.org/status/404")
    await run_case("fetch_webpage_content", "Dead Domain", fetch_webpage_content, "https://thisdomaindefinitelydoesnotexistatall12345.com")
    await run_case("fetch_webpage_content", "Heavy Page (Truncation & Clean)", fetch_webpage_content, "https://en.wikipedia.org/wiki/List_of_programming_languages", max_chars=1500)

    # 6. twitter_search
    print("\n--- Testing: twitter_search ---")
    await run_case("twitter_search", "Username query", twitter_search, "@OpenAI", max_results=4)
    await run_case("twitter_search", "Hashtag query", twitter_search, "#ArtificialIntelligence", max_results=4)
    await run_case("twitter_search", "Topic query", twitter_search, "DeepSeek AI reasoning", max_results=4)
    await run_case("twitter_search", "Empty query", twitter_search, "")

    # 7. reddit_search
    print("\n--- Testing: reddit_search ---")
    await run_case("reddit_search", "General Search query", reddit_search, "best python web framework 2025")
    await run_case("reddit_search", "Subreddit Specific", reddit_search, "fastapi vs django", subreddit="Python")
    await run_case("reddit_search", "Sorting: new", reddit_search, "machine learning discussion", subreddit="MachineLearning", sort="new")
    await run_case("reddit_search", "Empty query", reddit_search, "")

    # 8. stackoverflow_search
    print("\n--- Testing: stackoverflow_search ---")
    await run_case("stackoverflow_search", "Question with Accepted Answer", stackoverflow_search, "How to iterate over rows in DataFrame in Pandas", tagged="python")
    await run_case("stackoverflow_search", "Technical bug / error query", stackoverflow_search, "fatal: refusing to merge unrelated histories", tagged="git")
    await run_case("stackoverflow_search", "Obscure / Question without answers", stackoverflow_search, "xyznonexistentfunctioncall_error_code_999999_unhandled")
    await run_case("stackoverflow_search", "Empty query", stackoverflow_search, "")

    # 9. digikala_search
    print("\n--- Testing: digikala_search ---")
    await run_case("digikala_search", "Real Product: Laptop", digikala_search, "لپ تاپ ایسوس", max_results=3)
    await run_case("digikala_search", "Real Product: Phone", digikala_search, "آیفون 13", max_results=3)
    await run_case("digikala_search", "Completely Nonexistent Product", digikala_search, "کالای_کاملا_ناموجود_و_تخیلی_برای_تست_پرومته_۹۹۹")
    await run_case("digikala_search", "Empty query", digikala_search, "")

    # 10. check_website_status
    print("\n--- Testing: check_website_status ---")
    await run_case("check_website_status", "Valid HTTPS website", check_website_status, "https://google.com")
    await run_case("check_website_status", "Valid HTTP website (auto-redirect)", check_website_status, "http://example.com")
    await run_case("check_website_status", "Dead/Unreachable IP", check_website_status, "http://192.0.2.1:81") # RFC 5737 TEST-NET-1 (unroutable)
    await run_case("check_website_status", "Invalid/Nonexistent Domain", check_website_status, "https://nonexistent-site-test-12345.com")

    # 11. get_ip_info
    print("\n--- Testing: get_ip_info ---")
    await run_case("get_ip_info", "Public IP 1.1.1.1 (Cloudflare)", get_ip_info, "1.1.1.1")
    await run_case("get_ip_info", "Public IP 8.8.8.8 (Google)", get_ip_info, "8.8.8.8")
    await run_case("get_ip_info", "Private IP 192.168.1.1", get_ip_info, "192.168.1.1")
    await run_case("get_ip_info", "Domain Target", get_ip_info, "github.com")

    # 12. resolve_dns
    print("\n--- Testing: resolve_dns ---")
    await run_case("resolve_dns", "Valid A Record (google.com)", resolve_dns, "google.com", "A")
    await run_case("resolve_dns", "Valid AAAA Record (google.com)", resolve_dns, "google.com", "AAAA")
    await run_case("resolve_dns", "Valid MX Record (gmail.com)", resolve_dns, "gmail.com", "MX")
    await run_case("resolve_dns", "Valid TXT Record (cloudflare.com)", resolve_dns, "cloudflare.com", "TXT")
    await run_case("resolve_dns", "Nonexistent Domain", resolve_dns, "this-domain-does-not-exist-at-all-987654.com", "A")
    await run_case("resolve_dns", "Invalid Record Type", resolve_dns, "google.com", "INVALID_TYPE")

    # 13. check_ssl_certificate
    print("\n--- Testing: check_ssl_certificate ---")
    await run_case("check_ssl_certificate", "Valid SSL (google.com)", check_ssl_certificate, "google.com")
    await run_case("check_ssl_certificate", "Valid SSL (github.com)", check_ssl_certificate, "github.com")
    await run_case("check_ssl_certificate", "Expired SSL (expired.badssl.com)", check_ssl_certificate, "expired.badssl.com")
    await run_case("check_ssl_certificate", "Self-signed SSL (self-signed.badssl.com)", check_ssl_certificate, "self-signed.badssl.com")
    await run_case("check_ssl_certificate", "Invalid Host / Dead Domain", check_ssl_certificate, "nonexistent-domain-ssl-test-999.xyz")

    # 14. quick_http_inspect_tool
    print("\n--- Testing: quick_http_inspect_tool ---")
    await run_case("quick_http_inspect_tool", "Valid URL (https://example.com)", quick_http_inspect_tool, "https://example.com")
    await run_case("quick_http_inspect_tool", "Valid URL HEAD-to-GET fallback / 403 / 405", quick_http_inspect_tool, "https://httpbin.org/status/405")
    await run_case("quick_http_inspect_tool", "HTTP 404 URL", quick_http_inspect_tool, "https://httpbin.org/status/404")
    await run_case("quick_http_inspect_tool", "Invalid Domain", quick_http_inspect_tool, "https://nonexistent-domain-inspect-999.xyz")

    print("\n==================================================")
    print("TEST SUITE RUN COMPLETED!")
    print(f"Total test cases executed: {len(results)}")
    print("==================================================")

    # Save structured JSON
    import tempfile
    res_file = os.path.join(tempfile.gettempdir(), "search_network_test_results.json")
    with open(res_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"Saved test results to {res_file}")

if __name__ == "__main__":
    asyncio.run(main())
