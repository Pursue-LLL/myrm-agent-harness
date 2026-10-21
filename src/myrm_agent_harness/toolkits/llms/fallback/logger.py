"""Fallback decision logging.

Provides structured logging for model fallback decisions.

[INPUT]
(No external dependencies)

[OUTPUT]
- log_fallback_attempt: recordattempt
- log_fallback_decision: recorddecision

[POS]
Fallback decision logger. Structured logging of each fallback attempt and decision for tracing and analysis.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def log_fallback_attempt(
    model_name: str,
    error_kind: str,
    is_failoverable: bool,
) -> None:
    """Log a fallback attempt.

    Args:
        model_name: Model name
        error_kind: Error kind (from classifier)
        is_failoverable: Whether error is failoverable
    """
    logger.info(
        "Fallback attempt",
        extra={
            "model": model_name,
            "error_kind": error_kind,
            "is_failoverable": is_failoverable,
        },
    )


def log_fallback_decision(
    from_model: str,
    to_model: str,
    reason: str,
) -> None:
    """Log a fallback decision.

    Args:
        from_model: Source model name
        to_model: Target model name
        reason: Reason for fallback
    """
    logger.info(
        f"Fallback decision: {from_model} → {to_model}",
        extra={
            "from_model": from_model,
            "to_model": to_model,
            "reason": reason,
        },
    )
