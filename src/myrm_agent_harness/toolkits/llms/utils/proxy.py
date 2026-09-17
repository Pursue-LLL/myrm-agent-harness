"""Proxy utility functions for LLM egress network isolation.

[INPUT]
- urllib.parse: URL parsing and unparsing
- httpx: Async HTTP client with proxy support

[OUTPUT]
- mask_proxy_url(): Mask credentials in proxy URL for safe logging and UI
- validate_proxy_url(): Validate proxy scheme and structure
- probe_proxy_health(): Async lightweight proxy connectivity probe

[POS]
Network utility module for proxy URL validation, security masking,
and preflight connectivity verification.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

ALLOWED_PROXY_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})


def mask_proxy_url(url: str | None) -> str | None:
    """Mask credentials in a proxy URL for safe logging and UI display.

    Example:
        >>> mask_proxy_url("http://admin:secret123@proxy.corp.internal:8080")
        'http://admin:***@proxy.corp.internal:8080'
    """
    if not url or not isinstance(url, str):
        return url

    cleaned = url.strip()
    if not cleaned:
        return cleaned

    try:
        parsed = urlparse(cleaned)
        if not parsed.password:
            return cleaned

        username = parsed.username or ""
        port_part = f":{parsed.port}" if parsed.port is not None else ""
        masked_netloc = f"{username}:***@{parsed.hostname}{port_part}"

        return urlunparse((
            parsed.scheme,
            masked_netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        ))
    except Exception:
        return "<invalid-proxy-url>"


def validate_proxy_url(url: str | None) -> tuple[bool, str | None]:
    """Validate proxy URL scheme and basic structure.

    Returns:
        (is_valid, error_reason)
    """
    if not url or not isinstance(url, str):
        return False, "Proxy URL cannot be empty"

    cleaned = url.strip()
    if not cleaned:
        return False, "Proxy URL cannot be empty"
    try:
        parsed = urlparse(cleaned)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ALLOWED_PROXY_SCHEMES:
            return False, f"Unsupported proxy scheme '{scheme}'. Supported: {', '.join(sorted(ALLOWED_PROXY_SCHEMES))}"

        if not parsed.hostname:
            return False, "Proxy URL is missing hostname"

        return True, None
    except Exception as exc:
        return False, f"Invalid proxy URL: {exc}"


async def probe_proxy_health(
    proxy_url: str,
    target_url: str = "https://1.1.1.1",
    timeout_s: float = 3.0,
) -> tuple[bool, str | None]:
    """Perform a lightweight connectivity probe through the specified proxy.

    Args:
        proxy_url: Outbound proxy URL (HTTP/HTTPS/SOCKS5)
        target_url: Target URL for probe request (default Cloudflare DNS probe)
        timeout_s: Request timeout in seconds

    Returns:
        (is_success, error_message)
    """
    is_valid, err = validate_proxy_url(proxy_url)
    if not is_valid:
        return False, err

    import httpx

    masked = mask_proxy_url(proxy_url)
    try:
        async with httpx.AsyncClient(
            proxy=proxy_url,
            timeout=timeout_s,
            verify=True,
        ) as client:
            resp = await client.head(target_url)
            # Any HTTP response indicates successful proxy transmission
            if resp.status_code < 500:
                return True, None
            return True, None
    except httpx.ProxyError as exc:
        logger.warning("Proxy connection error for %s: %s", masked, exc)
        return False, f"Proxy connection failed: {exc}"
    except httpx.ConnectTimeout:
        logger.warning("Proxy connection timed out for %s", masked)
        return False, "Proxy connection timed out"
    except Exception as exc:
        logger.warning("Proxy probe failed for %s: %s", masked, exc)
        return False, f"Proxy probe failed: {exc}"
