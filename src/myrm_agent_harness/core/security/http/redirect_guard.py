"""HTTP redirect sensitive header security guard and Origin validation.

[INPUT]
- urllib.parse::urlparse (POS: standard library URL parsing)
- myrm_agent_harness.core.security.audit::record_decision (POS: security audit logging)

[OUTPUT]
- Origin / extract_origin: normalize and extract (scheme, host, port) tuples
- is_same_origin: evaluate whether two URLs share the same origin
- is_sensitive_header: check if a header key is sensitive (standard or regex-matched)
- strip_sensitive_headers_on_redirect: pure-function header sanitization for redirects
- InsecureRedirectSecurityError: raised on prohibited HTTP protocol downgrades
- create_mcp_redirect_guard_event_hooks: httpx/httpx2 client event hooks for MCP transports

[POS]
Outbound HTTP security module preventing credential leakage (Bearer tokens, API keys,
Cookies, custom secrets) when HTTP redirects cross origins or downgrade to plaintext HTTP.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from myrm_agent_harness.core.security.audit import record_decision

if TYPE_CHECKING:
    import httpx
    import httpx2

logger = logging.getLogger(__name__)

__all__ = [
    "InsecureRedirectSecurityError",
    "Origin",
    "create_mcp_redirect_guard_event_hooks",
    "extract_origin",
    "is_same_origin",
    "is_sensitive_header",
    "strip_sensitive_headers_on_redirect",
]

_DEFAULT_PORTS: dict[str, int] = {
    "http": 80,
    "https": 443,
    "ws": 80,
    "wss": 443,
}

_STANDARD_SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "proxy-authorization",
        "x-csrf-token",
        "x-xsrf-token",
        "x-auth-token",
        "x-api-key",
        "apikey",
        "token",
        "secret",
    }
)

_SENSITIVE_KEY_PATTERN = re.compile(
    r"^(x[-_])?(api[-_]?key|auth[-_]?token|secret|access[-_]?token|bearer[-_]?token|private[-_]?key|session[-_]?token|client[-_]?secret)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Origin:
    """Normalized RFC 6454 Web Origin representation."""

    scheme: str
    host: str
    port: int

    @property
    def is_secure(self) -> bool:
        """Check if origin uses TLS."""
        return self.scheme.lower() in ("https", "wss")


class InsecureRedirectSecurityError(PermissionError):
    """Raised when an HTTP redirect performs an insecure protocol downgrade or prohibited transfer."""


def extract_origin(url: str) -> Origin | None:
    """Extract normalized Origin (scheme, host, port) from a URL string."""
    try:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").strip().lower()
        host = (parsed.hostname or "").strip().lower()
        if not scheme or not host:
            return None
        port = parsed.port if parsed.port is not None else _DEFAULT_PORTS.get(scheme, 80)
        return Origin(scheme=scheme, host=host, port=port)
    except Exception:
        return None


def is_same_origin(from_url: str, to_url: str) -> bool:
    """Check if two URLs share the exact same Origin (scheme, host, port)."""
    origin_a = extract_origin(from_url)
    origin_b = extract_origin(to_url)
    if origin_a is None or origin_b is None:
        return False
    return (
        origin_a.scheme == origin_b.scheme
        and origin_a.host == origin_b.host
        and origin_a.port == origin_b.port
    )


def is_sensitive_header(
    header_name: str,
    custom_sensitive_headers: frozenset[str] | None = None,
) -> bool:
    """Check whether a header name represents a sensitive credential or secret."""
    norm = header_name.strip().lower()
    if norm in _STANDARD_SENSITIVE_HEADERS:
        return True
    if custom_sensitive_headers and norm in custom_sensitive_headers:
        return True
    return bool(_SENSITIVE_KEY_PATTERN.match(norm))


def strip_sensitive_headers_on_redirect(
    from_url: str,
    to_url: str,
    headers: dict[str, str],
    *,
    custom_sensitive_headers: frozenset[str] | None = None,
    allow_insecure_downgrade: bool = False,
    tool_name: str = "http_redirect_guard",
) -> dict[str, str]:
    """Sanitize request headers when following an HTTP redirect.

    Rules:
    1. Same-Origin: keep all headers.
    2. Protocol Downgrade (HTTPS -> HTTP): raise InsecureRedirectSecurityError if
       sensitive headers are present, unless allowed, and purge all sensitive headers.
    3. Cross-Origin: purge sensitive headers (RFC standard & custom) and record an audit decision.
    """
    origin_from = extract_origin(from_url)
    origin_to = extract_origin(to_url)

    if origin_from is None or origin_to is None:
        # Cannot determine origin safety; fail-closed by stripping sensitive headers
        return {
            k: v
            for k, v in headers.items()
            if not is_sensitive_header(k, custom_sensitive_headers)
        }

    # Detect HTTPS -> HTTP downgrade
    if origin_from.is_secure and not origin_to.is_secure:
        has_sensitive = any(is_sensitive_header(k, custom_sensitive_headers) for k in headers)
        if has_sensitive:
            msg = f"Insecure protocol downgrade redirect from {from_url} to {to_url} with sensitive credentials"
            record_decision(
                tool_name=tool_name,
                decision="INSECURE_REDIRECT_BLOCKED",
                reason=msg,
            )
            if not allow_insecure_downgrade:
                raise InsecureRedirectSecurityError(msg)

    # Same origin check
    if (
        origin_from.scheme == origin_to.scheme
        and origin_from.host == origin_to.host
        and origin_from.port == origin_to.port
    ):
        return dict(headers)

    # Cross-origin: strip sensitive headers
    stripped_keys: list[str] = []
    sanitized: dict[str, str] = {}
    for k, v in headers.items():
        if is_sensitive_header(k, custom_sensitive_headers):
            stripped_keys.append(k)
        else:
            sanitized[k] = v

    if stripped_keys:
        reason = (
            f"Stripped sensitive headers {stripped_keys} across cross-origin redirect: "
            f"{origin_from.scheme}://{origin_from.host}:{origin_from.port} -> "
            f"{origin_to.scheme}://{origin_to.host}:{origin_to.port}"
        )
        logger.warning(reason)
        record_decision(
            tool_name=tool_name,
            decision="REDIRECT_HEADER_STRIPPED",
            reason=reason,
        )

    return sanitized


def create_mcp_redirect_guard_event_hooks(
    initial_url: str,
    *,
    custom_sensitive_headers: frozenset[str] | None = None,
) -> dict[str, list[object]]:
    """Build httpx / httpx2 event_hooks to safeguard follow_redirects against credential leaks."""
    initial_origin = extract_origin(initial_url)

    async def _on_request(request: httpx.Request | httpx2.Request) -> None:
        target_origin = extract_origin(str(request.url))
        if initial_origin is None or target_origin is None:
            return

        # Check if this request has migrated across origins
        if (
            initial_origin.scheme != target_origin.scheme
            or initial_origin.host != target_origin.host
            or initial_origin.port != target_origin.port
        ):
            has_sensitive = any(is_sensitive_header(k, custom_sensitive_headers) for k in request.headers)
            # Check for insecure downgrade
            if initial_origin.is_secure and not target_origin.is_secure and has_sensitive:
                msg = f"MCP Insecure protocol downgrade redirect blocked: {initial_url} -> {request.url}"
                record_decision(
                    tool_name="mcp_transport",
                    decision="INSECURE_REDIRECT_BLOCKED",
                    reason=msg,
                )
                raise InsecureRedirectSecurityError(msg)

            # Strip sensitive headers from the outgoing request
            for header_key in list(request.headers.keys()):
                if is_sensitive_header(header_key, custom_sensitive_headers):
                    del request.headers[header_key]

    return {"request": [_on_request]}
