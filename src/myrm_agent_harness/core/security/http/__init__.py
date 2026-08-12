"""SSRF-protected outbound HTTP helpers.

[POS]
Facade for SSRF-shielded HTTP helpers (secure_get / secure_request / target resolution).
"""
from myrm_agent_harness.core.security.http.secure_fetch import (
    DEFAULT_MAX_CONTENT_LENGTH,
    DEFAULT_MAX_REDIRECTS,
    ContentTooLargeError,
    SecureHttpTarget,
    is_ssrf_shield_enabled,
    parse_allowed_internal_hosts,
    resolve_secure_http_target,
    secure_get,
    secure_request,
)

__all__ = [
    "DEFAULT_MAX_CONTENT_LENGTH",
    "DEFAULT_MAX_REDIRECTS",
    "ContentTooLargeError",
    "SecureHttpTarget",
    "is_ssrf_shield_enabled",
    "parse_allowed_internal_hosts",
    "resolve_secure_http_target",
    "secure_get",
    "secure_request",
]
