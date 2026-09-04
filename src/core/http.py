"""Shared HTTP layer: ONE pooled AsyncClient per profile (no per-call churn).

Profiles:
  - web:   general web/media crawling (12s timeout, browser UA)
  - api:   JSON APIs incl. Cloudflare (10s timeout)
  - fast:   latency-sensitive probes (5s timeout)
  - stream: large downloads with long read windows (75s timeout)
"""
import httpx
from typing import Dict, Optional

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_LIMITS = httpx.Limits(max_keepalive_connections=150, max_connections=300, keepalive_expiry=300.0)

_CLIENTS: Dict[str, httpx.AsyncClient] = {}


def _build(profile: str) -> httpx.AsyncClient:
    timeout = {"fast": 5.0, "api": 10.0, "web": 12.0, "stream": 75.0}.get(profile, 12.0)
    headers = {"User-Agent": _BROWSER_UA}
    if profile in ("web", "fast"):
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        headers["Accept-Language"] = "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7"
    else:
        headers["Accept"] = "application/json,*/*;q=0.8"
    return httpx.AsyncClient(limits=_LIMITS, timeout=timeout, headers=headers, follow_redirects=True)


def get_http_client(profile: str = "web") -> httpx.AsyncClient:
    client = _CLIENTS.get(profile)
    if client is None or client.is_closed:
        client = _build(profile)
        _CLIENTS[profile] = client
    return client


try:
    from contextlib import asynccontextmanager as _acm

    @_acm
    async def shared_client_ctx(profile: str = "web"):
        """`async with`-compatible wrapper around the shared client (never closes it)."""
        yield get_http_client(profile)
except Exception:  # pragma: no cover
    shared_client_ctx = None  # type: ignore


async def aclose_all() -> None:
    for profile, client in list(_CLIENTS.items()):
        try:
            await client.aclose()
        except Exception:
            pass
        _CLIENTS.pop(profile, None)
