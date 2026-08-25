"""Structured connector health degradation and failure classification for cron automations.

Pure deterministic functions and data models — no I/O, safe to import anywhere in harness and server.
Used to classify outbound delivery and connector failures, redact credentials in target endpoints,
and construct structured alert payloads for human and machine consumption.

[INPUT]
- Exception or error message text
- HTTP status codes, latency, and target URLs

[OUTPUT]
- ConnectorErrorCategory: 6-tier canonical failure taxonomy
- ConnectorHealthStatus: HEALTHY / DEGRADED / DOWN state machine
- classify_connector_error: Classifies raw exceptions or error strings into categories
- redact_connector_url: Strips passwords, auth tokens, and sensitive query params from target URLs
- ConnectorFailureDetail: Structured error metadata
- StructuredAlertPayload: Standard alert contract for notification channels and webhooks

[POS]
Harness-level domain models and taxonomy for automation connector health diagnostics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from myrm_agent_harness.core.security.redact import redact_sensitive_text


class ConnectorErrorCategory(StrEnum):
    """Canonical classification for connector and delivery failures."""

    HTTP_CLIENT_ERROR = "http_client_error"      # 4xx errors (excluding 401/403 auth)
    HTTP_SERVER_ERROR = "http_server_error"      # 500, 502, 503, 504 gateway/upstream failures
    NETWORK_UNREACHABLE = "network_unreachable"  # DNS resolution failed, Connection Refused
    TIMEOUT = "timeout"                          # Connect, read, or socket timeout
    AUTH_FAILURE = "auth_failure"                # 401 Unauthorized, 403 Forbidden, invalid key
    PAYLOAD_CONTRACT = "payload_contract"        # Invalid JSON-like response, response too large
    PROCESS_ERROR = "process_error"              # Stdio broken pipe, child process exit
    UNKNOWN = "unknown"


class ConnectorHealthStatus(StrEnum):
    """Health state of a specific connector destination."""

    HEALTHY = "healthy"      # 0 consecutive failures (or recovered)
    DEGRADED = "degraded"    # 1-2 consecutive failures, transient degradation
    DOWN = "down"            # >= 3 consecutive failures or permanent auth/client rejection


_SENSITIVE_PARAM_NAMES = frozenset({
    "access_token",
    "token",
    "secret",
    "key",
    "apikey",
    "api_key",
    "auth",
    "authorization",
    "password",
    "sig",
    "signature",
    "sign",
})


def redact_connector_url(url: str | None) -> str:
    """Safely redact credentials and tokens from a connector target URL.

    - Masks basic auth password: https://user:***@host:port/path
    - Masks known sensitive query params: ?access_token=***&key=***
    - Preserves hostname, port, and safe query parameters for diagnostics.
    """
    if not url:
        return ""

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return redact_sensitive_text(url)

    netloc = parsed.netloc
    if "@" in netloc:
        userinfo, hostport = netloc.split("@", 1)
        if ":" in userinfo:
            username = userinfo.split(":", 1)[0]
            netloc = f"{username}:***@{hostport}"
        else:
            netloc = f"***@{hostport}"

    query_parts: list[tuple[str, str]] = []
    if parsed.query:
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            if k.lower() in _SENSITIVE_PARAM_NAMES:
                query_parts.append((k, "***"))
            else:
                query_parts.append((k, v))
        new_query = urlencode(query_parts)
    else:
        new_query = ""

    redacted = urlunparse((
        parsed.scheme,
        netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment,
    ))
    return redacted


def classify_connector_error(
    error: Exception | str,
    *,
    status_code: int | None = None,
) -> tuple[ConnectorErrorCategory, str]:
    """Classify an exception or error string into a structured category and clean message.

    Returns:
        (category, human_readable_summary)
    """
    error_text = str(error).strip() if error else "Unknown error"

    # 1. Explicit status code check
    if status_code is not None:
        if status_code in (401, 403):
            return ConnectorErrorCategory.AUTH_FAILURE, f"Authentication failed (HTTP {status_code})"
        if 400 <= status_code < 500:
            return ConnectorErrorCategory.HTTP_CLIENT_ERROR, f"Client error (HTTP {status_code})"
        if 500 <= status_code < 600:
            return ConnectorErrorCategory.HTTP_SERVER_ERROR, f"Server error (HTTP {status_code})"

    lower = error_text.lower()

    # 2. Pattern matching for HTTP status inside error text
    if "webhook returned 401" in lower or "webhook returned 403" in lower or "unauthorized" in lower or "forbidden" in lower:
        return ConnectorErrorCategory.AUTH_FAILURE, "Destination rejected credentials (401/403)"
    if "webhook returned 4" in lower:
        return ConnectorErrorCategory.HTTP_CLIENT_ERROR, "Destination rejected request (4xx)"
    if "webhook returned 502" in lower or "502 bad gateway" in lower:
        return ConnectorErrorCategory.HTTP_SERVER_ERROR, "Destination gateway down (502 Bad Gateway)"
    if "webhook returned 503" in lower or "503 service unavailable" in lower:
        return ConnectorErrorCategory.HTTP_SERVER_ERROR, "Destination service unavailable (503)"
    if "webhook returned 504" in lower or "504 gateway timeout" in lower:
        return ConnectorErrorCategory.TIMEOUT, "Destination gateway timed out (504)"
    if "webhook returned 5" in lower or "internal server error" in lower:
        return ConnectorErrorCategory.HTTP_SERVER_ERROR, "Destination internal server error (5xx)"

    # 3. Timeout patterns
    if any(k in lower for k in ("timed out", "timeout", "deadline", "readtimeout", "connecttimeout")):
        return ConnectorErrorCategory.TIMEOUT, "Connection or read timed out"

    # 4. Network and DNS resolution patterns
    if any(k in lower for k in (
        "connection refused", "econnrefused", "name or service not known",
        "nodename nor servname", "dns", "unreachable", "network is unreachable",
        "ssl", "certificate", "tlsv1", "handshake failure"
    )):
        return ConnectorErrorCategory.NETWORK_UNREACHABLE, "Destination network or DNS unreachable"

    # 5. Payload / contract patterns
    if any(k in lower for k in ("content toolarge", "invalid json", "contract error", "payload too large")):
        return ConnectorErrorCategory.PAYLOAD_CONTRACT, "Response payload or contract invalid"

    # 6. Process / stdio errors
    if any(k in lower for k in ("broken pipe", "process exited", "subprocess terminated")):
        return ConnectorErrorCategory.PROCESS_ERROR, "Connector child process exited unexpectedly"

    return ConnectorErrorCategory.UNKNOWN, error_text[:120]


@dataclass(frozen=True, slots=True)
class ConnectorFailureDetail:
    """Structured failure diagnostic metadata attached to CronRunRecord."""

    category: ConnectorErrorCategory
    target: str
    status_code: int | None = None
    message: str = ""
    duration_ms: int | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category.value,
            "target": self.target,
            "status_code": self.status_code,
            "message": self.message,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True, slots=True)
class StructuredAlertPayload:
    """Standardized machine-readable alert payload for automation notifications."""

    job_id: str
    job_name: str
    consecutive_failures: int
    status: ConnectorHealthStatus
    category: ConnectorErrorCategory
    target: str
    error_summary: str
    fix_suggestion: str
    last_status_code: int | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, object]:
        return {
            "event": "cron.connector.degraded",
            "job_id": self.job_id,
            "job_name": self.job_name,
            "consecutive_failures": self.consecutive_failures,
            "status": self.status.value,
            "category": self.category.value,
            "target": self.target,
            "error_summary": self.error_summary,
            "fix_suggestion": self.fix_suggestion,
            "last_status_code": self.last_status_code,
            "timestamp": self.timestamp,
        }


def generate_fix_suggestion(category: ConnectorErrorCategory, status_code: int | None = None) -> str:
    """Generate an actionable, language-neutral fix suggestion for a connector error."""
    if category == ConnectorErrorCategory.AUTH_FAILURE:
        return "Verify target webhook secret, authorization token, or IP whitelist settings."
    if category == ConnectorErrorCategory.HTTP_SERVER_ERROR:
        if status_code == 502:
            return "Target server reverse proxy or upstream backend is down. Check destination server logs."
        if status_code == 503:
            return "Target server is overloaded or undergoing maintenance. Retry with exponential backoff."
        return "Target server encountered an internal error (5xx). Check destination server health."
    if category == ConnectorErrorCategory.NETWORK_UNREACHABLE:
        return "Check destination host DNS resolution, firewall rules, and SSL certificate validity."
    if category == ConnectorErrorCategory.TIMEOUT:
        return "Target server took too long to respond. Check network latency or increase timeout."
    if category == ConnectorErrorCategory.PAYLOAD_CONTRACT:
        return "Target returned an unexpected response format. Ensure response is valid JSON and within size limit."
    if category == ConnectorErrorCategory.PROCESS_ERROR:
        return "Local connector process terminated. Verify MCP server or runtime environment."
    return "Check destination connection settings in Settings → Cron."


__all__ = [
    "ConnectorErrorCategory",
    "ConnectorFailureDetail",
    "ConnectorHealthStatus",
    "StructuredAlertPayload",
    "classify_connector_error",
    "generate_fix_suggestion",
    "redact_connector_url",
]
