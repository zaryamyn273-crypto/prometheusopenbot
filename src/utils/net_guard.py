"""Outbound-fetch safety: SSRF guard for every user-influenced URL.

Blocks private/loopback/link-local/reserved IP literals AND hostnames that
resolve to them (DNS rebinding), plus cloud metadata endpoints. The Railway
internal domain is blocked too — the bot must never probe its own platform.

Usage: ``from src.utils.net_guard import assert_public_url`` (raises
``ValueError`` on refusal) before any ``client.get/stream`` of a user URL.
"""
import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_BLOCKED_SUFFIXES = (
    "metadata.google.internal",
    "metadata.google.com",
    "railway.internal",
    "internal",
    "localhost",
    "svc.cluster.local",
)


def _is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    return (
        not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
    )


def assert_public_url(raw_url: str) -> str:
    """Validate an outbound URL. Returns the cleaned URL or raises ValueError."""
    try:
        clean = (raw_url or "").strip()
    except Exception:
        raise ValueError("empty URL")
    if not clean:
        raise ValueError("empty URL")
    try:
        parsed = urlparse(clean if "://" in clean else f"https://{clean}")
    except Exception:
        raise ValueError("bad URL")
    if parsed.scheme not in ("http", "https"):
        raise ValueError("only http/https allowed")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("bad URL")
    if host in ("localhost",):
        raise ValueError("blocked target")
    if any(host == s or host.endswith("." + s) for s in _BLOCKED_SUFFIXES):
        raise ValueError("blocked target")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not _is_public_ip(literal):
        raise ValueError("blocked target")
    if literal is None:
        try:
            infos = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
        except Exception:
            raise ValueError("cannot resolve host")
        addrs = {info[4][0] for info in infos}
        if not addrs:
            raise ValueError("cannot resolve host")
        for a in addrs:
            try:
                if not _is_public_ip(ipaddress.ip_address(a)):
                    logger.warning(f"SSRF block: {host} resolves to {a}")
                    raise ValueError("blocked target")
            except ValueError as ve:
                if str(ve) == "blocked target":
                    raise
                raise ValueError("blocked target")
    return clean
