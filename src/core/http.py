"""Shared HTTP layer: ONE pooled AsyncClient per profile (no per-call churn).

Profiles:
  - web:   general web/media crawling (12s timeout, browser UA)
  - api:   JSON APIs incl. Cloudflare (10s timeout)
  - fast:   latency-sensitive probes (5s timeout)
  - stream: large downloads with long read windows (75s timeout)
"""
import asyncio
import threading
from typing import Dict, Optional
import httpx

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# Fallback and profile-tuned connection limits
_LIMITS = httpx.Limits(max_keepalive_connections=100, max_connections=300, keepalive_expiry=30.0)

_PROFILE_LIMITS: Dict[str, httpx.Limits] = {
    "web": httpx.Limits(max_keepalive_connections=60, max_connections=200, keepalive_expiry=30.0),
    "api": httpx.Limits(max_keepalive_connections=50, max_connections=150, keepalive_expiry=25.0),
    "fast": httpx.Limits(max_keepalive_connections=30, max_connections=100, keepalive_expiry=15.0),
    "stream": httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=45.0),
}

# Granular connect/pool/read timeouts prevent hanging socket handshakes
_TIMEOUTS: Dict[str, httpx.Timeout] = {
    "fast": httpx.Timeout(5.0, connect=2.0, pool=3.0),
    "api": httpx.Timeout(10.0, connect=4.0, pool=5.0),
    "web": httpx.Timeout(12.0, connect=5.0, pool=5.0),
    "stream": httpx.Timeout(75.0, connect=10.0, read=75.0, pool=10.0),
}
_DEFAULT_TIMEOUT = httpx.Timeout(12.0, connect=5.0, pool=5.0)

# Transport-level retry configuration for idempotent network resets on stale pooled sockets
_PROFILE_RETRIES: Dict[str, int] = {
    "fast": 1,
    "api": 3,
    "web": 2,
    "stream": 1,
}

# Pre-allocated immutable headers avoiding per-call dict allocations
_WEB_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
}
_API_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "application/json,*/*;q=0.8",
}

_CLIENTS: Dict[str, httpx.AsyncClient] = {}
_CLIENT_LOOPS: Dict[str, asyncio.AbstractEventLoop] = {}
_BUILD_LOCK = threading.Lock()


def _build(profile: str) -> httpx.AsyncClient:
    limits = _PROFILE_LIMITS.get(profile, _LIMITS)
    retries = _PROFILE_RETRIES.get(profile, 2)
    timeout = _TIMEOUTS.get(profile, _DEFAULT_TIMEOUT)
    headers = _WEB_HEADERS if profile in ("web", "fast") else _API_HEADERS
    transport = httpx.AsyncHTTPTransport(limits=limits, retries=retries)
    return httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    )


def get_http_client(profile: str = "web") -> httpx.AsyncClient:
    try:
        current_loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    client = _CLIENTS.get(profile)
    client_loop = _CLIENT_LOOPS.get(profile)

    # Fast lock-free path: verify client open status and loop affinity
    if (
        client is not None
        and not client.is_closed
        and (
            current_loop is None
            or client_loop is None
            or (client_loop is current_loop and not client_loop.is_closed())
        )
    ):
        if client_loop is None and current_loop is not None:
            _CLIENT_LOOPS[profile] = current_loop
        return client

    with _BUILD_LOCK:
        client = _CLIENTS.get(profile)
        client_loop = _CLIENT_LOOPS.get(profile)
        if (
            client is None
            or client.is_closed
            or (
                current_loop is not None
                and client_loop is not None
                and (client_loop is not current_loop or client_loop.is_closed())
            )
        ):
            client = _build(profile)
            _CLIENTS[profile] = client
            if current_loop is not None:
                _CLIENT_LOOPS[profile] = current_loop
        elif client_loop is None and current_loop is not None:
            _CLIENT_LOOPS[profile] = current_loop
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
    with _BUILD_LOCK:
        items = list(_CLIENTS.items())
        _CLIENTS.clear()
        _CLIENT_LOOPS.clear()

    if items:
        await asyncio.gather(*(client.aclose() for _, client in items), return_exceptions=True)
