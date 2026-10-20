"""[INPUT] SubagentFailureStage, SubagentFailureCategory, RemediationAction, StructuredFailureFact, and SafeFailureSanitizer.
[OUTPUT] SubagentDiagnosticProtocol generating single-line diagnostic headers and actionable failure facts.
[POS] Protocol implementation for Subagent Bounded Structured Failure Facts & Privacy-Preserving Diagnostic Protocol.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from .sanitizer import SafeFailureSanitizer
from .types import (
    RemediationAction,
    StructuredFailureFact,
    SubagentFailureCategory,
    SubagentFailureStage,
)

logger = logging.getLogger(__name__)


class SubagentDiagnosticProtocol:
    """Protocol governing single-line diagnostic header generation, error classification, and self-healing recommendations."""

    @staticmethod
    def format_diagnostic_header(
        product: str,
        stage: SubagentFailureStage,
        category: SubagentFailureCategory,
        http_status: int | None = None,
        exit_code: int | None = None,
        signal: str | None = None,
    ) -> str:
        """Render standard single-line safe diagnostic header matching DeepSeek Harness specification.

        Format:
        Product subagent failure (product: <product>; stage: <stage>; category: <category>; HTTP status: <status>; exit code: <code>; signal: <signal>)
        """
        status_str = str(http_status) if http_status is not None else "none"
        code_str = str(exit_code) if exit_code is not None else "none"
        sig_str = signal if signal else "none"

        return (
            f"Product subagent failure (product: {product}; "
            f"stage: {stage.value}; "
            f"category: {category.value}; "
            f"HTTP status: {status_str}; "
            f"exit code: {code_str}; "
            f"signal: {sig_str})"
        )

    @classmethod
    def classify_failure(
        cls,
        raw_message: str = "",
        http_status: int | None = None,
        exit_code: int | None = None,
        signal: str | None = None,
    ) -> SubagentFailureCategory:
        """Classify subagent failure into a machine-actionable category using explicit signals and heuristic keywords."""
        msg_lower = raw_message.lower()

        # 1. HTTP Status mapping
        if http_status == 429 or "rate limit" in msg_lower or "quota exceeded" in msg_lower or "tpm" in msg_lower:
            return SubagentFailureCategory.RATE_LIMITED

        if http_status in (401, 403) or "unauthorized" in msg_lower or "forbidden" in msg_lower or "permission denied" in msg_lower:
            return SubagentFailureCategory.AUTH_ERROR

        # 2. Context window exceeded
        if (
            (
                "context" in msg_lower
                and ("window" in msg_lower or "length" in msg_lower or "overflow" in msg_lower or "maximum" in msg_lower)
            )
            or "prompt is too long" in msg_lower
            or "token limit exceeded" in msg_lower
        ):
            return SubagentFailureCategory.CONTEXT_WINDOW_EXCEEDED

        # 3. Budget & Turn limits
        if "session budget" in msg_lower or "cost limit exceeded" in msg_lower or "budget exhausted" in msg_lower:
            return SubagentFailureCategory.SESSION_BUDGET_EXCEEDED

        if "max turns" in msg_lower or "turn limit reached" in msg_lower or "maximum iterations" in msg_lower:
            return SubagentFailureCategory.ERROR_MAX_TURNS

        # 4. Process abortion by signal
        if signal in ("SIGTERM", "SIGKILL", "SIGINT") or exit_code in (130, 137, 143):
            return SubagentFailureCategory.PROCESS_ABORTED

        # 5. Network timeouts
        if (
            "timed out" in msg_lower
            or "timeout" in msg_lower
            or "connection error" in msg_lower
            or "socket hang up" in msg_lower
            or http_status in (504, 408)
        ):
            return SubagentFailureCategory.NETWORK_TIMEOUT

        # 6. Sandbox failures
        if (
            "sandbox" in msg_lower
            or "container" in msg_lower
            or "oom" in msg_lower
            or "out of memory" in msg_lower
            or exit_code == 137
        ):
            return SubagentFailureCategory.SANDBOX_ERROR

        return SubagentFailureCategory.UNKNOWN_FAILURE

    @classmethod
    def derive_remediation(
        cls,
        category: SubagentFailureCategory,
        stage: SubagentFailureStage,
    ) -> RemediationAction:
        """Derive deterministic self-healing guidance for parent orchestrator."""
        if category == SubagentFailureCategory.CONTEXT_WINDOW_EXCEEDED:
            return RemediationAction.COMPACT_AND_RESUME

        if category == SubagentFailureCategory.RATE_LIMITED:
            return RemediationAction.RETRY_WITH_BACKOFF

        if category == SubagentFailureCategory.NETWORK_TIMEOUT:
            return RemediationAction.RETRY_ONCE

        if category == SubagentFailureCategory.SESSION_BUDGET_EXCEEDED:
            return RemediationAction.ABORT_EARLY

        if category == SubagentFailureCategory.AUTH_ERROR:
            return RemediationAction.ESCALATE_TO_USER

        if category == SubagentFailureCategory.SANDBOX_ERROR:
            return RemediationAction.RESPAWN_CLEAN_SANDBOX

        if category == SubagentFailureCategory.ERROR_MAX_TURNS:
            return RemediationAction.SYNTHESIZE_PARTIAL_FINDINGS

        # Fallback based on stage
        if stage in (SubagentFailureStage.QUERY_START, SubagentFailureStage.THREAD_START):
            return RemediationAction.RETRY_ONCE

        return RemediationAction.RETRY_WITH_BACKOFF

    @classmethod
    def create_failure_fact(
        cls,
        product: str,
        stage: SubagentFailureStage,
        raw_message: str,
        category: SubagentFailureCategory | None = None,
        http_status: int | None = None,
        exit_code: int | None = None,
        signal: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StructuredFailureFact:
        """Create a fully bounded, privacy-sanitized StructuredFailureFact with safe header and remediation guidance."""
        # 1. Resolve category if not specified
        resolved_category = category or cls.classify_failure(
            raw_message=raw_message,
            http_status=http_status,
            exit_code=exit_code,
            signal=signal,
        )

        # 2. Derive remediation
        remediation = cls.derive_remediation(resolved_category, stage)

        # 3. Format standard header
        header = cls.format_diagnostic_header(
            product=product,
            stage=stage,
            category=resolved_category,
            http_status=http_status,
            exit_code=exit_code,
            signal=signal,
        )

        # 4. Sanitize message & enforce 4096-byte boundary
        clean_msg = SafeFailureSanitizer.sanitize_text(raw_message)
        bounded_msg, byte_count = SafeFailureSanitizer.enforce_byte_limit(clean_msg)

        # Sanitize metadata dictionary
        safe_meta: dict[str, str] = {}
        if metadata:
            for k, v in metadata.items():
                safe_meta[k] = SafeFailureSanitizer.sanitize_text(v)

        return StructuredFailureFact(
            product=product,
            stage=stage,
            category=resolved_category,
            http_status=http_status,
            exit_code=exit_code,
            signal=signal,
            sanitized_message=bounded_msg,
            remediation=remediation,
            safe_diagnostic_header=header,
            byte_size=byte_count,
            metadata=safe_meta,
        )
