"""Sanitizer implementation for telemetry spans under sensitive-data policies.

[INPUT]
- Raw telemetry span data and sensitive data policy configuration.

[OUTPUT]
- Cleaned dictionary payloads with sensitive fields omitted or masked.

[POS]
- Core sanitization engine ensuring privacy policy consistency across
  success, error, streaming, retry, and resume spans.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from myrm_agent_harness.core.security.tracing_redaction.types import (
    RawSpanPayload,
    RedactedSpanPayload,
    SensitiveDataPolicy,
    SpanCategory,
    TracingRedactionConfig,
)


class TracingSpanSanitizer:
    """Sanitizes trace spans according to configured SensitiveDataPolicy."""

    def __init__(
        self,
        config: TracingRedactionConfig | None = None,
    ) -> None:
        """Initialize sanitizer with policy configuration."""
        self._config = config or TracingRedactionConfig()
        self._compiled_patterns = [
            re.compile(p) for p in self._config.sensitive_patterns
        ]

    def sanitize_span(self, span: RawSpanPayload) -> RedactedSpanPayload:
        """Sanitize an individual span payload.

        Args:
            span: Raw incoming span.

        Returns:
            RedactedSpanPayload safe for storage/export.
        """
        policy = self._config.policy

        if policy == SensitiveDataPolicy.ALLOW:
            return RedactedSpanPayload(
                span_id=span.span_id,
                trace_id=span.trace_id,
                name=span.name,
                category=span.category,
                data=dict(span.data),
                policy_applied=policy,
                is_sanitized=False,
                error_message=span.error_message,
                status_code=span.status_code,
            )

        if policy == SensitiveDataPolicy.OMIT:
            sanitized_data = self._omit_category_data(span.category, span.data)
            sanitized_error = (
                self._resolve_generic_error(span.category)
                if span.error_message
                else None
            )
            return RedactedSpanPayload(
                span_id=span.span_id,
                trace_id=span.trace_id,
                name=span.name,
                category=span.category,
                data=sanitized_data,
                policy_applied=policy,
                is_sanitized=True,
                error_message=sanitized_error,
                status_code=span.status_code,
            )

        # policy == SensitiveDataPolicy.MASK
        masked_data = self._mask_data_mapping(span.data)
        masked_error = (
            self._mask_string(span.error_message)
            if span.error_message
            else None
        )
        return RedactedSpanPayload(
            span_id=span.span_id,
            trace_id=span.trace_id,
            name=span.name,
            category=span.category,
            data=masked_data,
            policy_applied=policy,
            is_sanitized=True,
            error_message=masked_error,
            status_code=span.status_code,
        )

    def _omit_category_data(
        self,
        category: SpanCategory,
        data: Mapping[str, str | int | float | bool | list[str] | dict[str, str] | None],
    ) -> dict[str, str | int | float | bool | list[str] | dict[str, str] | None]:
        """Omit sensitive attributes depending on span category."""
        res: dict[str, str | int | float | bool | list[str] | dict[str, str] | None] = {}

        if category == SpanCategory.COMMAND_EXECUTION:
            # Preserve only non-sensitive operational fields
            for key in ("status", "exitCode", "exit_code"):
                if key in data:
                    res[key] = data[key]
            return res

        if category == SpanCategory.FILE_CHANGE:
            # Drop path, keep kind
            if "kind" in data:
                res["kind"] = data["kind"]
            return res

        if category == SpanCategory.MCP_TOOL:
            # Retain tool and server identifiers, omit arguments & structured content
            for key in ("server", "tool", "status"):
                if key in data:
                    res[key] = data[key]
            return res

        if category == SpanCategory.WEB_SEARCH:
            # Search query omitted to prevent PII leakage
            return res

        if category == SpanCategory.TODO_LIST:
            # Drop item text
            if "completed" in data:
                res["completed"] = data["completed"]
            return res

        if category == SpanCategory.REASONING:
            # Omit internal reasoning chain
            return res

        if category == SpanCategory.ERROR:
            # Error details stripped
            return res

        # Generic: retain only safe status keys
        for key, val in data.items():
            if key in ("status", "success", "duration_ms", "step"):
                res[key] = val
        return res

    def _resolve_generic_error(self, category: SpanCategory) -> str:
        if category == SpanCategory.MCP_TOOL:
            return self._config.generic_mcp_error_message
        return self._config.generic_error_message

    def _mask_string(self, text: str) -> str:
        """Apply regex mask rules and truncation to strings."""
        result = text
        for pattern in self._compiled_patterns:
            result = pattern.sub(self._config.redact_mask, result)
        if len(result) > self._config.max_text_length:
            result = result[: self._config.max_text_length] + "...[TRUNCATED]"
        return result

    def _mask_data_mapping(
        self,
        data: Mapping[str, str | int | float | bool | list[str] | dict[str, str] | None],
    ) -> dict[str, str | int | float | bool | list[str] | dict[str, str] | None]:
        """Recursively mask mapping values."""
        res: dict[str, str | int | float | bool | list[str] | dict[str, str] | None] = {}
        for k, v in data.items():
            if isinstance(v, str):
                res[k] = self._mask_string(v)
            elif isinstance(v, list):
                res[k] = [
                    self._mask_string(item) if isinstance(item, str) else str(item)
                    for item in v
                ]
            elif isinstance(v, dict):
                res[k] = {
                    dk: self._mask_string(str(dv)) for dk, dv in v.items()
                }
            else:
                res[k] = v
        return res
