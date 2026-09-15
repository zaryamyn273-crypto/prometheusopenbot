from src.core.config import (
    TELEGRAM_BOT_TOKEN,
    ADMIN_ID,
    ADMIN_IDS,
    is_admin_id,
    get_admin_ids,
    ROUTER_BASE_URL,
    ROUTER_INTERNAL_BASE_URL,
    ROUTER_API_KEY,
    ROUTER_MODEL,
    ROUTER_FAST_MODEL,
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_D1_ID,
    CLOUDFLARE_KV_ID,
    GITHUB_TOKEN,
    ALLRATESTODAY_API_KEY,
    SYSTEM_PROMPT,
    ENABLE_FINANCIAL_SYNC,
    FINANCIAL_SYNC_INTERVAL_SEC,
    has_router,
    has_tavily,
    has_cloudflare,
    E2B_API_KEY,
    E2B_TEMPLATE,
    E2B_TIMEOUT_SEC,
    has_e2b,
)
from src.core import database
# NOTE: ai_service is intentionally NOT imported here — it pulls PIL/httpx and
# is only needed for full AI turns. Access via `from src.core import ai_service`
# (lazy __getattr__ below) or `from src.core.ai_service import …` directly.
import importlib as _importlib


def __getattr__(name: str):
    if name == "ai_service":
        return _importlib.import_module("src.core.ai_service")
    raise AttributeError(f"module 'src.core' has no attribute {name!r}")

__all__ = [
    "TELEGRAM_BOT_TOKEN",
    "ADMIN_ID",
    "ADMIN_IDS",
    "is_admin_id",
    "get_admin_ids",
    "ROUTER_BASE_URL",
    "ROUTER_INTERNAL_BASE_URL",
    "ROUTER_API_KEY",
    "ROUTER_MODEL",
    "ROUTER_FAST_MODEL",
    "CLOUDFLARE_ACCOUNT_ID",
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_D1_ID",
    "CLOUDFLARE_KV_ID",
    "GITHUB_TOKEN",
    "ALLRATESTODAY_API_KEY",
    "SYSTEM_PROMPT",
    "ENABLE_FINANCIAL_SYNC",
    "FINANCIAL_SYNC_INTERVAL_SEC",
    "has_router",
    "has_tavily",
    "has_cloudflare",
    "E2B_API_KEY",
    "E2B_TEMPLATE",
    "E2B_TIMEOUT_SEC",
    "has_e2b",
    "database",
    "ai_service"
]
