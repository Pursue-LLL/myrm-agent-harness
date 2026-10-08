"""
[POS] src/myrm_agent_harness/core/security/execution_approval_sanitizer/facade.py
[INPUT] types, redaction_engine
[OUTPUT] ExecutionApprovalSanitizerFacade
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .redaction_engine import ExecutionApprovalSecretRedactionEngine
from .types import (
    ApprovalPayloadRequest,
    SanitizationResult,
    SanitizerMetrics,
)


class ExecutionApprovalSanitizerFacade:
    """Unified entrypoint for execution approval sensitive credential redaction."""

    def __init__(
        self, engine: ExecutionApprovalSecretRedactionEngine | None = None
    ) -> None:
        self._engine = engine or ExecutionApprovalSecretRedactionEngine()
        self._metrics = SanitizerMetrics()

    @property
    def metrics(self) -> SanitizerMetrics:
        """Shared operational telemetry counters."""
        return self._metrics

    def sanitize_payload(
        self, request: ApprovalPayloadRequest
    ) -> SanitizationResult:
        """Sanitize raw execution command or prompt payload before presenting to human."""
        self._metrics.payloads_evaluated_total += 1
        result = self._engine.sanitize_text(request.raw_command_or_text)

        if result.redactions_count > 0:
            self._metrics.redacted_payloads_total += 1
            self._metrics.total_secrets_redacted_count += result.redactions_count
        else:
            self._metrics.clean_payloads_total += 1

        return result

    def sanitize_raw_text(self, text: str) -> SanitizationResult:
        """Direct helper to sanitize raw command string."""
        self._metrics.payloads_evaluated_total += 1
        result = self._engine.sanitize_text(text)

        if result.redactions_count > 0:
            self._metrics.redacted_payloads_total += 1
            self._metrics.total_secrets_redacted_count += result.redactions_count
        else:
            self._metrics.clean_payloads_total += 1

        return result
