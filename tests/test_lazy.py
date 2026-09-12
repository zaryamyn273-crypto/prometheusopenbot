import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
"""Lazy-loading architecture tests.

Proves that at any moment only the needed tools/modules are active:
- importing src.tools registers NOTHING (zero tool modules loaded).
- category ensure loads exactly its owner modules (weather != media).
- smart schema selection under lazy == under eager (no behavior drift).
- execute_* auto-loads the owner module on demand.
- importing bot pulls neither ai_service (PIL) nor any tool module.
- _triage_fast_turn answers trivial turns with minimal machinery.

Subprocess isolation is used where import state matters: each probe runs in
a FRESH interpreter (sys.executable -c) so earlier imports can't leak in.
"""
import json
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
BASE_ENV = {
    "TELEGRAM_BOT_TOKEN": "dummy",
    "ADMIN_ID": "123",
    "ROUTER_API_KEY": "dummy",
}


def _run(code: str) -> str:
    env = dict(os.environ)
    env.update(BASE_ENV)
    p = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert p.returncode == 0, f"probe crashed:\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr[-2000:]}"
    return p.stdout.strip()


def test_nothing_loaded_at_import():
    out = _run(
        "import sys; import src.tools as T; "
        "from src.tools.registry import REGISTRY; "
        "mods=[m for m in sys.modules if m.startswith('src.tools.') and m != 'src.tools.registry']; "
        "print(len(REGISTRY)); print('MODS:' + ','.join(sorted(mods)))"
    )
    lines = out.splitlines()
    assert lines[0] == "0", f"registry not empty at import: {lines[0]}"
    assert lines[1] == "MODS:", f"tool modules loaded at import: {lines[1]}"
    print("  import loads zero tools/modules: OK")


def test_category_loads_only_owners():
    out = _run(
        "import sys; from src.tools.registry import REGISTRY, ensure_category; "
        "ensure_category('weather'); "
        "print('get_weather' in REGISTRY); "
        "print('download_music_track' in REGISTRY); "
        "print('src.tools.media' in sys.modules); "
        "print('src.tools.web_network' in sys.modules)"
    )
    assert out.splitlines() == ["True", "False", "False", "True"], out
    print("  weather loads web_network only (no media): OK")


def test_lazy_eager_parity():
    prompts = ["هوای تهران چطوره", "قیمت بیت کوین چنده", "سلام",
               " alkalmi جوک بگو ".strip(), "آهنگ شاد بذار"]
    code = (
        "import sys, json; "
        "from src.tools.registry import get_smart_tools_for_prompt, ensure_all, REGISTRY; "
        "prompts = %s; "
        "lazy = [[(s['function']['name']) for s in get_smart_tools_for_prompt(p)] for p in prompts]; "
        "ensure_all(); "
        "eager = [[(s['function']['name']) for s in get_smart_tools_for_prompt(p)] for p in prompts]; "
        "print(json.dumps(lazy == eager)); print(json.dumps([len(x) for x in eager]))"
    ) % json.dumps(prompts)
    out = _run(code)
    lines = out.splitlines()
    assert lines[0] == "true", f"lazy/eager drift: {lines}"
    print(f"  lazy==eager schemas {lines[1]}: OK")


def test_execute_loads_on_demand():
    out = _run(
        "import sys, asyncio; "
        "from src.tools.registry import REGISTRY, execute_registered_tool; "
        "before = 'src.tools.scientific' in sys.modules; "
        "r = asyncio.run(execute_registered_tool('generate_uuid', {'count': 1})); "
        "print(before); print('src.tools.scientific' in sys.modules); "
        "print('generate_uuid' in REGISTRY)"
    )
    assert out.splitlines() == ["False", "True", "True"], out
    print("  execute auto-loads owner module: OK")


def test_bot_import_stays_light():
    out = _run(
        "import sys; import bot; "
        "print('src.core.ai_service' in sys.modules); "
        "print('src.tools.financial' in sys.modules); "
        "print('src.tools.media' in sys.modules); "
        "print('src.tools.system' in sys.modules); "
        "print('PIL' in sys.modules or 'PIL.Image' in sys.modules); "
        "print('telegram' in sys.modules)"
    )
    lines = out.splitlines()
    assert lines == ["False", "False", "False", "False", "False", "True"], lines
    print("  bot import skips ai_service/PIL/tool modules: OK")


def test_triage_tiers():
    import asyncio
    import bot

    class _M:
        reply_to_message = None

    class _C:
        id = -1001
        title = "t"

    class _U:
        id = 999
        language_code = "fa"
        first_name = "u"

    async def go(text, lang="fa", image=False, reply=False):
        u = _U()
        u.language_code = lang
        m = _M()
        if reply:
            m.reply_to_message = object()
        return await bot._triage_fast_turn(m, _C(), u, text, "u", lang, image, reply)

    assert asyncio.run(go("ساعت چنده"))[0].startswith("⏰")
    assert asyncio.run(go("what time is it", lang="en"))[0].startswith("⏰")
    assert asyncio.run(go("سلام"))[0].startswith("سلام")
    assert asyncio.run(go("thanks", lang="en"))[0].startswith("You're welcome")
    # gates: reply / image / long text fall through to Tier 2
    assert asyncio.run(go("ساعت چنده", reply=True)) is None
    assert asyncio.run(go("ساعت", image=True)) is None
    assert asyncio.run(go("x" * 60)) is None
    assert asyncio.run(go(" possibly a complex multi intent question about economy? ".strip())) is None
    print("  triage tiers + gates: OK")


def main() -> int:
    print("== lazy architecture test ==")
    test_nothing_loaded_at_import()
    test_category_loads_only_owners()
    test_lazy_eager_parity()
    test_execute_loads_on_demand()
    test_bot_import_stays_light()
    test_triage_tiers()
    print("== lazy test DONE ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
