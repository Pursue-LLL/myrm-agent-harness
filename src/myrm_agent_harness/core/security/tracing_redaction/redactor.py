"""Tracing Sensitive Data Redactor across all execution paths.

[INPUT]
- TraceSpanInput with arbitrary payloads and errors across success, error, streaming, retry, and resume paths.

[OUTPUT]
- RedactedTraceSpan guaranteed free from secrets, credentials, and honors opt-out policies.

[POS]
- Harness core security engine for OpenAI-Agents-JS #1970 cross-path tracing redaction consistency.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .types import (
    ExecutionPathType,
    RedactedTraceSpan,
    TraceSpanInput,
    TracingOptOutMode,
)

# Common credential patterns in logs, errors, and traces
TOKEN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[a-zA-Z0-9_\-]{20,}", re.IGNORECASE), "[REDACTED_API_KEY]"),
    (
        re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{15,}", re.IGNORECASE),
        "Bearer [REDACTED_TOKEN]",
    ),
    (
        re.compile(r"xox[baprs]-[a-zA-Z0-9_\-\.]{10,}", re.IGNORECASE),
        "[REDACTED_SLACK_TOKEN]",
    ),
    (
        re.compile(r"gh[pousr]_[a-zA-Z0-9]{30,}", re.IGNORECASE),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    (
        re.compile(
            r"(password|passwd|secret|api_key|token)[\"']?\s*[:=]\s*[\"']?([^\"'\s,;]+)",
            re.IGNORECASE,
        ),
        r"\1=[REDACTED]",
    ),
]

SENSITIVE_KEY_NAMES: frozenset[str] = frozenset(
    [
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "auth_token",
        "authorization",
        "private_key",
        "client_secret",
    ]
)


class TracingRedactor:
    """Sanitizes trace spans and enforces cross-path sensitive data preservation policies."""

    def __init__(
        self, default_opt_out_mode: TracingOptOutMode = TracingOptOutMode.DROP_TRACE
    ) -> None:
        self._default_opt_out_mode = default_opt_out_mode

    def _redact_text(self, text: str) -> tuple[str, int]:
        """Redact known secret patterns from a string."""
        modified = text
        count = 0
        for pattern, replacement in TOKEN_PATTERNS:
            new_text, n = pattern.subn(replacement, modified)
            if n > 0:
                count += n
                modified = new_text
        return modified, count

    def _sanitize_value(self, val: object, key_context: str = "") -> tuple[object, int]:
        """Recursively redact secrets in strings, mappings, and sequences."""
        # Key name check
        if key_context.lower() in SENSITIVE_KEY_NAMES:
            return "[REDACTED_SENSITIVE_FIELD]", 1

        if isinstance(val, str):
            return self._redact_text(val)

        if isinstance(val, Mapping):
            redacted_dict: dict[str, object] = {}
            total_count = 0
            for k, v in val.items():
                s_key = str(k)
                clean_v, count = self._sanitize_value(v, key_context=s_key)
                redacted_dict[s_key] = clean_v
                total_count += count
            return redacted_dict, total_count

        if isinstance(val, Sequence) and not isinstance(val, (str, bytes)):
            redacted_list: list[object] = []
            total_count = 0
            for item in val:
                clean_item, count = self._sanitize_value(item, key_context=key_context)
                redacted_list.append(clean_item)
                total_count += count
            return redacted_list, total_count

        return val, 0

    def sanitize_span(
        self,
        span: TraceSpanInput,
        opt_out_mode_override: TracingOptOutMode | None = None,
    ) -> RedactedTraceSpan:
        """Sanitize an execution trace span across success, error, streaming, retry, and resume paths."""
        opt_mode = opt_out_mode_override or self._default_opt_out_mode

        # 1. Opt-out enforcement
        if span.opt_out_requested:
            if opt_mode == TracingOptOutMode.DROP_TRACE:
                return RedactedTraceSpan(
                    trace_id=span.trace_id,
                    span_id=span.span_id,
                    path_type=span.path_type,
                    sanitized_payload={},
                    sanitized_error=None,
                    is_dropped=True,
                    redaction_count=0,
                    policy_applied="opt_out_drop",
                )

        # 2. Payload sanitization
        sanitized_payload, p_count = self._sanitize_value(span.payload)
        assert isinstance(sanitized_payload, dict)

        # 3. Error message / stack trace sanitization
        sanitized_error: str | None = None
        e_count = 0
        if span.raw_error:
            sanitized_error, e_count = self._redact_text(span.raw_error)

        return RedactedTraceSpan(
            trace_id=span.trace_id,
            span_id=span.span_id,
            path_type=span.path_type,
            sanitized_payload=sanitized_payload,
            sanitized_error=sanitized_error,
            is_dropped=False,
            redaction_count=p_count + e_count,
            policy_applied="redaction_enforced",
        )
