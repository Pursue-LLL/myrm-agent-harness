"""Fine-grained error classifier and Full Jitter exponential backoff engine.

Classifies errors into transient-retryable versus fatal-non-retryable categories
and computes jittered backoff delays to prevent synchronized retry storms.

[INPUT]
- __future__
- asyncio
- random
- circuit_breaker_types

[OUTPUT]
- ErrorClassifier
- FullJitterBackoff

[POS]
Fine-grained error classifier and Full Jitter exponential backoff engine.
"""

from __future__ import annotations

import asyncio
import random

from .circuit_breaker_types import ErrorCategory


class ErrorClassifier:
    """Classifies tool exceptions into retryable transient faults or fatal errors."""

    _TRANSIENT_EXC_TYPES: tuple[type[BaseException], ...] = (
        TimeoutError,
        asyncio.TimeoutError,
        ConnectionResetError,
        ConnectionRefusedError,
        ConnectionError,
        BrokenPipeError,
    )

    _TRANSIENT_KEYWORDS: tuple[str, ...] = (
        "429",
        "too many requests",
        "rate limit",
        "502",
        "503",
        "504",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        "connection reset",
        "timed out",
        "handshake failure",
    )

    _FATAL_KEYWORDS: tuple[str, ...] = (
        "400",
        "bad request",
        "401",
        "unauthorized",
        "403",
        "forbidden",
        "not found",
        "validation error",
        "schema error",
    )

    @classmethod
    def classify(cls, exc: BaseException) -> ErrorCategory:
        """Classify an exception to establish strict retry boundaries."""
        msg = str(exc).lower()

        # Check fatal keywords first (e.g. 401 Unauthorized must never be retried)
        if any(keyword in msg for keyword in cls._FATAL_KEYWORDS):
            return ErrorCategory.NON_RETRYABLE_FATAL

        # Check transient exception types
        if isinstance(exc, cls._TRANSIENT_EXC_TYPES):
            return ErrorCategory.RETRYABLE_TRANSIENT

        # Check transient keywords in exception message
        if any(keyword in msg for keyword in cls._TRANSIENT_KEYWORDS):
            return ErrorCategory.RETRYABLE_TRANSIENT

        # Default standard logic/programming errors are non-retryable
        return ErrorCategory.NON_RETRYABLE_FATAL


class FullJitterBackoff:
    """Computes exponential backoff delays with AWS-style Full Jitter to eliminate resonance."""

    @staticmethod
    def compute_delay(
        attempt: int,
        base_backoff_s: float = 0.5,
        max_backoff_s: float = 5.0,
    ) -> float:
        """Calculate random uniform delay between 0 and min(max_backoff, base * 2^attempt)."""
        temp = min(max_backoff_s, base_backoff_s * (2**attempt))
        return random.uniform(0.0, temp)
