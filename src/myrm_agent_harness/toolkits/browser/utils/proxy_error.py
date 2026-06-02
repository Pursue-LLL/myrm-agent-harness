"""Utilities for detecting proxy and network errors."""

import re
from typing import Any

# Common proxy and network error patterns
PROXY_ERROR_PATTERNS = [
    r"net::err_proxy",
    r"net::err_tunnel_connection_failed",
    r"net::err_empty_response",
    r"net::err_connection_reset",
    r"net::err_connection_closed",
    r"net::err_connection_refused",
    r"net::err_name_not_resolved",
    r"net::err_timed_out",
    r"net::err_network_changed",
    r"proxy authentication required",
    r"proxy connection failed",
    r"target closed",
    r"browser has been closed",
    r"page closed",
    r"context closed",
]

# Compiled regex for faster matching
_PROXY_ERROR_REGEX = re.compile("|".join(PROXY_ERROR_PATTERNS), re.IGNORECASE)

def is_proxy_error(error: Exception | str | Any) -> bool:
    """Detect if an exception or error message is related to proxy/network failure.

    Args:
        error: The exception or error string to check.

    Returns:
        True if the error is likely a proxy or network error, False otherwise.
    """
    error_msg = str(error).lower()
    return bool(_PROXY_ERROR_REGEX.search(error_msg))

def is_blocked_response(status_code: int, body_text: str = "") -> bool:
    """Detect if a response indicates the IP is blocked (e.g., 403, CAPTCHA).

    Args:
        status_code: The HTTP status code.
        body_text: Optional response body text to check for CAPTCHA signatures.

    Returns:
        True if the response indicates a block, False otherwise.
    """
    if status_code in (403, 429):
        return True

    # Check for common CAPTCHA/Challenge signatures in body
    if body_text:
        body_lower = body_text.lower()
        if "cloudflare" in body_lower and "challenge" in body_lower:
            return True
        if "datadome" in body_lower:
            return True
        if "captcha" in body_lower and "verify" in body_lower:
            return True

    return False
