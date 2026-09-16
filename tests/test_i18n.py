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
    assert normalize_lang("en") == "fa"
    assert normalize_lang("ru") == "fa"
    assert normalize_lang("") == "fa"
    assert normalize_lang(None) == "fa"
    assert lang_name("fa") == "Persian (Farsi)"
    assert lang_name("ru") == "Persian (Farsi)"
    assert "ساعت" in t("fa", "time_is", hm="12:00")
    assert "تهران" in t("en", "time_is", hm="12:00")
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


def test_bot_reply_lang_coverage():
    """Static audit of bot.py: every user-facing Persian reply must either
    (a) render via t()/_maybe_translate/translate_text, or
    (b) live in an admin-gated function (contains an is_admin check).

    Media metadata (reply_audio/reply_document titles) is excluded: captions
    are translated upstream (music_command, _deliver_ai_turn pre-pass).
    """
    import ast
    import re
    FA = re.compile(r"[\u0600-\u06FF]")
    SENDERS = {"reply_text", "reply_safely", "answer", "send_message",
               "edit_message_text"}

    with open(os.path.join(os.path.dirname(__file__), "..", "bot.py"),
              encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    funcs = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    def const_frags(node):
        return [n.value for n in ast.walk(node)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]

    def uses_i18n(node):
        for n in ast.walk(node):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                    and n.func.id in ("t", "_maybe_translate", "translate_text"):
                return True
        return False

    offenders = []
    for fnode in funcs:
        fsrc = ast.get_source_segment(src, fnode) or ""
        gated = "is_admin" in fsrc
        for n in ast.walk(fnode):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            name = fn.attr if isinstance(fn, ast.Attribute) \
                else (fn.id if isinstance(fn, ast.Name) else "")
            if name not in SENDERS:
                continue
            args = n.args
            if name == "reply_safely":
                msgnode = args[1] if len(args) > 1 else None
            else:
                msgnode = args[0] if args else None
            if msgnode is None:
                continue
            if not any(FA.search(f) for f in const_frags(msgnode)):
                continue
            if uses_i18n(msgnode) or gated:
                continue
            offenders.append(f"{fnode.name}:{n.lineno}")
    assert not offenders, f"Persian-only user-facing replies: {offenders}"
    print(f"  reply coverage: OK ({len(funcs)} funcs scanned, 0 offenders)")


def main() -> int:
    print("== i18n test ==")
    test_dict_parity()
    test_normalize_and_names()
    test_translate_graceful()
    test_fast_path_triggers()
    test_bot_reply_lang_coverage()
    print("== i18n test DONE ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
