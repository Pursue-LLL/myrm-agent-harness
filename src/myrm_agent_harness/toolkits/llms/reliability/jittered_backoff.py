"""Jittered backoff utilities for decorrelated retries.

Replaces fixed exponential backoff with jittered delays to prevent
thundering-herd retry spikes when multiple sessions hit the same
rate-limited provider concurrently. Also provides adaptive schedule
handling for PAAS overload conditions (such as Z.AI 1305 / "temporarily overloaded").

[INPUT]
- (none)

[OUTPUT]
- calculate_jittered_delay: Compute a jittered exponential backoff delay.
- is_paas_overload_error: Detect PAAS temporary overload (e.g. Z.AI 1305).
- calculate_adaptive_jittered_delay: Compute adaptive delay with long-ladder support for PAAS overloads.
- paas_overload_retry_ceiling: Compute retry loop ceiling for PAAS overloads.

[POS]
Jittered backoff utilities for decorrelated retries.
"""

from __future__ import annotations

import random
import threading
import time

# Monotonic counter for jitter seed uniqueness within the same process.
# Protected by a lock to avoid race conditions in concurrent retry paths.
_jitter_counter = 0
_jitter_lock = threading.Lock()

# PAAS (e.g. Z.AI Coding Plan / GLM-5.2) overload schedule.
# Short retries hammer the same scheduling window; after _PAAS_1305_SHORT_ATTEMPTS
# normal retries, the wait widens progressively to match backend queue clearing.
_PAAS_1305_LONG_BACKOFF: tuple[float, ...] = (30.0, 60.0, 90.0, 120.0)
_PAAS_1305_SHORT_ATTEMPTS: int = 3


def calculate_jittered_delay(
    attempt: int,
    *,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    jitter_ratio: float = 0.5,
    retry_after: float | None = None,
) -> float:
    """Compute a jittered exponential backoff delay.

    Args:
        attempt: 1-based retry attempt number.
        base_delay: Base delay in seconds for attempt 1.
        max_delay: Maximum delay cap in seconds.
        jitter_ratio: Fraction of computed delay to use as random jitter range.
        retry_after: Explicit wait time from HTTP header, if available.

    Returns:
        Delay in seconds.
    """
    global _jitter_counter
    with _jitter_lock:
        _jitter_counter += 1
        tick = _jitter_counter

    exponent = max(0, attempt - 1)
    if exponent >= 63 or base_delay <= 0:
        delay = max_delay
    else:
        delay = min(base_delay * (2**exponent), max_delay)

    ceiling = max_delay
    if retry_after is not None and retry_after > 0:
        delay = max(delay, float(retry_after))
        # A provider-stated wait is a floor the cap must not undercut.
        ceiling = max(max_delay, float(retry_after))

    # Seed from time + counter for decorrelation
    seed = (time.time_ns() ^ (tick * 0x9E3779B9)) & 0xFFFFFFFF
    rng = random.Random(seed)
    jitter = rng.uniform(0, jitter_ratio * delay)

    return min(delay + jitter, ceiling)


def is_paas_overload_error(error: object) -> bool:
    """True only for PAAS scheduling overloads (e.g. Z.AI 1305 / "temporarily overloaded")."""
    if error is None:
        return False
    parts = [
        str(error),
        str(getattr(error, "message", "")),
        str(getattr(error, "body", "")),
        str(getattr(error, "response", "")),
    ]
    text = " ".join(part for part in parts if part).lower()
    status_code = getattr(error, "status_code", None)
    is_429_or_overloaded = status_code in (429, 529, 503) or "429" in text or "overloaded" in text
    has_paas_overload_signature = "1305" in text or "temporarily overloaded" in text or "temporarily_overloaded" in text
    return is_429_or_overloaded and has_paas_overload_signature


def calculate_adaptive_jittered_delay(
    attempt: int,
    error: object = None,
    *,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    jitter_ratio: float = 0.5,
    retry_after: float | None = None,
    short_attempts: int = _PAAS_1305_SHORT_ATTEMPTS,
) -> tuple[float, str | None]:
    """Compute adaptive backoff delay, switching to a wider schedule for PAAS overloads.

    Args:
        attempt: 1-based retry attempt number.
        error: Current error instance (checked for PAAS 1305 signatures).
        base_delay: Base delay in seconds.
        max_delay: Maximum delay cap in seconds.
        jitter_ratio: Jitter fraction.
        retry_after: Provider-stated wait.
        short_attempts: Number of initial short attempts before wide ladder.

    Returns:
        Tuple of (delay_seconds, reason_label).
    """
    if not is_paas_overload_error(error):
        delay = calculate_jittered_delay(
            attempt,
            base_delay=base_delay,
            max_delay=max_delay,
            jitter_ratio=jitter_ratio,
            retry_after=retry_after,
        )
        return delay, None

    if attempt <= short_attempts:
        delay = calculate_jittered_delay(
            attempt,
            base_delay=base_delay,
            max_delay=max_delay,
            jitter_ratio=jitter_ratio,
            retry_after=retry_after,
        )
        return delay, "paas_1305_short"

    idx = min(attempt - short_attempts - 1, len(_PAAS_1305_LONG_BACKOFF) - 1)
    target_base = _PAAS_1305_LONG_BACKOFF[idx]
    delay = calculate_jittered_delay(
        1,
        base_delay=target_base,
        max_delay=target_base,
        jitter_ratio=0.2,
        retry_after=retry_after,
    )
    return delay, "paas_1305_long"


def paas_overload_retry_ceiling(short_attempts: int = _PAAS_1305_SHORT_ATTEMPTS) -> int:
    """Retry-loop ceiling for the full PAAS overload schedule."""
    return short_attempts + len(_PAAS_1305_LONG_BACKOFF) + 1
