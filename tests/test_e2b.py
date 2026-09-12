import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
"""Lightweight E2B sandbox tests — safe on Railway free tiers.

- Without E2B_API_KEY or without the `e2b-code-interpreter` package:
  every case SKIPs (exit 0), tools must return a Persian guide message.
- With a key: runs one tiny cloud execution (print) + status ping.
- Never sends Telegram messages, never touches D1/KV.
"""
import asyncio

from src.core.config import ADMIN_ID
ADMIN = ADMIN_ID or 123456789


def _has_key() -> bool:
    try:
        from src.core.config import has_e2b
        return bool(has_e2b())
    except Exception:
        return False


def _has_pkg() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("e2b_code_interpreter") is not None
    except Exception:
        return False


async def _run():
    # Lazy registry: nothing is registered on plain import anymore —
    # tests needing the full cabinet call ensure_all() explicitly.
    from src.tools.registry import REGISTRY, execute_registered_tool, ensure_all
    ensure_all()

    # NOTE: caller_id must be passed as kwarg — execute_registered_tool injects
    # it into the tool call from there, NOT from the args dict.
    async def _call(name, args, cid=ADMIN):
        return await execute_registered_tool(name, dict(args), caller_id=cid)

    for name in ("e2b_run_code", "e2b_run_command", "e2b_status"):
        assert name in REGISTRY, f"tool not registered: {name}"
    print("  registry: e2b tools present")

    # 1. Admin gate: non-admin must be rejected without any cloud call.
    out = await _call("e2b_run_code", {"code": "print(1)"}, cid=0)
    assert "غیرمجاز" in str(out), f"admin gate broken: {out}"
    out = await _call("e2b_run_command", {"command": "whoami"}, cid=0)
    assert "غیرمجاز" in str(out), f"admin gate broken: {out}"
    print("  admin gate: OK")

    # 2. Secret access rejected before any cloud dispatch.
    out = await _call("e2b_run_code", {"code": "print(open('.env').read())"})
    assert "ممنوع" in str(out) or "مسدود" in str(out), f"secret guard broken: {out}"
    print("  secret guard: OK")

    # 3. Destructive commands never run, even in the cloud.
    out = await _call("e2b_run_command", {"command": "rm -rf / --no-preserve-root"})
    assert "هرگز" in str(out) or "مخرب" in str(out), f"destructive guard broken: {out}"
    print("  destructive guard: OK")

    if not _has_key() or not _has_pkg():
        print("  SKIP live cloud run (no E2B_API_KEY or package). Guide message check:")
        out = await _call("e2b_run_code", {"code": "print(2+2)"})
        s = str(out)
        assert ("فعال نیست" in s) or ("نصب نیست" in s) or ("2" in s and "4" in s), f"unexpected: {s}"
        print("  offline guide: OK")
        return

    # 4. Live ping (only with key + package).
    out = await _call("e2b_status", {})
    print(f"  live status: {str(out)[:120]}")
    out = await _call("e2b_run_code", {"code": "print(40+2)", "timeout_sec": 25})
    assert "42" in str(out), f"live run failed: {out}"
    print("  live run: OK (42 found)")


def main() -> int:
    print("== E2B sandbox test ==")
    asyncio.run(_run())
    print("== E2B test DONE ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
