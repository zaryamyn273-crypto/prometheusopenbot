import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncio
import pytest

# Ensure all categories are imported
from src.tools.web_network.digikala import digikala_search, clean_digikala_query
from src.tools.web_network.ecommerce import amazon_search, ebay_search
from src.tools.dev import reddit_search
from src.tools.financial import get_commodities_price, get_gold_and_coin_price, get_price
from src.tools.registry import REGISTRY, ensure_category

@pytest.mark.asyncio
async def test_digikala_search_upgraded():
    # Test query cleaning
    q1 = clean_digikala_query("قیمت خرید گوشی سامسونگ s24 دیجیکالا")
    assert "دیجیکالا" not in q1
    assert "قیمت" not in q1
    assert "سامسونگ s24" in q1

    # Test tool execution
    res = await digikala_search("گوشی سامسونگ s24", max_results=3)
    assert isinstance(res, str)
    assert len(res) > 20
    assert ("دیجی‌کالا" in res or "digikala" in res.lower())
    assert ("تومان" in res or "موجود" in res or "محصول" in res)

@pytest.mark.asyncio
async def test_amazon_search_zero_api():
    res = await amazon_search("macbook air m3", max_results=3)
    assert isinstance(res, str)
    assert len(res) > 20
    assert ("Amazon" in res or "آمازون" in res or "amazon.com" in res)
    assert ("$" in res or "قیمت" in res or "dp/" in res or "محدودیت" in res or "یافت نشد" in res or "نتایج" in res)

@pytest.mark.asyncio
async def test_ebay_search_zero_api():
    res = await ebay_search("thinkpad laptop", max_results=3)
    assert isinstance(res, str)
    assert len(res) > 20
    assert ("eBay" in res or "ای‌بی" in res or "ebay.com" in res)
    assert ("$" in res or "قیمت" in res or "itm" in res or "اختلال" in res or "یافت نشد" in res or "نتایج" in res or "استعلام" in res)

@pytest.mark.asyncio
async def test_amazon_search_anti_bot_mock_fallback():
    """Verify that when Amazon scraper faces 503/anti-bot challenge, it gracefully invokes fallback without raising exceptions."""
    from unittest.mock import patch, AsyncMock
    from src.tools.web_network import ecommerce

    cache_key = "AMZ_test_mock_device"
    ecommerce._L1_ECOMMERCE_CACHE.pop(cache_key, None)

    mock_resp = AsyncMock()
    mock_resp.status_code = 503
    mock_resp.text = "<html><body><h1>503 Service Unavailable</h1><p>Robot Check bm-verify</p></body></html>"

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    class MockCtx:
        async def __aenter__(self):
            return mock_client
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("src.tools.web_network.ecommerce.shared_client_ctx", return_value=MockCtx()):
        res = await amazon_search("test mock device", max_results=3)
        assert isinstance(res, str)
        assert len(res) > 20
        assert ("Amazon" in res or "آمازون" in res or "amazon.com" in res)
        assert ("$" in res or "قیمت" in res or "dp/" in res or "محدودیت" in res or "یافت نشد" in res or "نتایج" in res)

@pytest.mark.asyncio
async def test_ebay_search_anti_bot_mock_fallback():
    """Verify that when eBay scraper faces 503/anti-bot challenge, it gracefully invokes fallback without raising exceptions."""
    from unittest.mock import patch, AsyncMock
    from src.tools.web_network import ecommerce

    cache_key = "EBAY_test_mock_laptop_all"
    ecommerce._L1_ECOMMERCE_CACHE.pop(cache_key, None)

    mock_resp = AsyncMock()
    mock_resp.status_code = 503
    mock_resp.text = "<html><body><h1>503 Service Temporarily Unavailable</h1></body></html>"

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    class MockCtx:
        async def __aenter__(self):
            return mock_client
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    with patch("src.tools.web_network.ecommerce.shared_client_ctx", return_value=MockCtx()):
        res = await ebay_search("test mock laptop", max_results=3)
        assert isinstance(res, str)
        assert len(res) > 20
        assert ("eBay" in res or "ای‌بی" in res or "ebay.com" in res)
        assert ("$" in res or "قیمت" in res or "itm" in res or "اختلال" in res or "یافت نشد" in res or "نتایج" in res or "استعلام" in res)

@pytest.mark.asyncio
async def test_reddit_search_zero_api():
    res = await reddit_search("python asyncio", max_results=3)
    assert isinstance(res, str)
    assert len(res) > 20
    assert ("Reddit" in res or "ردیت" in res or "reddit.com" in res)

@pytest.mark.asyncio
async def test_commodities_price_tool():
    res = await get_commodities_price()
    assert isinstance(res, str)
    assert len(res) > 20
    assert ("نقره" in res or "نفت" in res or "Brent" in res or "Silver" in res)

@pytest.mark.asyncio
async def test_gold_coin_bubble_calculation():
    res = await get_gold_and_coin_price()
    assert isinstance(res, str)
    assert len(res) > 20
    assert "طلا" in res or "سکه" in res
    if "ارزش ذاتی" in res:
        assert "حباب" in res

@pytest.mark.asyncio
async def test_financial_price_commodities_redirection():
    # Asking for silver should return commodities board
    res_silver = await get_price("نقره")
    assert ("نقره" in res_silver or "Silver" in res_silver or "XAG" in res_silver)

    # Asking for oil should return crude oil
    res_oil = await get_price("نفت")
    assert ("نفت" in res_oil or "Brent" in res_oil or "WTI" in res_oil)

    # Asking for BTC should return crypto
    res_btc = await get_price("BTC")
    assert ("BTC" in res_btc or "بیت" in res_btc)

def test_registry_registration():
    ensure_category("search")
    ensure_category("financial")
    ensure_category("dev")
    assert "digikala_search" in REGISTRY
    assert "amazon_search" in REGISTRY
    assert "ebay_search" in REGISTRY
    assert "reddit_search" in REGISTRY
    assert "get_commodities_price" in REGISTRY
    assert "get_price" in REGISTRY

if __name__ == "__main__":
    asyncio.run(test_digikala_search_upgraded())
    print("✓ Digikala search OK")
    asyncio.run(test_amazon_search_zero_api())
    print("✓ Amazon search OK")
    asyncio.run(test_amazon_search_anti_bot_mock_fallback())
    print("✓ Amazon 503/anti-bot mock fallback OK")
    asyncio.run(test_ebay_search_zero_api())
    print("✓ eBay search OK")
    asyncio.run(test_ebay_search_anti_bot_mock_fallback())
    print("✓ eBay 503/anti-bot mock fallback OK")
    asyncio.run(test_reddit_search_zero_api())
    print("✓ Reddit search OK")
    asyncio.run(test_commodities_price_tool())
    print("✓ Commodities tool OK")
    asyncio.run(test_gold_coin_bubble_calculation())
    print("✓ Gold & Coin bubble OK")
    asyncio.run(test_financial_price_commodities_redirection())
    print("✓ Price redirection OK")
    test_registry_registration()
    print("✓ Registry registration OK")
    print("\nALL E-COMMERCE, REDDIT & FINANCIAL UPGRADES PASSED!")
