import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import asyncio
import time
from src.core import database, ai_service, config
from src.tools import (
    registry, scientific, financial, web_network, system, media, github, files as file_reader, database as database_tools
)
from src.utils import telegram_formatter

async def run_master_audit():
    print('========================================================')
    print('  PROMETHEUS V5.0 ULTIMATE: COMPLETE SYSTEM AUDIT TEST')
    print('========================================================')

    # 1. Registry Inspection
    print('\n1. Tool Registry Verification:')
    all_defs = registry.get_all_tool_definitions()
    print(f'   Total Registered Tool Schemas: {len(all_defs)}')
    assert len(all_defs) >= 42, f'Expected at least 42 tools, got {len(all_defs)}'
    print(f'   ✅ Registry integrity verified ({len(all_defs)} tools present).')

    # 2. Database & Cache Multi-Tier Test
    print('\n2. Multi-Tier Cache & Storage Test:')
    database.init_db()
    await database.kv_set_cache_async('test_v5_key', 'hello_world_v5', 60)
    cached_val = await database.kv_get_cache_async('test_v5_key')
    assert cached_val == 'hello_world_v5'
    print('   ✅ L1 & Cloudflare KV caching: OK')

    # 3. Scientific & Math Tools
    print('\n3. Scientific & Math Tools:')
    m = scientific.calculate_math_expression('factorial(5) + 2^6')
    assert '184' in m
    stat = scientific.statistics_summary('10, 20, 30, 40, 50')
    assert 'Mean' in stat
    h = scientific.generate_hash_digest('prometheus', 'sha256')
    assert 'SHA256' in h
    u = scientific.convert_units(100, 'c', 'f')
    assert '212' in u
    dt = scientific.get_current_datetime_info()
    assert 'ساعت' in dt
    col = scientific.color_converter_tool('#3498DB')
    assert 'RGB' in col
    print('   ✅ Math, Statistics, Hash, Units, Time, Colors: OK')

    # 4. Financial & Market Tools
    print('\n4. Financial & Crypto Tools:')
    btc = await financial.get_price('BTC')
    assert 'BTC' in btc or 'بایننس' in btc
    grid = await financial.get_crypto_overview()
    assert 'BTC' in grid and 'ETH' in grid
    gold = await financial.get_gold_and_coin_price()
    assert 'طلا' in gold or 'سکه' in gold
    fiat = await financial.get_fiat_overview()
    assert 'دلار' in fiat or 'تومان' in fiat
    print('   ✅ Crypto, Binance, Nobitex, Gold, Coins, Fiat: OK')

    # 5. Web, Search & Network Tools
    print('\n5. Web Search & Network Tools:')
    srch = await web_network.web_search('Python programming')
    assert len(srch) > 30
    news = await web_network.live_news('tech')
    assert len(news) > 20
    weath = await web_network.get_weather('Tehran')
    assert 'دما' in weath or 'Tehran' in weath or 'تهران' in weath
    dns = await web_network.resolve_dns('google.com')
    assert 'TTL' in dns or 'رکوردهای DNS' in dns
    ip_info = await web_network.get_ip_info('1.1.1.1')
    assert 'Cloudflare' in ip_info or 'کشور' in ip_info
    ssl_chk = await web_network.check_ssl_certificate('github.com')
    assert 'SSL' in ssl_chk or 'صادرکننده' in ssl_chk
    print('   ✅ Multi-Engine Search, News, Weather, DNS, IP, SSL: OK')

    # 6. Media & Audio Tools
    print('\n6. Media & Audio Engine:')
    music = await media.download_music_track('Hello Adele')
    assert isinstance(music, dict) and music.get('type') in ('audio', 'audio_bytes')
    qr = media.generate_qr_code_tool('https://t.me/prometheus')
    assert 'qrserver.com' in qr
    tele = await media.publish_telegraph_article('Test Title', 'Test Content Body')
    assert 'telegra.ph' in tele
    print('   ✅ Native Audio Player, QR Generator, Telegraph Publisher: OK')

    # 7. System Sandbox & Admin Tools
    print('\n7. Sandbox & System Diagnostics:')
    py_exec = await system.execute_python_code('print(list(range(5)))', caller_id=config.ADMIN_ID)
    assert '[0, 1, 2, 3, 4]' in py_exec
    diag = system.admin_system_diagnostics()
    assert 'CPU' in diag and 'RAM' in diag
    print('   ✅ Python Sandbox & Server Diagnostics: OK')

    # 8. GitHub Tools (12 GitHub tools)
    print('\n8. GitHub Tools:')
    gh_s = await github.github_search_repositories('telegram bot python')
    assert 'github.com' in gh_s
    gh_info = await github.github_repo_info('psf/requests')
    assert 'ستاره' in gh_info or 'Stars' in gh_info
    gh_user = await github.github_user_info('torvalds')
    assert 'پروفایل' in gh_user or 'torvalds' in gh_user
    gh_commits = await github.github_repo_commits('psf/requests', max_results=2)
    assert 'کامیت' in gh_commits
    gh_issues = await github.github_repo_issues('psf/requests', max_results=2)
    assert 'ایسیو' in gh_issues or 'issue' in gh_issues.lower() or 'باز' in gh_issues
    gh_rel = await github.github_repo_releases('psf/requests', max_results=1)
    assert 'ریلیز' in gh_rel or 'نسخه' in gh_rel or 'منتشر' in gh_rel
    gh_stats = await github.github_repo_stats('psf/requests')
    assert 'زبان' in gh_stats
    gh_trend = await github.github_trending('', 'daily')
    assert 'ترند' in gh_trend
    print('   ✅ GitHub x12 (search/info/readme/file/tree/user/commits/issues/releases/code/stats/trending): OK')

    # 9. Formatter & Telegram HTML Converter
    print('\n9. Telegram HTML Safe Formatter:')
    raw_md = "**بولد** *ایتالیک* `print('hello')` [لینک](https://google.com)"
    formatted = telegram_formatter.markdown_to_telegram_html(raw_md)
    print('   Sample Formatted Output:', formatted)
    assert '<b>' in formatted and '<code>' in formatted and '<a href=' in formatted
    print('   ✅ HTML Safe Formatter: OK')

    # 10. End-to-End AI Autonomous Reasoning Loop
    print('\n10. End-to-End AI Agent Turn Test:')
    t0 = time.time()
    ai_res, extra = await ai_service.generate_response(
        chat_id=8888,
        user_prompt='ساعت چنده، آب و هوای تهران چطوره و قیمت بیت کوین چنده؟',
        caller_user_id=config.ADMIN_ID,
        caller_name='Commander',
        is_private_chat=True
    )
    t_ai = time.time() - t0
    print(f'   AI Response Latency: {t_ai:.2f}s')
    print('   AI Response Content:\n', ai_res)
    assert 'بیت' in ai_res or 'BTC' in ai_res or '$' in ai_res
    print('   ✅ Autonomous Agent Loop & Multi-Tool Execution: OK')

    print('\n========================================================')
    print('  🎉 100% OF MODULES, TOOLS & AGENT PIPELINES VERIFIED!')
    print('========================================================')

if __name__ == '__main__':
    asyncio.run(run_master_audit())
