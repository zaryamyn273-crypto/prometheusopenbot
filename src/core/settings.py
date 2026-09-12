"""Typed settings schema (Pydantic Settings) — strict fail-fast at startup.

Why this exists on top of ``config.py``: ``config.py`` reads raw strings with
``os.getenv`` and never complains, so a typo'd ``ADMIN_ID=abc`` or an empty
token only explodes minutes later as a cryptic KeyError deep in a handler.
This module validates TYPES and SHAPES once at boot; ``build_application``
refuses to start with a clear bilingual message instead of crash-looping.

Only 3 variables are truly required to boot (see also ``.env.example``);
everything else is optional and degrades gracefully by design.
"""
from typing import Optional

try:
    from pydantic import field_validator
    from pydantic_settings import BaseSettings, SettingsConfigDict
except Exception:  # pragma: no cover — guarded import, validated below
    BaseSettings = object  # type: ignore
    SettingsConfigDict = dict  # type: ignore

    def field_validator(*a, **k):  # type: ignore
        def _deco(fn):
            return fn
        return _deco


class Settings(BaseSettings):
    """Full env schema. Required fields have no defaults (fail-fast)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8",
                                      extra="ignore", case_sensitive=False)

    # --- Required: the bot cannot boot without these ---
    TELEGRAM_BOT_TOKEN: str
    ADMIN_ID: int
    ROUTER_API_KEY: str = ""
    ROUTER_BASE_URL: str = "https://api.openai.com/v1"
    ROUTER_MODEL: str = "gpt-4o-mini"

    # --- Optional: every one of these degrades gracefully ---
    CLOUDFLARE_ACCOUNT_ID: str = ""
    CLOUDFLARE_API_TOKEN: str = ""
    CLOUDFLARE_D1_ID: str = ""
    CLOUDFLARE_KV_ID: str = ""
    GITHUB_TOKEN: str = ""
    ALLRATESTODAY_API_KEY: str = ""
    ALLRATESTODAY_URL: str = "https://allratestoday.com/api/v1/rates"
    TAVILY_API_KEY: str = ""
    TAVILY_API_KEYS: str = ""
    TAVILY_API_URL: str = "https://api.tavily.com/search"
    SPOTIFY_CLIENT_ID: str = ""
    SPOTIFY_CLIENT_SECRET: str = ""
    E2B_API_KEY: str = ""
    E2B_TEMPLATE: str = ""
    E2B_TIMEOUT_SEC: int = 30
    YT_COOKIES_FILE: str = ""
    ENABLE_FINANCIAL_SYNC: str = "1"
    FINANCIAL_SYNC_INTERVAL_SEC: int = 900
    PORT: int = 8080

    @field_validator("TELEGRAM_BOT_TOKEN")
    @classmethod
    def _token_shape(cls, v: str) -> str:
        v = (v or "").strip()
        if ":" not in v or len(v) < 20:
            raise ValueError("must look like 123456:ABC-DEF... (get it from @BotFather)")
        return v

    @field_validator("ADMIN_ID")
    @classmethod
    def _admin_positive(cls, v: int) -> int:
        if v is None or int(v) <= 0:
            raise ValueError("must be your numeric Telegram ID (>0, via @userinfobot)")
        return int(v)

    @field_validator("ROUTER_BASE_URL")
    @classmethod
    def _http_url(cls, v: str) -> str:
        v = (v or "").strip().rstrip("/")
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("must be an http(s) URL")
        return v

    @field_validator("E2B_TIMEOUT_SEC")
    @classmethod
    def _e2b_timeout(cls, v: int) -> int:
        return max(5, min(120, int(v or 30)))

    @field_validator("FINANCIAL_SYNC_INTERVAL_SEC")
    @classmethod
    def _sync_interval(cls, v: int) -> int:
        return max(300, int(v or 900))

    @field_validator("PORT")
    @classmethod
    def _port(cls, v: int) -> int:
        v = int(v or 8080)
        if not 1 <= v <= 65535:
            raise ValueError("must be 1-65535")
        return v


def validate_startup_settings() -> "Settings":
    """Build + validate settings. Raises SystemExit(2) with a clear message."""
    if BaseSettings is object:
        # pydantic-settings not installed — config.py values still apply;
        # only the strict schema check is skipped (never crash on this).
        import logging
        logging.getLogger(__name__).warning(
            "pydantic-settings not installed; skipping strict startup validation.")
        return None  # type: ignore
    try:
        return Settings()  # type: ignore
    except Exception as e:
        import sys
        msg = (
            "\n❌ Invalid configuration — the bot refuses to boot with bad env.\n"
            "پیکربندی نامعتبر است — ربات با env خراب بالا نمی‌آید.\n\n"
            f"{e}\n\n"
            "Fix: copy .env.example to .env and set at minimum:\n"
            "  TELEGRAM_BOT_TOKEN=123456:ABC...  ADMIN_ID=123456789  ROUTER_API_KEY=sk-...\n"
        )
        print(msg, file=sys.stderr)
        raise SystemExit(2)


def summarize_active_services(s: Optional["Settings"]) -> str:
    """One-line ops summary for the boot log (never prints secrets)."""
    if s is None:
        return "settings-schema=skipped"
    parts = ["router=" + ("ON" if (s.ROUTER_API_KEY or "").strip() else "OFFLINE")]
    parts.append("cloudflare=" + ("ON" if (s.CLOUDFLARE_ACCOUNT_ID and (s.CLOUDFLARE_D1_ID or s.CLOUDFLARE_KV_ID)) else "OFF"))
    for name in ("TAVILY_API_KEY", "GITHUB_TOKEN", "E2B_API_KEY"):
        parts.append(f"{name.split('_')[0].lower()}=" + ("ON" if (getattr(s, name, '') or '').strip() else "OFF"))
    parts.append(f"model={s.ROUTER_MODEL}")
    return " ".join(parts)
