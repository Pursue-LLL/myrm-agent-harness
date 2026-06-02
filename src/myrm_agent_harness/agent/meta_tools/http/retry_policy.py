"""HTTP Retry Policy - Exponential Backoff with Jitter + Retry-After

[INPUT]

[OUTPUT]
- is_retryable_error: check if error is retryable
- calculate_retry_delay: calculate retry delay with exponential backoff and jitter
- extract_retry_after: extract Retry-After header value from response

[POS]
HTTP retry policy. Exponential backoff with jitter and Retry-After header support for improved success rates.

"""

from __future__ import annotations

import random
from dataclasses import dataclass

import httpx


@dataclass
class RetryPolicy:
    """Retry policy configuration"""

    max_retries: int = 3
    base_delay: float = 1.0  # seconds
    backoff_factor: float = 2.0  # exponential backoff
    max_delay: float = 60.0  # cap for exponential growth
    enable_jitter: bool = True  # add random jitter to avoid thundering herd
    retryable_status_codes: frozenset[int] = frozenset({429, 502, 503, 504})


DEFAULT_RETRY_POLICY = RetryPolicy()


def is_retryable_error(error: Exception, policy: RetryPolicy) -> bool:
    """Check if error is retryable

    Args:
        error: Exception from HTTP request
        policy: RetryPolicy

    Returns:
        True if error is retryable
    """
    if isinstance(error, (httpx.NetworkError, httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout)):
        return True

    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in policy.retryable_status_codes

    return False


def extract_retry_after(error: Exception) -> float | None:
    """Extract Retry-After value from an HTTPStatusError response.

    Supports integer seconds and decimal seconds formats.
    HTTP-date format is not supported (rare in modern APIs).

    Returns:
        Delay in seconds, or None if not present / unparseable.
    """
    if not isinstance(error, httpx.HTTPStatusError):
        return None

    raw = error.response.headers.get("retry-after") or error.response.headers.get("Retry-After")
    if not raw:
        return None

    try:
        return max(0.0, float(raw))
    except (ValueError, TypeError):
        return None


def calculate_retry_delay(
    attempt: int,
    policy: RetryPolicy,
    *,
    retry_after: float | None = None,
) -> float:
    """Calculate retry delay with exponential backoff and jitter.

    When ``retry_after`` is provided (e.g. from a 429 Retry-After header),
    it takes priority over the computed exponential delay — but still has
    jitter applied to prevent thundering-herd on shared rate-limit windows.

    Args:
        attempt: Current retry attempt (1-based)
        policy: RetryPolicy
        retry_after: Optional server-specified delay (seconds)

    Returns:
        Delay in seconds
    """
    if retry_after is not None:
        delay = retry_after
    else:
        delay = policy.base_delay * (policy.backoff_factor ** (attempt - 1))

    if policy.enable_jitter:
        delay *= random.uniform(0.5, 1.5)

    return min(delay, policy.max_delay)
