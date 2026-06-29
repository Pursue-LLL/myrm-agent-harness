"""URL routing utilities for hybrid private/public network navigation.

Detects whether a URL targets a private/internal network address and provides
routing decisions for BrowserSession. Used in sandbox mode to transparently
fallback to Extension Bridge for private URLs that the sandbox Chromium cannot reach.

[INPUT]
(none — self-contained pure utility; SSRF checks use core.security.guards.ssrf)

[OUTPUT]
- is_private_url(url): Detect if URL targets a private/loopback/LAN address

[POS]
URL routing decision module. Determines whether a URL is private (needs Extension Bridge
fallback in sandbox mode) or public (reachable by sandbox Chromium directly).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_PRIVATE_HOSTNAME_EXACT: frozenset[str] = frozenset({"localhost"})

_PRIVATE_HOSTNAME_SUFFIXES: tuple[str, ...] = (
    ".localhost",
    ".local",
    ".lan",
    ".internal",
)

_PRIVATE_IPV4_NETWORKS: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
)

_PRIVATE_IPV6_NETWORKS: tuple[ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def is_private_url(url: str) -> bool:
    """Detect if a URL targets a private/loopback/LAN address.

    Short-circuits on literal IPs and well-known hostnames to avoid DNS latency.
    Falls back to DNS resolution for ambiguous hostnames.
    DNS failures are treated as NOT private (let the normal navigation path handle errors).

    NOTE: Does NOT use `ip.is_private` because it includes benchmark/documentation
    ranges (198.18/15, 192.0.2/24, etc.) which may appear in VPN/proxy environments
    as legitimate DNS results. Instead checks only RFC 1918 + loopback + link-local + CGNAT.
    """
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").strip().lower().rstrip(".")
        if not hostname:
            return False

        if hostname in _PRIVATE_HOSTNAME_EXACT:
            return True

        if any(hostname.endswith(s) for s in _PRIVATE_HOSTNAME_SUFFIXES):
            return True

        try:
            ip = ipaddress.ip_address(hostname)
            return _is_private_ip(ip)
        except ValueError:
            pass

        return _resolve_is_private(hostname)

    except Exception as exc:
        logger.debug("URL privacy check failed for %s: %s", url, exc)
        return False


def _is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP is RFC 1918 private / loopback / link-local / CGNAT.

    Explicitly enumerates target ranges instead of relying on `ip.is_private`
    which includes benchmark (198.18/15) and documentation (192.0.2/24) ranges
    that may appear as valid DNS results in VPN/proxy environments.
    Also handles IPv4-mapped IPv6 addresses (::ffff:x.x.x.x).
    """
    if isinstance(ip, ipaddress.IPv4Address):
        return any(ip in net for net in _PRIVATE_IPV4_NETWORKS)
    mapped = ip.ipv4_mapped
    if mapped is not None:
        return any(mapped in net for net in _PRIVATE_IPV4_NETWORKS)
    return any(ip in net for net in _PRIVATE_IPV6_NETWORKS)


def _resolve_is_private(hostname: str) -> bool:
    """DNS-resolve hostname and check if any resolved IP is private.

    Returns False on DNS failure (not private — let normal path handle the error).
    Callers should wrap in asyncio.to_thread() to avoid blocking the event loop.
    """
    try:
        addr_info = socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM, proto=socket.IPPROTO_TCP,
        )
    except (socket.gaierror, socket.timeout, OSError):
        return False

    if not addr_info:
        return False

    for _, _, _, _, sockaddr in addr_info:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _is_private_ip(ip):
            return True

    return False
