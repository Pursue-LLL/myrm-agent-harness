"""Trace processor ensuring redaction policy compliance across lifecycle states.

[INPUT]
- Trace lifecycle hooks (start, update, stream chunk, error, end).

[OUTPUT]
- Cleaned RedactedSpanPayloads emitted to downstream trace collectors.

[POS]
- Coordinating telemetry processor that guarantees zero leakage across normal,
  streaming, error, retry, and resumed agent operations.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from myrm_agent_harness.core.security.tracing_redaction.sanitizer import (
    TracingSpanSanitizer,
)
from myrm_agent_harness.core.security.tracing_redaction.types import (
    RawSpanPayload,
    RedactedSpanPayload,
    TracingRedactionConfig,
)

logger = logging.getLogger(__name__)


@dataclass
class RedactionAuditStats:
    """Telemetry redaction audit metrics."""

    total_spans_processed: int = 0
    spans_redacted: int = 0
    streaming_spans: int = 0
    retry_spans: int = 0
    resume_spans: int = 0
    error_spans: int = 0


class TracingRedactionProcessor:
    """Telemetry processor enforcing sensitive-data policies on all spans."""

    def __init__(
        self,
        config: TracingRedactionConfig | None = None,
        sanitizer: TracingSpanSanitizer | None = None,
    ) -> None:
        """Initialize the processor with configuration and sanitizer.

        Args:
            config: Redaction configuration settings.
            sanitizer: Optional pre-configured sanitizer instance.
        """
        self._config = config or TracingRedactionConfig()
        self._sanitizer = sanitizer or TracingSpanSanitizer(config=self._config)
        self._stats = RedactionAuditStats()
        self._completed_spans: list[RedactedSpanPayload] = []

    @property
    def config(self) -> TracingRedactionConfig:
        """Return the active configuration."""
        return self._config

    @property
    def stats(self) -> RedactionAuditStats:
        """Return audit metrics."""
        return self._stats

    def process_span(self, span: RawSpanPayload) -> RedactedSpanPayload:
        """Process and sanitize an individual span payload.

        Args:
            span: Raw incoming telemetry span.

        Returns:
            Sanitized RedactedSpanPayload.
        """
        self._stats.total_spans_processed += 1
        if span.is_streaming:
            self._stats.streaming_spans += 1
        if span.is_retry:
            self._stats.retry_spans += 1
        if span.is_resume:
            self._stats.resume_spans += 1
        if span.error_message:
            self._stats.error_spans += 1

        redacted = self._sanitizer.sanitize_span(span)
        if redacted.is_sanitized:
            self._stats.spans_redacted += 1

        self._completed_spans.append(redacted)
        return redacted

    def process_batch(
        self, spans: Sequence[RawSpanPayload]
    ) -> list[RedactedSpanPayload]:
        """Process a batch of spans.

        Args:
            spans: Sequence of incoming raw spans.

        Returns:
            List of sanitized RedactedSpanPayload instances.
        """
        return [self.process_span(s) for s in spans]

    def get_exported_spans(self) -> list[RedactedSpanPayload]:
        """Return all sanitized spans ready for telemetry export."""
        return list(self._completed_spans)

    def clear(self) -> None:
        """Reset internal buffers and stats."""
        self._completed_spans.clear()
        self._stats = RedactionAuditStats()
