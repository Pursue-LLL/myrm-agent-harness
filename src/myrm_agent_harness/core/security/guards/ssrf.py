"""Unified outbound URL SSRF protection for all Agent HTTP paths.

[INPUT]
- myrm_agent_harness.utils.url_utils::is_blocked_ip (POS: shared IP blocklist)
- myrm_agent_harness.utils.url_utils::validate_scheme_and_hostname (POS: scheme/hostname validation)
- myrm_agent_harness.core.security.guards.url_allowlist::URLAllowlistGuard (POS: skill DLP domain allowlist)

[OUTPUT]
- SSRFResult / SSRFVerdict: validation outcomes
- SSRFSecurityError: raised on blocked URLs (re-exported from url_allowlist)
- check_url / resolve_and_check: sync validation
- validate_url_for_ssrf / async_validate_url_for_ssrf: full validation with DNS
- async_pin_url / validate_and_resolve_url: DNS-pinned URL for HTTP clients

[POS]
Single orchestration layer for outbound URL SSRF checks across toolkits and agent meta-tools.
For HTTP fetch with redirect handling, consumers should use `core.security.http.secure_fetch`.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

from myrm_agent_harness.core.security.guards.url_allowlist import SSRFSecurityError, URLAllowlistGuard
from myrm_agent_harness.utils.url_utils import is_blocked_ip, validate_scheme_and_hostname

logger = logging.getLogger(__name__)

__all__ = [
    "SSRFResult",
    "SSRFVerdict",
    "SSRFSecurityError",
    "URLAllowlistGuard",
    "async_pin_url",
    "async_validate_url_for_ssrf",
    "check_url",
    "is_internal_ip",
    "resolve_and_check",
    "validate_and_resolve_url",
    "validate_url_for_ssrf",
]


@dataclass(frozen=True, slots=True)
class SSRFResult:
    """SSRF validation outcome with resolved IPs for DNS pinning."""

    safe: bool
    error: str = ""
    hostname: str = ""
    resolved_ips: tuple[str, ...] = ()

    def __iter__(self):
        yield self.safe
        yield self.error


@dataclass(frozen=True, slots=True)
class SSRFVerdict:
    """Sync fast-check result without resolved IPs."""

    allowed: bool
    reason: str


_VERDICT_OK = SSRFVerdict(allowed=True, reason="")


def is_internal_ip(ip_str: str) -> bool:
    """Check if an IP belongs to a blocked private/internal range."""
    return is_blocked_ip(ip_str)


def check_url(url: str, *, allowed_internal_hosts: frozenset[str] = frozenset()) -> SSRFVerdict:
    """Validate a URL for SSRF safety without DNS resolution."""
    hostname, error = validate_scheme_and_hostname(url)
    if hostname is None:
        return SSRFVerdict(allowed=False, reason=error)

    try:
        URLAllowlistGuard.check(hostname)
    except SSRFSecurityError as exc:
        return SSRFVerdict(allowed=False, reason=str(exc))

    if hostname in allowed_internal_hosts:
        return _VERDICT_OK

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return _VERDICT_OK

    if is_blocked_ip(hostname):
        return SSRFVerdict(allowed=False, reason=f"Blocked private/internal IP address: {hostname}")
    return _VERDICT_OK


def resolve_and_check(hostname: str, *, allowed_internal_hosts: frozenset[str] = frozenset()) -> SSRFVerdict:
    """DNS-resolve a hostname synchronously and validate all resolved IPs."""
    if hostname in allowed_internal_hosts:
        return _VERDICT_OK

    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return SSRFVerdict(allowed=False, reason=f"DNS resolution failed for: {hostname}")

    for _family, _type, _proto, _canonname, sockaddr in results:
        addr = sockaddr[0]
        if is_blocked_ip(addr):
            return SSRFVerdict(
                allowed=False,
                reason=f"Hostname '{hostname}' resolves to private/internal IP: {addr}",
            )
    return _VERDICT_OK


def _resolve_and_check_sync(hostname: str) -> SSRFResult:
    try:
        addr = ipaddress.ip_address(hostname)
        if is_blocked_ip(addr):
            return SSRFResult(safe=False, error=f"Blocked IP: {addr} is a non-public IP address", hostname=hostname)
        return SSRFResult(safe=True, hostname=hostname, resolved_ips=(hostname,))
    except ValueError:
        pass

    try:
        resolved = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return SSRFResult(safe=False, error=f"DNS resolution failed: {hostname}", hostname=hostname)

    ips: list[str] = []
    for _, _, _, _, sockaddr in resolved:
        ip_str = sockaddr[0]
        if is_blocked_ip(ip_str):
            return SSRFResult(
                safe=False,
                error=f"Blocked resolved IP: {ip_str} is a non-public IP address (from {hostname})",
                hostname=hostname,
            )
        if ip_str not in ips:
            ips.append(ip_str)

    return SSRFResult(safe=True, hostname=hostname, resolved_ips=tuple(ips))


async def _resolve_and_check_async(hostname: str) -> SSRFResult:
    try:
        addr = ipaddress.ip_address(hostname)
        if is_blocked_ip(addr):
            return SSRFResult(safe=False, error=f"Blocked IP: {addr} is a non-public IP address", hostname=hostname)
        return SSRFResult(safe=True, hostname=hostname, resolved_ips=(hostname,))
    except ValueError:
        pass

    loop = asyncio.get_running_loop()
    try:
        resolved = await loop.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return SSRFResult(safe=False, error=f"DNS resolution failed: {hostname}", hostname=hostname)

    ips: list[str] = []
    for _, _, _, _, sockaddr in resolved:
        ip_str = sockaddr[0]
        if is_blocked_ip(ip_str):
            return SSRFResult(
                safe=False,
                error=f"Blocked resolved IP: {ip_str} is a non-public IP address (from {hostname})",
                hostname=hostname,
            )
        if ip_str not in ips:
            ips.append(ip_str)

    return SSRFResult(safe=True, hostname=hostname, resolved_ips=tuple(ips))


def _guard_hostname_or_error(hostname: str) -> SSRFResult | None:
    try:
        URLAllowlistGuard.check(hostname)
    except SSRFSecurityError as exc:
        return SSRFResult(safe=False, error=str(exc), hostname=hostname)
    return None


def validate_url_for_ssrf(url: str) -> SSRFResult:
    """Validate URL against SSRF attacks (synchronous, with DNS resolution)."""
    hostname, error = validate_scheme_and_hostname(url)
    if hostname is None:
        return SSRFResult(safe=False, error=error)

    guard_result = _guard_hostname_or_error(hostname)
    if guard_result is not None:
        return guard_result

    return _resolve_and_check_sync(hostname)


async def async_validate_url_for_ssrf(url: str) -> SSRFResult:
    """Validate URL against SSRF attacks (async, non-blocking DNS)."""
    hostname, error = validate_scheme_and_hostname(url)
    if hostname is None:
        return SSRFResult(safe=False, error=error)

    guard_result = _guard_hostname_or_error(hostname)
    if guard_result is not None:
        return guard_result

    return await _resolve_and_check_async(hostname)


async def async_pin_url(
    url: str,
    allowed_internal_hosts: list[str] | None = None,
) -> tuple[str, dict[str, str]]:
    """Validate URL and return a DNS-pinned safe URL plus Host header for HTTP clients."""
    hostname, error = validate_scheme_and_hostname(url)
    if hostname is None:
        raise SSRFSecurityError(error)

    URLAllowlistGuard.check(hostname)

    allowed_hosts = allowed_internal_hosts or []
    parsed = urlparse(url)
    if hostname in allowed_hosts:
        return url, {}

    result = await _resolve_and_check_async(hostname)
    if not result.safe:
        logger.warning("SSRF blocked request: %s — %s", url, result.error)
        raise SSRFSecurityError(
            "Access to internal network is blocked for security reasons. "
            f"{result.error}"
        )

    if not result.resolved_ips:
        raise SSRFSecurityError(f"DNS resolution failed for {hostname}")

    ip_address = result.resolved_ips[0]
    netloc = f"{ip_address}:{parsed.port}" if parsed.port else ip_address
    safe_url = urlunparse(parsed._replace(netloc=netloc))
    return safe_url, {"Host": hostname}


validate_and_resolve_url = async_pin_url
