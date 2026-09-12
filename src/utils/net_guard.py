"""
Outbound-fetch safety: Robust SSRF Guard & Hop-by-Hop Redirect Validator.

Features:
- Blocks private, loopback, link-local, multicast, and reserved IP ranges (IPv4 & IPv6).
- Blocks cloud metadata endpoints (AWS, GCP, Azure, DigitalOcean, Alibaba).
- Blocks DNS rebinding by resolving all hostnames and verifying every resolved IP.
- Enforces hop-by-hop redirect validation (safe_http_get, safe_stream_get) to prevent 302 redirect SSRF.
- Strictly allows only http and https protocols.
"""

import ipaddress
import logging
import socket
import contextlib
from urllib.parse import urlparse, urljoin
from typing import Optional, Set

logger = logging.getLogger(__name__)

_BLOCKED_HOSTS_AND_SUFFIXES: Set[str] = {
    "localhost",
    "metadata.google.internal",
    "metadata.google.com",
    "railway.internal",
    "internal",
    "local",
    "lan",
    "home.arpa",
    "svc.cluster.local",
    "169.254.169.254",
    "instance-data",
}

# Explicitly blocked CIDRs for cloud metadata and internal virtualization networks
_METADATA_NETWORKS = [
    ipaddress.ip_network("169.254.0.0/16"),   # Link-Local / Cloud Metadata
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("10.0.0.0/8"),       # Private RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),    # Private RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),   # Private RFC 1918
    ipaddress.ip_network("0.0.0.0/8"),        # Current network
    ipaddress.ip_network("100.64.0.0/10"),    # Carrier-grade NAT
    ipaddress.ip_network("198.18.0.0/15"),    # Benchmark testing
]


def _is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    """Verifies that an IP address is genuinely public and not in any restricted range."""
    # Convert IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) to standard IPv4
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False

    if isinstance(ip, ipaddress.IPv4Address):
        for net in _METADATA_NETWORKS:
            if ip in net:
                return False
    elif isinstance(ip, ipaddress.IPv6Address):
        # Block IPv6 unique-local (fc00::/7) and link-local (fe80::/10)
        if ip in ipaddress.ip_network("fc00::/7") or ip in ipaddress.ip_network("fe80::/10"):
            return False

    return True


def assert_public_url(raw_url: str) -> str:
    """
    Validates an outbound URL against SSRF attacks.
    Returns the cleaned URL or raises ValueError.
    """
    clean = str(raw_url or "").strip()
    if not clean:
        raise ValueError("empty URL")

    # Force http/https scheme if omitted
    target = clean if "://" in clean else f"https://{clean}"
    try:
        parsed = urlparse(target)
    except Exception:
        raise ValueError("bad URL format")

    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("only http and https schemes allowed")

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("missing host in URL")

    # Hostname suffix blacklist
    if host in _BLOCKED_HOSTS_AND_SUFFIXES or any(host.endswith("." + s) for s in _BLOCKED_HOSTS_AND_SUFFIXES):
        raise ValueError("blocked target host")

    # IP Literal Check
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        if not _is_public_ip(literal):
            raise ValueError("blocked target IP literal")
        return target

    # DNS Resolution Check (Anti-DNS Rebinding)
    try:
        infos = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    except Exception:
        raise ValueError("cannot resolve host")

    addrs = {info[4][0] for info in infos}
    if not addrs:
        raise ValueError("cannot resolve host")

    for a in addrs:
        try:
            ip_obj = ipaddress.ip_address(a)
            if not _is_public_ip(ip_obj):
                logger.warning(f"SSRF Security Block: Host '{host}' resolved to restricted IP '{a}'")
                raise ValueError("blocked target resolved IP")
        except ValueError as ve:
            if "blocked" in str(ve):
                raise
            raise ValueError("blocked target resolved IP")

    return target


async def safe_http_get(client, url: str, timeout: float = 7.0, max_redirects: int = 5, **kwargs):
    """
    SSRF-Safe HTTP GET: Validates every redirect hop against assert_public_url.
    Prevents 302 redirect bypass to cloud metadata or internal network.
    """
    curr_url = assert_public_url(url)
    hops = 0

    while hops <= max_redirects:
        resp = await client.get(curr_url, timeout=timeout, follow_redirects=False, **kwargs)
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location")
            if not loc:
                return resp
            # Resolve relative redirects
            next_url = urljoin(curr_url, loc)
            # Validate next hop
            curr_url = assert_public_url(next_url)
            hops += 1
            continue
        return resp

    raise ValueError(f"Too many redirects ({hops} hops)")


@contextlib.asynccontextmanager
async def safe_stream_get(client, url: str, timeout: float = 7.0, max_redirects: int = 5, **kwargs):
    """
    SSRF-Safe streaming GET: Validates every redirect hop against assert_public_url.
    Prevents 302 redirect bypass during streaming.
    """
    curr_url = assert_public_url(url)
    hops = 0

    while hops <= max_redirects:
        async with client.stream("GET", curr_url, timeout=timeout, follow_redirects=False, **kwargs) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location")
                if not loc:
                    yield resp
                    return
                next_url = urljoin(curr_url, loc)
                curr_url = assert_public_url(next_url)
                hops += 1
                continue
            yield resp
            return

    raise ValueError(f"Too many redirects ({hops} hops)")
