"""Autonomous error self-correction governor and hypothesis generation engine.

Provides the Diagnose-Hypothesize-Repair loop for resilient long-running tasks.

[INPUT]
- .types: DiagnosticHypothesis, ErrorCorrectionOutcome, RecoveryActionType

[OUTPUT]
- ErrorSelfCorrectionGovernor: Autonomous diagnosis, hypothesis testing, and error recovery engine.

[POS]
Harness resilience engine to self-heal runtime errors and avoid catastrophic failures.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from myrm_agent_harness.agent.resilience.types import (
    DiagnosticHypothesis,
    ErrorCorrectionOutcome,
    RecoveryActionType,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

# Common error patterns mapped to root cause heuristics
_ERROR_PATTERNS: list[tuple[re.Pattern[str], RecoveryActionType, str, str]] = [
    (
        re.compile(r"(?:ModuleNotFoundError|ImportError).*?(?:No module named|cannot import name)\s*['\"]?([a-zA-Z0-9_\-]+)['\"]?|ModuleNotFoundError", re.IGNORECASE),
        RecoveryActionType.ENV_REPAIR,
        "Missing python dependency",
        "Install the required package in the workspace environment before proceeding.",
    ),
    (
        re.compile(r"(?:FileNotFoundError|NoSuchFile).*?(?:No such file or directory:?)\s*['\"]?([^\n'\"]+)['\"]?|FileNotFoundError", re.IGNORECASE),
        RecoveryActionType.SANITIZE_INPUT,
        "Target path does not exist or relative path ambiguity",
        "Verify current working directory, list directory contents, or check path spelling.",
    ),
    (
        re.compile(r"PermissionDenied|Permission denied|EACCES", re.IGNORECASE),
        RecoveryActionType.ALTERNATIVE_TOOL,
        "Filesystem permission restriction or read-only mount",
        "Check permissions or execute within isolated workspace directory.",
    ),
    (
        re.compile(r"ConnectionError|TimeoutError|ETIMEDOUT|ECONNREFUSED|504 Gateway Time-out", re.IGNORECASE),
        RecoveryActionType.RETRY,
        "Transient network latency or server timeout",
        "Perform exponential backoff retry or query fallback endpoint.",
    ),
    (
        re.compile(r"JSONDecodeError|Expecting value|Invalid \w+ JSON", re.IGNORECASE),
        RecoveryActionType.SANITIZE_INPUT,
        "Malformed JSON payload or corrupted response structure",
        "Sanitize inputs and re-parse payload without truncated boundaries.",
    ),
    (
        re.compile(r"SyntaxError|invalid syntax|Syntax error", re.IGNORECASE),
        RecoveryActionType.SANITIZE_INPUT,
        "Code syntax error in dynamic execution payload",
        "Verify language syntax, quotes balance, and bracket closures.",
    ),
]


class ErrorSelfCorrectionGovernor:
    """Autonomous error self-correction governor.

    Analyzes execution failures, generates actionable diagnosis hypotheses,
    and guides the agent loop to self-heal instead of giving up.
    """

    def __init__(self, max_recovery_attempts: int = 2) -> None:
        self.max_recovery_attempts = max_recovery_attempts

    def generate_hypotheses(
        self,
        *,
        operation: str,
        target: str,
        error_message: str,
        attempt: int = 1,
    ) -> list[DiagnosticHypothesis]:
        """Generate structured diagnostic hypotheses based on error context."""
        hypotheses: list[DiagnosticHypothesis] = []

        if attempt > self.max_recovery_attempts:
            hypotheses.append(
                DiagnosticHypothesis(
                    hypothesis_id=f"hyp-{uuid4().hex[:8]}",
                    error_summary=f"Exceeded max recovery attempts ({self.max_recovery_attempts}) for {operation}",
                    root_cause_guess="Persistent failure across multiple recovery strategies",
                    action_type=RecoveryActionType.ESCALATE,
                    confidence_score=0.99,
                    reasoning="Prevent infinite self-correction loops on deterministic errors.",
                )
            )
            return hypotheses

        # Pattern-based heuristic matching
        for pattern, action_type, root_cause, hint in _ERROR_PATTERNS:
            match = pattern.search(error_message)
            if match:
                matched_entity = match.group(1) if match.groups() else ""
                hypotheses.append(
                    DiagnosticHypothesis(
                        hypothesis_id=f"hyp-{uuid4().hex[:8]}",
                        error_summary=f"{operation} failed with {root_cause}",
                        root_cause_guess=f"{root_cause}: {matched_entity}".strip(": "),
                        action_type=action_type,
                        suggested_fix={"matched_entity": matched_entity, "hint": hint},
                        confidence_score=0.85,
                        reasoning=f"Regex signature matched known failure pattern: {pattern.pattern}",
                    )
                )

        # Fallback default hypothesis if no specific pattern matched
        if not hypotheses:
            hypotheses.append(
                DiagnosticHypothesis(
                    hypothesis_id=f"hyp-{uuid4().hex[:8]}",
                    error_summary=f"Unclassified execution failure in {operation}",
                    root_cause_guess="Tool parameter mismatch, schema violation, or unexpected runtime state",
                    action_type=RecoveryActionType.RETRY,
                    suggested_fix={"hint": "Inspect arguments, check prerequisite environment, and try alternative options."},
                    confidence_score=0.5,
                    reasoning="Default self-correction hypothesis for generic error recovery.",
                )
            )

        return hypotheses

    def diagnose_and_suggest_repair(
        self,
        *,
        operation: str,
        target: str,
        error_message: str,
        attempt: int = 1,
        prior_actions: list[str] | None = None,
    ) -> ErrorCorrectionOutcome:
        """Diagnose failure and return structured repair outcome with actionable advice."""
        hypotheses = self.generate_hypotheses(
            operation=operation,
            target=target,
            error_message=error_message,
            attempt=attempt,
        )

        primary_hyp = hypotheses[0]
        action = primary_hyp.action_type
        is_terminal = action == RecoveryActionType.ESCALATE

        details_lines = [
            f"**Diagnosed Cause**: {primary_hyp.root_cause_guess}",
            f"**Recommended Strategy**: {action.value}",
        ]
        if "hint" in primary_hyp.suggested_fix:
            details_lines.append(f"**Actionable Hint**: {primary_hyp.suggested_fix['hint']}")
        if prior_actions:
            details_lines.append(f"**Prior Attempts**: {', '.join(prior_actions)}")

        diagnostic_details = "\n".join(details_lines)

        logger.info(
            "ErrorSelfCorrectionGovernor evaluated [%s]: action=%s attempt=%d/%d",
            operation,
            action.value,
            attempt,
            self.max_recovery_attempts,
        )

        return ErrorCorrectionOutcome(
            success=not is_terminal,
            action_taken=action,
            original_error=error_message,
            diagnostic_details=diagnostic_details,
            attempts_made=attempt,
            fallback_message=(
                f"Self-correction ceiling reached for '{operation}'. Stop repeating this exact action."
                if is_terminal
                else None
            ),
        )
