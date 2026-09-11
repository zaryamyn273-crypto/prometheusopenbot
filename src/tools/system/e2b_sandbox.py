"""E2B Cloud Sandbox — isolated code/command execution in the cloud.

Optional dependency: works only when E2B_API_KEY is set + `e2b-code-interpreter`
is installed. Otherwise every tool returns a clear Persian guide message and
the caller (execute_python_code) falls back to the local multiprocessing sandbox.

Get a key: https://e2b.dev/dashboard?tab=keys  (format e2b_...)

Design notes for Railway-simple deploys:
- Lazy imports everywhere: missing pip package never crashes the bot.
- Per-call AsyncSandbox (no global reuse): E2B sandboxes are stateful and
  billed per lifetime; short-lived per-call sandboxes are the documented pattern
  and avoid leaking state between admin turns.
- Timeouts are enforced on BOTH the E2B run (timeout=) and the surrounding
  asyncio.wait_for so a hung sandbox can never hang the Telegram handler.
- Secrets are masked in outputs; .env/token access is rejected before dispatch.
"""
import asyncio
import logging
from typing import Any, Optional

from src.tools.registry import register_tool
from src.core.config import ADMIN_ID

logger = logging.getLogger(__name__)

_E2B_MISSING_MSG = (
    "⚠️ *سندباکس ابری E2B فعال نیست.*\n\n"
    "برای اجرای ایزوله در کلاد:\n"
    "۱. از https://e2b.dev/dashboard?tab=keys کلید بگیرید (`e2b_...`)\n"
    "۲. در Railway متغیر `E2B_API_KEY` را ست کنید\n"
    "۳. `pip install e2b-code-interpreter` (داخل requirements هست)\n\n"
    "تا آن موقع از سندباکس لوکال استفاده می‌شود."
)

_DANGER_TOKENS = (
    ".env", "telegram_bot_token", "router_api_key", "e2b_api_key",
    "cloudflare", "/etc/passwd", "/etc/shadow",
)


def _is_admin(caller_id: int) -> bool:
    try:
        return int(caller_id or 0) == int(ADMIN_ID)
    except Exception:
        return False


def _clean_code_block(code: str) -> str:
    c = (code or "").strip()
    if c.startswith("```python"):
        c = c[9:]
    elif c.startswith("```"):
        c = c[3:]
    if c.endswith("```"):
        c = c[:-3]
    return c.strip()


def _has_e2b_key() -> bool:
    try:
        from src.core import config as _cfg
        return bool((_cfg.E2B_API_KEY or "").strip())
    except Exception:
        return False


def _reject_secrets_access(code_or_cmd: str) -> Optional[str]:
    low = (code_or_cmd or "").lower()
    if any(t in low for t in _DANGER_TOKENS):
        return "⛔ دسترسی به سکرت/توکن (.env و کلیدها) در سندباکس ابری ممنوع است."
    return None


def _format_execution(exec_obj: Any, backend: str) -> str:
    """Renders an e2b Execution into compact Telegram Markdown."""
    try:
        text = (getattr(exec_obj, "text", "") or "").strip()
    except Exception:
        text = ""
    try:
        logs = getattr(exec_obj, "logs", None)
        stdout = (getattr(logs, "stdout", "") or []) if logs else []
        stderr = (getattr(logs, "stderr", "") or []) if logs else []
        stdout_s = "\n".join(getattr(m, "text", str(m)) for m in (stdout or [])).strip()
        stderr_s = "\n".join(getattr(m, "text", str(m)) for m in (stderr or [])).strip()
    except Exception:
        stdout_s, stderr_s = "", ""
    try:
        err = getattr(exec_obj, "error", None)
        err_s = ""
        if err:
            err_s = getattr(err, "message", None) or getattr(err, "value", None) or str(err)
            err_s = str(err_s).strip()
    except Exception:
        err_s = ""

    # Prefer explicit result text, else stdout, else stderr/error.
    body = text or stdout_s
    if err_s and err_s not in body:
        body = (body + f"\n❌ {err_s}").strip() if body else f"❌ {err_s}"
    if not body and stderr_s:
        body = stderr_s
    if not body:
        body = "اجرا شد (بدون خروجی)."
    if len(body) > 3500:
        body = body[:3500] + "\n… [خروجی خلاصه شد]"
    badge = "☁️ *نتیجه سندباکس ابری E2B*:" if backend == "e2b" else "🐍 *نتیجه اجرا*:"
    return f"{badge}\n\n```\n{body}\n```"


async def _run_e2b_code(code: str, language: str = "python", timeout: Optional[int] = None) -> str:
    """Low-level E2B runner. Raises RuntimeError with Persian message on any failure."""
    if not _has_e2b_key():
        raise RuntimeError(_E2B_MISSING_MSG)
    try:
        from e2b_code_interpreter import AsyncSandbox
    except Exception as e:
        raise RuntimeError(
            "⚠️ پکیج `e2b-code-interpreter` نصب نیست.\n"
            f"`pip install e2b-code-interpreter` را اجرا کنید. ({e})"
        )
    lang = (language or "python").strip().lower()
    if lang in ("js", "javascript", "node"):
        lang = "javascript"
    else:
        lang = "python"
    try:
        from src.core import config as _cfg
        tmo = int(timeout or _cfg.E2B_TIMEOUT_SEC or 30)
        tmo = max(5, min(120, tmo))
        template = (_cfg.E2B_TEMPLATE or "").strip() or None
    except Exception:
        tmo, template = 30, None

    sandbox = None
    try:
        try:
            if template:
                sandbox = await AsyncSandbox.create(template=template)
            else:
                sandbox = await AsyncSandbox.create()
        except TypeError:
            # Older SDK without template kwarg.
            sandbox = await AsyncSandbox.create()
        except Exception as e:
            raise RuntimeError(f"❌ اتصال به E2B برقرار نشد: {e}")

        try:
            if lang == "python":
                execution = await asyncio.wait_for(
                    sandbox.run_code(code, timeout=float(tmo)), timeout=float(tmo + 15)
                )
            else:
                execution = await asyncio.wait_for(
                    sandbox.run_code(code, language=lang, timeout=float(tmo)), timeout=float(tmo + 15)
                )
        except asyncio.TimeoutError:
            raise RuntimeError(f"⏱ زمان اجرای E2B ({tmo}s) تمام شد.")
        return _format_execution(execution, "e2b")
    finally:
        if sandbox is not None:
            try:
                await sandbox.kill()
            except Exception:
                pass
            try:
                await sandbox.close()
            except Exception:
                pass


async def run_e2b_python(code: str, timeout: Optional[int] = None) -> str:
    """Shared entry used by execute_python_code for cloud-first execution."""
    return await _run_e2b_code(code, language="python", timeout=timeout)


@register_tool(
    name="e2b_run_code",
    description="اجرای ایزوله کد پایتون/جاوااسکریپت در سندباکس ابری E2B (مختص فرمانده ارشد؛ بدون کلید E2B_API_KEY غیرفعال است)",
    category="admin",
)
async def e2b_run_code(
    code: str,
    language: str = "python",
    timeout_sec: int = 30,
    caller_id: int = 0,
) -> str:
    """
    :param code: کد پایتون یا جاوااسکریپت برای اجرا در سندباکس ابری
    :param language: زبان اجرا (python یا javascript)
    :param timeout_sec: سقف اجرا به ثانیه (۵ تا ۱۲۰)
    """
    if not _is_admin(caller_id):
        return "⛔ دسترسی غیرمجاز! سندباکس E2B فقط در انحصار فرمانده ارشد است."
    clean = _clean_code_block(code)
    if not clean:
        return "کدی برای اجرا ارائه نشده است."
    if len(clean) > 20000:
        return "❌ حجم کد بیش از سقف ۲۰KB است."
    blocked = _reject_secrets_access(clean)
    if blocked:
        return blocked
    # Destructive shell patterns never run, even in the cloud.
    try:
        from src.tools.system import is_destructive_shell_command as _is_destr
        if _is_destr(clean):
            return "⛔ این دستور مخرب/حساس است و هرگز اجرا نمی‌شود (حتی به دستور ادمین)."
    except Exception:
        pass
    # Local AST guard for python before paying for a cloud sandbox.
    if (language or "python").lower().startswith("py"):
        try:
            from src.core.security import validate_python_code as _validate
            _validate(clean)
        except ValueError as e:
            return f"❌ خطای نگارشی (SyntaxError) در کد:\n{e}"
        except PermissionError as e:
            return f"⛔ کد به دلایل امنیتی مسدود شد:\n{e}"
    try:
        out = await _run_e2b_code(clean, language=language, timeout=timeout_sec)
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        logger.error(f"E2B run_code error: {e}")
        return f"❌ خطای سندباکس E2B: {e}"
    try:
        from src.core.security import sanitize_output as _san
        out = _san(out)
    except Exception:
        pass
    return out


@register_tool(
    name="e2b_run_command",
    description="اجرای ایزوله دستور شل لینوکس در سندباکس ابری E2B (مختص فرمانده ارشد؛ فایل‌سیستم ربات مصون می‌ماند)",
    category="admin",
)
async def e2b_run_command(
    command: str,
    timeout_sec: int = 30,
    caller_id: int = 0,
) -> str:
    """
    :param command: دستور شل لینوکس (مثل pip list یا python --version)
    :param timeout_sec: سقف اجرا به ثانیه (۵ تا ۶۰)
    """
    if not _is_admin(caller_id):
        return "⛔ دسترسی غیرمجاز! سندباکس E2B فقط در انحصار فرمانده ارشد است."
    cmd = (command or "").strip()
    if not cmd:
        return "دستوری برای اجرا ارائه نشده است."
    if len(cmd) > 2000:
        return "❌ طول دستور بیش از سقف مجاز است."
    blocked = _reject_secrets_access(cmd)
    if blocked:
        return blocked
    try:
        from src.tools.system import is_destructive_shell_command as _is_destr2
        if _is_destr2(cmd):
            return "⛔ این دستور مخرب/حساس است و هرگز اجرا نمی‌شود (حتی به دستور ادمین)."
    except Exception:
        pass
    if not _has_e2b_key():
        return _E2B_MISSING_MSG
    try:
        from e2b_code_interpreter import AsyncSandbox
    except Exception as e:
        return f"⚠️ پکیج `e2b-code-interpreter` نصب نیست. ({e})"
    try:
        from src.core import config as _cfg2
        tmo = max(5, min(60, int(timeout_sec or 30)))
        template = (_cfg2.E2B_TEMPLATE or "").strip() or None
    except Exception:
        tmo, template = 30, None

    sandbox = None
    try:
        try:
            sandbox = await AsyncSandbox.create(template=template) if template else await AsyncSandbox.create()
        except TypeError:
            sandbox = await AsyncSandbox.create()
        except Exception as e:
            return f"❌ اتصال به E2B برقرار نشد: {e}"
        try:
            proc = await asyncio.wait_for(
                sandbox.commands.run(cmd, timeout=float(tmo)), timeout=float(tmo + 15)
            )
        except asyncio.TimeoutError:
            return f"⏱ زمان اجرای دستور E2B ({tmo}s) تمام شد."
        except Exception as e:
            return f"❌ خطای اجرای دستور در E2B: {e}"
        try:
            stdout = (getattr(proc, "stdout", "") or "").strip()
            stderr = (getattr(proc, "stderr", "") or "").strip()
            code_c = getattr(proc, "exit_code", 0)
        except Exception:
            stdout, stderr, code_c = "", "", 0
        body = stdout or stderr or f"(exit code {code_c})"
        if len(body) > 3500:
            body = body[:3500] + "\n… [خروجی خلاصه شد]"
        out = f"☁️ *نتیجه شل ابری E2B (exit `{code_c}`)*:\n\n```\n{body}\n```"
    finally:
        if sandbox is not None:
            try:
                await sandbox.kill()
            except Exception:
                pass
            try:
                await sandbox.close()
            except Exception:
                pass
    try:
        from src.core.security import sanitize_output as _san2
        out = _san2(out)
    except Exception:
        pass
    return out


@register_tool(
    name="e2b_status",
    description="وضعیت اتصال سندباکس ابری E2B (نصب پکیج + کلید + ping واقعی)",
    category="admin",
)
async def e2b_status(caller_id: int = 0) -> str:
    if not _is_admin(caller_id):
        return "⛔ فقط فرمانده ارشد."
    try:
        import e2b_code_interpreter as _pkg
        ver = getattr(_pkg, "__version__", "?")
        pkg_txt = f"🟢 نصب است (`{ver}`)"
    except Exception:
        return f"🔴 پکیج نصب نیست + کلید {'ست شده' if _has_e2b_key() else 'ست نشده'}.\n{_E2B_MISSING_MSG}"
    if not _has_e2b_key():
        return f"🟡 پکیج {pkg_txt} ولی `E2B_API_KEY` خالی است.\n{_E2B_MISSING_MSG}"
    # Live ping: tiny sandbox run proves key + network both work.
    try:
        from e2b_code_interpreter import AsyncSandbox
        sb = await AsyncSandbox.create()
        try:
            ex = await asyncio.wait_for(sb.run_code("print('e2b-ok')", timeout=15.0), timeout=30.0)
            ok = "e2b-ok" in ((getattr(ex, "text", "") or "") + str(getattr(getattr(ex, "logs", None), "stdout", "")))
        finally:
            try:
                await sb.kill()
            except Exception:
                pass
            try:
                await sb.close()
            except Exception:
                pass
        return "🟢 *E2B متصل و سالم است.* ping موفق." if ok else "🟡 کلید ست است ولی ping ناموفق بود."
    except Exception as e:
        return f"🔴 خطای اتصال E2B: {e}"
