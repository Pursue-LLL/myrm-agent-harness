"""Proxy utility functions for LLM egress network isolation.

[INPUT]
- urllib.parse: URL parsing and unparsing
- httpx: Async HTTP client with proxy support

[OUTPUT]
- normalize_proxy_url(): Normalize proxy URL string (canonical scheme rewriting and whitespace stripping)
- mask_proxy_url(): Mask credentials in proxy URL for safe logging and UI
- validate_proxy_url(): Validate proxy scheme and structure
- probe_proxy_health(): Async lightweight proxy connectivity probe with TTL caching
- clear_proxy_probe_cache(): Clear the in-memory proxy probe result cache

[POS]
Network utility module for proxy URL normalization, validation, security masking,
and preflight connectivity verification.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import time
from urllib.parse import quote, urlparse, urlunparse

logger = logging.getLogger(__name__)

ALLOWED_PROXY_SCHEMES = frozenset({"http", "https", "socks5", "socks5h"})
_BLOCKED_METADATA_HOSTNAMES = frozenset({
    "instance-data",
    "metadata.google.internal",
    "metadata",
})

_CREDENTIAL_URL_PATTERN = re.compile(
    r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<user>[^:\s/@]+):(?P<pass>[^@\s]+)@"
)

_PROBE_CACHE_MAX_ENTRIES = 256
_probe_cache: dict[tuple[str, str], tuple[float, bool, str | None]] = {}


def _sanitize_proxy_error(exc_or_msg: object, proxy_url: str) -> str:
    """Sanitize error messages to prevent credential leakage in logs and UI."""
    msg = str(exc_or_msg)
    try:
        parsed = urlparse(proxy_url)
        if parsed.password:
            msg = msg.replace(f":{parsed.password}@", ":***@")
            encoded_pw = quote(parsed.password, safe="")
            if encoded_pw != parsed.password:
                msg = msg.replace(f":{encoded_pw}@", ":***@")
    except Exception:
        pass
    return _CREDENTIAL_URL_PATTERN.sub(r"\g<scheme>\g<user>:***@", msg)


def clear_proxy_probe_cache() -> None:
    """Clear the in-memory probe result cache."""
    _probe_cache.clear()


def _is_blocked_proxy_target(hostname: str) -> tuple[bool, str | None]:
    """Check if a hostname or IP address targets forbidden link-local or metadata services.

    Allows loopback (e.g. 127.0.0.1, localhost) and private LAN addresses for local developer proxies,
    while blocking cloud IMDS / link-local addresses (169.254.0.0/16, fe80::/10) and known metadata hostnames.
    """
    clean_host = hostname.strip("[]").lower()
    if clean_host in _BLOCKED_METADATA_HOSTNAMES:
        return True, f"Proxy host '{clean_host}' is blocked for security reasons (metadata service)"

    try:
        ip = ipaddress.ip_address(clean_host)
        if ip.is_link_local:
            return True, f"Proxy host '{clean_host}' is a link-local address, which is blocked"
        if ip.version == 6 and ip.ipv4_mapped and ip.ipv4_mapped.is_link_local:
            return True, f"Proxy host '{clean_host}' is an IPv4-mapped link-local address, which is blocked"
        if ip.is_unspecified:
            return True, f"Proxy host '{clean_host}' is an unspecified address, which is blocked"
    except ValueError:
        pass

    return False, None


def normalize_proxy_url(proxy_url: str | None) -> str | None:
    """Normalize proxy URL string.

    Converts common shorthand or client-exported schemes like 'socks://'
    into canonical 'socks5://', strips leading/trailing whitespace,
    and returns None for empty/non-string inputs.

    Example:
        >>> normalize_proxy_url(" socks://127.0.0.1:1080 ")
        'socks5://127.0.0.1:1080'
    """
    if not proxy_url or not isinstance(proxy_url, str):
        return None

    cleaned = proxy_url.strip()
    if not cleaned:
        return None

    if cleaned.lower().startswith("socks://"):
        return "socks5://" + cleaned[len("socks://"):]

    return cleaned


def mask_proxy_url(url: str | None) -> str | None:
    """Mask credentials in a proxy URL for safe logging and UI display.

    Supports standalone proxy URLs as well as messages containing embedded URLs.

    Example:
        >>> mask_proxy_url("http://admin:secret123@proxy.corp.internal:8080")
        'http://admin:***@proxy.corp.internal:8080'
    """
    if not url or not isinstance(url, str):
        return url

    cleaned = url.strip()
    if not cleaned:
        return cleaned

    # 1. Clean standalone URL (without whitespace)
    if not any(c in cleaned for c in (" ", "\n", "\t", "\r")):
        try:
            parsed = urlparse(cleaned)
            if parsed.scheme and (parsed.hostname or parsed.netloc):
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

    # 2. Freeform text / embedded URLs fallback
    return _CREDENTIAL_URL_PATTERN.sub(r"\g<scheme>\g<user>:***@", cleaned)


def validate_proxy_url(url: str | None) -> tuple[bool, str | None]:
    """Validate proxy URL scheme and basic structure.

    Returns:
        (is_valid, error_reason)
    """
    if not url or not isinstance(url, str):
        return False, "Proxy URL cannot be empty"

    normalized = normalize_proxy_url(url)
    if not normalized:
        return False, "Proxy URL cannot be empty"

    try:
        parsed = urlparse(normalized)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ALLOWED_PROXY_SCHEMES:
            return False, f"Unsupported proxy scheme '{scheme}'. Supported: {', '.join(sorted(ALLOWED_PROXY_SCHEMES))}"

        if not parsed.hostname:
            return False, "Proxy URL is missing hostname"

        is_blocked, block_err = _is_blocked_proxy_target(parsed.hostname)
        if is_blocked:
            return False, block_err

        return True, None
    except Exception as exc:
        return False, f"Invalid proxy URL: {exc}"


async def probe_proxy_health(
    proxy_url: str,
    target_url: str = "https://1.1.1.1",
    timeout_s: float = 3.0,
    cache_ttl_s: float = 60.0,
) -> tuple[bool, str | None]:
    """Perform a lightweight connectivity probe through the specified proxy.

    Args:
        proxy_url: Outbound proxy URL (HTTP/HTTPS/SOCKS5)
        target_url: Target URL for probe request (default Cloudflare DNS probe)
        timeout_s: Request timeout in seconds
        cache_ttl_s: Duration in seconds to cache probe results (<= 0 disables caching)

    Returns:
        (is_success, error_message)
    """
    normalized_proxy = normalize_proxy_url(proxy_url)
    if not normalized_proxy:
        return False, "Proxy URL cannot be empty"

    if cache_ttl_s > 0:
        cache_key = (normalized_proxy, target_url)
        cached_entry = _probe_cache.get(cache_key)
        if cached_entry is not None:
            cached_at, cached_ok, cached_err = cached_entry
            if time.monotonic() - cached_at < cache_ttl_s:
                return cached_ok, cached_err

    is_valid, err = validate_proxy_url(normalized_proxy)
    if not is_valid:
        return False, err

    try:
        parsed_target = urlparse(target_url)
        target_scheme = (parsed_target.scheme or "").lower()
        if target_scheme not in ("http", "https"):
            return False, f"Unsupported probe target scheme '{target_scheme}'"
        if not parsed_target.hostname:
            return False, "Probe target URL is missing hostname"
        target_blocked, target_reason = _is_blocked_proxy_target(parsed_target.hostname)
        if target_blocked:
            return False, f"Probe target URL blocked: {target_reason}"
    except Exception as exc:
        return False, f"Invalid probe target URL: {exc}"

    import httpx

    masked = mask_proxy_url(normalized_proxy)
    outcome: tuple[bool, str | None]
    try:
        async with httpx.AsyncClient(
            proxy=normalized_proxy,
            timeout=timeout_s,
            verify=True,
        ) as client:
            resp = await client.head(target_url)
            status = resp.status_code
            if 200 <= status < 400:
                outcome = (True, None)
            elif status == 407:
                outcome = (False, "Proxy authentication required (HTTP 407)")
            elif status in (403, 429):
                outcome = (False, f"Target probe blocked or rate limited (HTTP {status})")
            elif 400 <= status < 500:
                # Upstream target responded (e.g. 401/404/405), confirming proxy tunnel and TLS succeeded
                outcome = (True, None)
            elif status >= 500:
                outcome = (False, f"Proxy or upstream server error (HTTP {status})")
            else:
                outcome = (False, f"Proxy probe received unexpected HTTP {status}")
    except httpx.ProxyError as exc:
        sanitized_msg = _sanitize_proxy_error(exc, normalized_proxy)
        logger.warning("Proxy connection error for %s: %s", masked, sanitized_msg)
        outcome = (False, f"Proxy connection failed: {sanitized_msg}")
    except httpx.ConnectTimeout:
        logger.warning("Proxy connection timed out for %s", masked)
        outcome = (False, "Proxy connection timed out")
    except Exception as exc:
        sanitized_msg = _sanitize_proxy_error(exc, normalized_proxy)
        logger.warning("Proxy probe failed for %s: %s", masked, sanitized_msg)
        outcome = (False, f"Proxy probe failed: {sanitized_msg}")

    if cache_ttl_s > 0:
        now = time.monotonic()
        if len(_probe_cache) >= _PROBE_CACHE_MAX_ENTRIES:
            expired_keys = [k for k, v in _probe_cache.items() if now - v[0] >= cache_ttl_s]
            for k in expired_keys:
                _probe_cache.pop(k, None)
            if len(_probe_cache) >= _PROBE_CACHE_MAX_ENTRIES:
                _probe_cache.pop(next(iter(_probe_cache)), None)
        _probe_cache[cache_key] = (now, outcome[0], outcome[1])

    return outcome
