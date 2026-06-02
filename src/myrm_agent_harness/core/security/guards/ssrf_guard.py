"""SSRF Guard — Server-Side Request Forgery protection.

Validates URLs before network requests to prevent Agent tools from
accessing internal/private network services. Pure functions, no state.

Called by network-capable toolkits (browser, shell) before issuing
HTTP requests — NOT integrated into the global middleware since most
tools don't make network requests.

[INPUT]
- myrm_agent_harness.utils.url_utils::is_blocked_ip (POS: shared IP check)

[OUTPUT]
- SSRFVerdict: allowed / blocked (with reason)
- check_url(): validate a URL against SSRF rules
- resolve_and_check(): DNS-resolve a hostname and validate the IP

[POS]
Standalone guard module. Called by browser toolkit (navigation) and
shell toolkit (when curl/wget/fetch detected) before network access.
IP blocking logic delegates to url_utils.is_blocked_ip (single source of truth).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from myrm_agent_harness.utils.url_utils import is_blocked_ip

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})


@dataclass(frozen=True, slots=True)
class SSRFVerdict:
    """Result of SSRF validation."""

    allowed: bool
    reason: str


_VERDICT_OK = SSRFVerdict(allowed=True, reason="")


def check_url(url: str, *, allowed_internal_hosts: frozenset[str] = frozenset()) -> SSRFVerdict:
    """Validate a URL for SSRF safety.

    Checks scheme whitelist and hostname against private networks.
    Does NOT perform DNS resolution (use resolve_and_check for that).

    Args:
        url: the URL to validate
        allowed_internal_hosts: hostnames explicitly allowed (bypass private IP check)
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return SSRFVerdict(allowed=False, reason=f"Malformed URL: {url[:200]}")

    if parsed.scheme not in _ALLOWED_SCHEMES:
        return SSRFVerdict(
            allowed=False,
            reason=f"Blocked URL scheme '{parsed.scheme}' (allowed: {', '.join(sorted(_ALLOWED_SCHEMES))})",
        )

    hostname = parsed.hostname
    if not hostname:
        return SSRFVerdict(allowed=False, reason="URL has no hostname")

    if hostname in allowed_internal_hosts:
        return _VERDICT_OK

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass  # hostname is a domain name, not an IP — will be checked at DNS resolution
    else:
        if is_blocked_ip(hostname):
            return SSRFVerdict(allowed=False, reason=f"Blocked private/internal IP address: {hostname}")

    return _VERDICT_OK


def resolve_and_check(hostname: str, *, allowed_internal_hosts: frozenset[str] = frozenset()) -> SSRFVerdict:
    """DNS-resolve a hostname and validate the resolved IP addresses.

    This provides deeper protection than check_url alone, catching
    cases where a public domain resolves to a private IP.

    Args:
        hostname: the hostname to resolve
        allowed_internal_hosts: hostnames explicitly allowed
    """
    if hostname in allowed_internal_hosts:
        return _VERDICT_OK

    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return SSRFVerdict(allowed=False, reason=f"DNS resolution failed for: {hostname}")

    for _family, _type, _proto, _canonname, sockaddr in results:
        addr = sockaddr[0]
        if is_blocked_ip(addr):
            return SSRFVerdict(allowed=False, reason=f"Hostname '{hostname}' resolves to private/internal IP: {addr}")

    return _VERDICT_OK
