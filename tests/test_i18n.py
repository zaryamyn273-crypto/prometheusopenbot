import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
"""i18n layer tests — fully offline, no keys, no network.

- fa/en dictionaries have identical key sets (no missing translations).
- Language detection maps Telegram codes correctly.
- translate_text() degrades gracefully: fa passthrough + no-key passthrough.
- EN fast-path triggers actually match in _try_fast_market_match.
"""
import asyncio


def test_dict_parity():
    from src.core.i18n import STRINGS
    assert set(STRINGS.keys()) == {"fa", "en"}, STRINGS.keys()
    fa_keys, en_keys = set(STRINGS["fa"]), set(STRINGS["en"])
    assert fa_keys == en_keys, f"missing: fa-only={fa_keys - en_keys} en-only={en_keys - fa_keys}"
    for lang, pack in STRINGS.items():
        for k, v in pack.items():
            assert isinstance(v, str) and v.strip(), f"empty string {lang}.{k}"
    print(f"  dict parity: OK ({len(fa_keys)} keys x fa/en)")


def test_normalize_and_names():
    from src.core.i18n import normalize_lang, lang_name, t
    assert normalize_lang("fa") == "fa"
    assert normalize_lang("fa-IR") == "fa"
    assert normalize_lang("en") == "en"
    assert normalize_lang("ru") == "en"      # chrome fallback
    assert normalize_lang("") == "en"
    assert normalize_lang(None) == "en"
    assert lang_name("fa") == "Persian (Farsi)"
    assert lang_name("ru") == "Russian"
    assert lang_name("es") == "Spanish"
    assert lang_name("fr") == "French"
    assert lang_name("xx-unknown") == "English"
    assert "ساعت" in t("fa", "time_is", hm="12:00")
    assert "Tehran" in t("en", "time_is", hm="12:00")
    assert t("en", "no_such_key") == "no_such_key"  # graceful fallback
    print("  normalize/names/t: OK")


def test_translate_graceful():
    from src.core.ai_service import translate_text
    # fa target -> passthrough, no LLM call
    out = asyncio.run(translate_text("سلام دنیا", "Persian (Farsi)"))
    assert out == "سلام دنیا", out
    # no ROUTER_API_KEY in this env -> original returned
    assert "ROUTER_API_KEY" not in (os.getenv("ROUTER_API_KEY") or "")
    out2 = asyncio.run(translate_text("قیمت دلار", "English"))
    assert out2 == "قیمت دلار", out2
    print("  translate graceful fallback: OK")


def test_fast_path_triggers():
    from src.core.ai_service import _try_fast_market_match
    # EN triggers must hit (returns coroutine result, not None)
    for q in ("dollar price", "bitcoin price", "gold price", "crypto market"):
        hit = asyncio.run(_try_fast_market_match(q))
        assert hit is not None, f"EN trigger missed: {q!r}"
    # FA triggers still hit
    for q in ("قیمت دلار", "قیمت بیت کوین", "قیمت طلا"):
        hit = asyncio.run(_try_fast_market_match(q))
        assert hit is not None, f"FA trigger missed: {q!r}"
    # Analysis questions must NOT fast-path (both languages)
    assert asyncio.run(_try_fast_market_match("should i buy bitcoin")) is None
    assert asyncio.run(_try_fast_market_match("بیت کوین بخرم؟")) is None
    print("  fast-path EN+FA triggers: OK")


def main() -> int:
    print("== i18n test ==")
    test_dict_parity()
    test_normalize_and_names()
    test_translate_graceful()
    test_fast_path_triggers()
    print("== i18n test DONE ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
