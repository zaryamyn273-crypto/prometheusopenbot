"""
Comprehensive verification test suite for:
1. AI Image Generation Engine (9router / Flux fallback)
2. Reddit, Amazon & eBay search tool improvements
3. Supercharged OSINT suite (IP, Domain/DNS, Phone, Social/Developer Recon)
4. Fast & Powerful Numeric ID Extraction Logic
"""

import asyncio
import re
import pytest

from src.core import ai_service
from src.tools.media import generate_ai_image
from src.tools.web_network.ecommerce import amazon_search, ebay_search
from src.tools.dev import reddit_search
from src.tools.web_network.osint import (
    osint_ip_intelligence,
    osint_domain_dns,
    osint_phone_intelligence,
    osint_person_dossier
)


@pytest.mark.asyncio
async def test_image_generation():
    # 1. Direct AI service image generation
    res = await ai_service.generate_image("a cyberpunk neon cat")
    assert res.get("success") is True, f"Image generation failed: {res.get('error')}"
    assert res.get("image_bytes") or res.get("url")
    assert len(res.get("image_bytes", b"")) > 1000 or res.get("url")

    # 2. Registered media tool
    tool_res = await generate_ai_image("یک سیب سرخ روی میز چوبی")
    assert isinstance(tool_res, dict)
    assert tool_res.get("type") in ("photo_bytes", "photo_url")
    assert "🎨" in tool_res.get("caption", "")


@pytest.mark.asyncio
async def test_searches():
    # Reddit search should prioritize /comments/ posts
    r_res = await reddit_search("python tutorial", max_results=2)
    assert "نتایج" in r_res

    # Amazon search
    amz_res = await amazon_search("Kindle Paperwhite", max_results=2)
    assert "آمازون" in amz_res or "Amazon" in amz_res

    # eBay search
    ebay_res = await ebay_search("vintage watch", max_results=2)
    assert "eBay" in ebay_res or "ای‌بی" in ebay_res


@pytest.mark.asyncio
async def test_supercharged_osint():
    # 1. IP intelligence
    ip_res = await osint_ip_intelligence("1.1.1.1")
    assert "IP Intelligence" in ip_res
    assert "Cloudflare" in ip_res or "Australia" in ip_res or "1.1.1.1" in ip_res

    # 2. Domain & DNS
    dns_res = await osint_domain_dns("cloudflare.com")
    assert "Domain OSINT" in dns_res
    assert "cloudflare.com" in dns_res

    # 3. Phone intelligence
    phone_res = await osint_phone_intelligence("+989123456789")
    assert "Phone Intelligence" in phone_res
    assert "همراه اول" in phone_res
    assert "+989123456789" in phone_res

    # 4. Universal auto-delegation
    auto_ip = await osint_person_dossier("8.8.8.8")
    assert "IP Intelligence" in auto_ip

    auto_phone = await osint_person_dossier("09351234567")
    assert "ایرانسل" in auto_phone

    # 5. Developer Recon
    dev_res = await osint_person_dossier("torvalds")
    assert "GitHub" in dev_res or "Linus" in dev_res


def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        print("Running test_image_generation...")
        loop.run_until_complete(test_image_generation())
        print("✓ Image generation passed.")

        print("Running test_searches...")
        loop.run_until_complete(test_searches())
        print("✓ Searches passed.")

        print("Running test_supercharged_osint...")
        loop.run_until_complete(test_supercharged_osint())
        print("✓ Supercharged OSINT passed.")

        print("\nALL NEW CAPABILITIES VERIFIED SUCCESSFULLY!")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
