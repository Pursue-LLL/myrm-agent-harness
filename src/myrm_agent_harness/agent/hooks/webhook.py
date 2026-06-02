"""SSRF defense-in-depth utilities for webhook hooks.

Provides URL validation, IP blacklisting, and DNS resolution guards
used by HookExecutor._run_http to prevent Server-Side Request Forgery.

[INPUT]
- (none)

[OUTPUT]
- check_ssrf: Layer 1+2: URL validation + hostname/IP blacklist.
- resolve_and_pin_dns: Layer 3: DNS resolution + IP validation + conditional DNS...

[POS]
SSRF defense-in-depth utilities for webhook hooks.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

_FORBIDDEN_HOSTS = frozenset(
    {
        "localhost",
        "host.docker.internal",
        "metadata.google.internal",
        "metadata.aws.internal",
    }
)


def _is_private_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address is private/reserved (SSRF target)."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped

    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
    )


def check_ssrf(url: str) -> str | None:
    """Layer 1+2: URL validation + hostname/IP blacklist.

    Returns error message if blocked, None if safe.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    if parsed.username or parsed.password:
        return "SSRF blocked: URL contains userinfo"

    lower_host = hostname.lower()
    if lower_host in _FORBIDDEN_HOSTS or lower_host.endswith(".localhost"):
        return f"SSRF blocked: forbidden host '{hostname}'"

    try:
        addr = ipaddress.ip_address(hostname)
        if _is_private_ip(addr):
            return f"SSRF blocked: private IP '{hostname}'"
    except ValueError:
        pass

    return None


def resolve_and_pin_dns(url: str, *, allow_private: bool = False) -> tuple[str, str]:
    """Layer 3: DNS resolution + IP validation + conditional DNS pinning.

    Resolves the hostname, validates all resolved IPs against private ranges.
    For HTTP: rewrites URL to use resolved IP (DNS pinning, prevents TOCTOU).
    For HTTPS: returns original URL (TLS certificate validation prevents rebinding).

    Returns:
        (resolved_url, original_host_header) — if HTTP pinning succeeds
        (original_url, "") — if HTTPS (no pinning needed)
        ("", "") — if DNS resolved to private IP (SSRF blocked)
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    port = parsed.port
    is_https = parsed.scheme == "https"

    try:
        ipaddress.ip_address(hostname)
        return url, ""
    except ValueError:
        pass

    try:
        results = socket.getaddrinfo(hostname, port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        logger.warning("DNS resolution failed for webhook host: %s", hostname)
        return url, ""

    if not results:
        return url, ""

    if not allow_private:
        for _family, _type, _proto, _canonname, sockaddr in results:
            ip_str = sockaddr[0]
            try:
                addr = ipaddress.ip_address(ip_str)
                if _is_private_ip(addr):
                    logger.warning("SSRF blocked: DNS for '%s' resolved to private IP %s", hostname, ip_str)
                    return "", ""
            except ValueError:
                continue

    if is_https:
        return url, ""

    resolved_ip = results[0][4][0]
    netloc = f"[{resolved_ip}]" if ":" in resolved_ip else resolved_ip
    if port:
        netloc = f"{netloc}:{port}"

    pinned_url = urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))

    return pinned_url, hostname
