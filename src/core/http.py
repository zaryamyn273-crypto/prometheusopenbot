"""Shared HTTP layer: ONE pooled AsyncClient per profile (no per-call churn).

Profiles:
  - web:   general web/media crawling (12s timeout, browser UA)
  - api:   JSON APIs incl. Cloudflare (10s timeout)
  - fast:   latency-sensitive probes (5s timeout)
  - stream: large downloads with long read windows (75s timeout)
"""
import asyncio
import inspect
import random
import socket
import threading
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
import httpx

try:
    import h2  # noqa: F401
    _HTTP2_AVAILABLE = True
except ImportError:
    _HTTP2_AVAILABLE = False

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# Fallback and profile-tuned connection limits (tuned keepalive expiry avoids stale Cloudflare/proxy sockets)
_LIMITS = httpx.Limits(max_keepalive_connections=100, max_connections=300, keepalive_expiry=15.0)

_PROFILE_LIMITS: Dict[str, httpx.Limits] = {
    "web": httpx.Limits(max_keepalive_connections=100, max_connections=250, keepalive_expiry=15.0),
    "api": httpx.Limits(max_keepalive_connections=100, max_connections=300, keepalive_expiry=12.0),
    "fast": httpx.Limits(max_keepalive_connections=50, max_connections=150, keepalive_expiry=12.0),
    "stream": httpx.Limits(max_keepalive_connections=30, max_connections=80, keepalive_expiry=45.0),
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

# Base backoff factors in seconds for exponential backoff
_PROFILE_BACKOFF: Dict[str, float] = {
    "fast": 0.1,
    "api": 0.25,
    "web": 0.3,
    "stream": 0.5,
}

# HTTP/2 profile mapping: disabled for large streams where raw HTTP/1.1 TCP throughput
# avoids pure-python h2 frame handling and flow-control window stalls.
_PROFILE_HTTP2: Dict[str, bool] = {
    "web": _HTTP2_AVAILABLE,
    "api": _HTTP2_AVAILABLE,
    "fast": _HTTP2_AVAILABLE,
    "stream": False,
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
_STREAM_HEADERS = {
    "User-Agent": _BROWSER_UA,
    "Accept": "*/*",
}
_PROFILE_HEADERS: Dict[str, Dict[str, str]] = {
    "web": _WEB_HEADERS,
    "fast": _WEB_HEADERS,
    "api": _API_HEADERS,
    "stream": _STREAM_HEADERS,
}

# Probe underlying httpx transport capabilities at import time
_TRANSPORT_PARAMS = inspect.signature(httpx.AsyncHTTPTransport.__init__).parameters
_SUPPORTS_SOCKET_OPTIONS = "socket_options" in _TRANSPORT_PARAMS

_SOCKET_OPTIONS: Optional[Tuple[Tuple[int, int, int], ...]] = None
if _SUPPORTS_SOCKET_OPTIONS:
    try:
        opts: List[Tuple[int, int, int]] = [
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
            (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
        ]
        if hasattr(socket, "TCP_KEEPIDLE"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30))
        elif hasattr(socket, "TCP_KEEPALIVE"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, 30))
        if hasattr(socket, "TCP_KEEPINTVL"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10))
        if hasattr(socket, "TCP_KEEPCNT"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3))
        if hasattr(socket, "TCP_USER_TIMEOUT"):
            opts.append((socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, 30000))

        # Probe dummy socket to filter out options unsupported by host OS or container kernel
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        valid_opts: List[Tuple[int, int, int]] = []
        try:
            for opt in opts:
                try:
                    test_sock.setsockopt(*opt)
                    valid_opts.append(opt)
                except (OSError, ValueError):
                    pass
        finally:
            test_sock.close()
        _SOCKET_OPTIONS = tuple(valid_opts) if valid_opts else None
    except Exception:
        _SOCKET_OPTIONS = None


class BackoffAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """AsyncHTTPTransport with exponential backoff, jitter, and stale-socket resilience."""

    def __init__(
        self,
        *args: Any,
        max_retries: int = 2,
        backoff_factor: float = 0.25,
        **kwargs: Any,
    ) -> None:
        # Retries handled at transport level with exponential backoff rather than 0ms tight-loop
        super().__init__(*args, retries=0, **kwargs)
        self._max_retries = max(0, max_retries)
        self._backoff_factor = backoff_factor

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._max_retries <= 0:
            return await super().handle_async_request(request)

        attempt = 0
        while True:
            try:
                return await super().handle_async_request(request)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if attempt >= self._max_retries:
                    raise
                stream = getattr(request, "stream", None)
                can_replay = getattr(stream, "can_replay", None)
                if can_replay is not None and not can_replay():
                    raise
                delay = min(self._backoff_factor * (2 ** attempt) + random.uniform(0.01, 0.05), 2.5)
                attempt += 1
                await asyncio.sleep(delay)
            except (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError):
                # Stale pooled socket recovery: safe for idempotent requests
                if attempt >= self._max_retries or request.method not in ("GET", "HEAD", "OPTIONS"):
                    raise
                stream = getattr(request, "stream", None)
                can_replay = getattr(stream, "can_replay", None)
                if can_replay is not None and not can_replay():
                    raise
                # First idle/stale socket reset: retry immediately with minimal jitter to avoid human-perceptible latency
                if attempt == 0:
                    delay = random.uniform(0.02, 0.05)
                else:
                    delay = min(self._backoff_factor * (2 ** attempt) + random.uniform(0.01, 0.05), 2.5)
                attempt += 1
                await asyncio.sleep(delay)


_CLIENTS: Dict[str, httpx.AsyncClient] = {}
_CLIENT_LOOPS: Dict[str, asyncio.AbstractEventLoop] = {}
_PER_LOOP_CLIENTS: Dict[Tuple[str, int], httpx.AsyncClient] = {}
_LOOP_REFS: Dict[int, asyncio.AbstractEventLoop] = {}
_BUILD_LOCK = threading.Lock()


def _build(profile: str) -> httpx.AsyncClient:
    limits = _PROFILE_LIMITS.get(profile, _LIMITS)
    retries = _PROFILE_RETRIES.get(profile, 2)
    backoff = _PROFILE_BACKOFF.get(profile, 0.25)
    timeout = _TIMEOUTS.get(profile, _DEFAULT_TIMEOUT)
    headers = _PROFILE_HEADERS.get(profile, _WEB_HEADERS)

    transport_kwargs: Dict[str, Any] = {
        "limits": limits,
        "max_retries": retries,
        "backoff_factor": backoff,
        "http2": _PROFILE_HTTP2.get(profile, _HTTP2_AVAILABLE),
    }
    if _SOCKET_OPTIONS is not None:
        transport_kwargs["socket_options"] = _SOCKET_OPTIONS

    transport = BackoffAsyncHTTPTransport(**transport_kwargs)
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

    loop_id = id(current_loop) if current_loop is not None else 0
    key = (profile, loop_id)

    # Ultra-fast lock-free path: verify loop-specific client validity
    client = _PER_LOOP_CLIENTS.get(key)
    if client is not None and not client.is_closed:
        return client

    with _BUILD_LOCK:
        client = _PER_LOOP_CLIENTS.get(key)
        if client is not None and not client.is_closed:
            return client

        client = _build(profile)
        _PER_LOOP_CLIENTS[key] = client
        _CLIENTS[profile] = client
        if current_loop is not None:
            _CLIENT_LOOPS[profile] = current_loop
            _LOOP_REFS[loop_id] = current_loop
        else:
            _CLIENT_LOOPS.pop(profile, None)

        # Prune dead or closed clients to avoid memory growth across loop lifecycles
        dead_keys: List[Tuple[str, int]] = []
        for k, c in list(_PER_LOOP_CLIENTS.items()):
            loop_ref = _LOOP_REFS.get(k[1])
            if c.is_closed or (loop_ref is not None and loop_ref.is_closed()):
                dead_keys.append(k)
                if not c.is_closed:
                    try:
                        if current_loop is not None and current_loop.is_running():
                            current_loop.create_task(_safe_aclose(c))
                    except Exception:
                        pass
        for k in dead_keys:
            _PER_LOOP_CLIENTS.pop(k, None)
            _LOOP_REFS.pop(k[1], None)

        return client


async def _safe_aclose(client: httpx.AsyncClient) -> None:
    """Close an AsyncClient swallowing transport errors from dead or mismatched loops."""
    try:
        await client.aclose()
    except Exception:
        pass


@asynccontextmanager
async def shared_client_ctx(profile: str = "web") -> AsyncIterator[httpx.AsyncClient]:
    """`async with`-compatible wrapper around the shared client (never closes it)."""
    yield get_http_client(profile)

_acm = asynccontextmanager


async def aclose_all() -> None:
    with _BUILD_LOCK:
        all_clients = list(_PER_LOOP_CLIENTS.values()) + list(_CLIENTS.values())
        _PER_LOOP_CLIENTS.clear()
        _CLIENTS.clear()
        _CLIENT_LOOPS.clear()
        _LOOP_REFS.clear()

    seen: set = set()
    open_clients: List[httpx.AsyncClient] = []
    for client in all_clients:
        if client is not None and id(client) not in seen:
            seen.add(id(client))
            if not client.is_closed:
                open_clients.append(client)

    if open_clients:
        await asyncio.gather(*(_safe_aclose(client) for client in open_clients), return_exceptions=True)
