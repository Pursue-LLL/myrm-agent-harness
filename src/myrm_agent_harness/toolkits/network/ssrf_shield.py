"""SSRF (Server-Side Request Forgery) Shield

Provides framework-level protection against SSRF attacks, including DNS Rebinding.
This module must be used by all tools that make outbound HTTP requests on behalf of the Agent.

[INPUT]
- myrm_agent_harness.utils.url_utils::is_blocked_ip (POS: shared IP check, single source of truth)

[OUTPUT]
- SSRFSecurityError: exception for SSRF violations
- URLAllowlistGuard: context-based URL allowlist (DLP protection)
- is_internal_ip(): check if IP is internal (delegates to url_utils.is_blocked_ip)
- validate_and_resolve_url(): full SSRF check + DNS Rebinding prevention

[INPUT]
- (none)

[OUTPUT]
- SSRFSecurityError: Raised when an SSRF attempt is detected.
- URLAllowlistGuard: Context-based URL allowlist for DLP protection.
- is_internal_ip: Check if an IP address is internal/private.
- validate_and_resolve_url: Validate URL against SSRF and resolve DNS to prevent DNS ...

[POS]
SSRF (Server-Side Request Forgery) Shield
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import socket
from contextlib import contextmanager
from urllib.parse import urlparse, urlunparse

from myrm_agent_harness.utils.url_utils import is_blocked_ip

logger = logging.getLogger(__name__)


class SSRFSecurityError(ValueError):
    """Raised when an SSRF attempt is detected."""

    pass


_allowed_domains_var: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("allowed_domains", default=None)


class URLAllowlistGuard:
    """Context-based URL allowlist for DLP protection."""

    @staticmethod
    @contextmanager
    def apply(allowed_domains: list[str] | None):
        """Apply allowlist to current context."""
        token = _allowed_domains_var.set(allowed_domains)
        try:
            yield
        finally:
            _allowed_domains_var.reset(token)

    @staticmethod
    def check(hostname: str) -> None:
        """Check if hostname is in the current context's allowlist."""
        allowed_domains = _allowed_domains_var.get()
        if allowed_domains is None:
            return

        for domain in allowed_domains:
            if domain == "*":
                return
            if hostname == domain or hostname.endswith(f".{domain}"):
                return

        logger.warning(f"DLP Shield blocked request to unauthorized domain: {hostname}")
        raise SSRFSecurityError(
            f"Access to {hostname} is blocked. "
            f"The current skill is only allowed to access: {', '.join(allowed_domains)}"
        )


def is_internal_ip(ip_str: str) -> bool:
    """Check if an IP address is internal/private.

    Delegates to url_utils.is_blocked_ip (single source of truth).
    """
    return is_blocked_ip(ip_str)


async def validate_and_resolve_url(
    url: str, allowed_internal_hosts: list[str] | None = None
) -> tuple[str, dict[str, str]]:
    """Validate URL against SSRF and resolve DNS to prevent DNS Rebinding.

    This function performs the following steps:
    1. Parses the URL to extract the hostname.
    2. Resolves the hostname to an IP address.
    3. Checks if the IP address is internal/private.
    4. If internal and not in allowed_internal_hosts, raises SSRFSecurityError.
    5. Replaces the hostname in the URL with the resolved IP address.
    6. Returns the new URL and a dictionary containing the original Host header.

    By connecting directly to the resolved IP and passing the original Host header,
    we ensure that the underlying HTTP client does not perform a second DNS resolution,
    which completely neutralizes DNS Rebinding attacks.

    Args:
        url: The target URL.
        allowed_internal_hosts: Optional list of allowed internal IPs or hostnames.

    Returns:
        A tuple of (safe_url_with_ip, headers_with_host).

    Raises:
        SSRFSecurityError: If the URL resolves to a blocked internal IP.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname

    if not hostname:
        raise SSRFSecurityError(f"Invalid URL (no hostname): {url}")

    URLAllowlistGuard.check(hostname)

    allowed_hosts = allowed_internal_hosts or []
    if hostname in allowed_hosts:
        return url, {}

    try:
        loop = asyncio.get_running_loop()
        addr_info = await loop.getaddrinfo(hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
        ip_address = addr_info[0][4][0]
    except socket.gaierror as e:
        raise SSRFSecurityError(f"DNS resolution failed for {hostname}: {e}") from e

    if is_internal_ip(ip_address) and ip_address not in allowed_hosts:
        logger.warning(f"SSRF Shield blocked request to internal IP: {hostname} -> {ip_address}")
        raise SSRFSecurityError(
            f"Access to internal network is blocked for security reasons. "
            f"Resolved {hostname} to internal IP {ip_address}."
        )

    netloc = ip_address
    if parsed.port:
        netloc = f"{ip_address}:{parsed.port}"

    safe_parsed = parsed._replace(netloc=netloc)
    safe_url = urlunparse(safe_parsed)

    return safe_url, {"Host": hostname}
