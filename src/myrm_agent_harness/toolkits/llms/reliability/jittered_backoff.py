"""Jittered backoff utilities for decorrelated retries.

Replaces fixed exponential backoff with jittered delays to prevent
thundering-herd retry spikes when multiple sessions hit the same
rate-limited provider concurrently.

[INPUT]
- (none)

[OUTPUT]
- calculate_jittered_delay: Compute a jittered exponential backoff delay.

[POS]
Jittered backoff utilities for decorrelated retries.
"""

import random
import threading
import time

# Monotonic counter for jitter seed uniqueness within the same process.
# Protected by a lock to avoid race conditions in concurrent retry paths.
_jitter_counter = 0
_jitter_lock = threading.Lock()


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

    if retry_after is not None and retry_after > 0:
        delay = max(delay, float(retry_after))

    # Seed from time + counter for decorrelation
    seed = (time.time_ns() ^ (tick * 0x9E3779B9)) & 0xFFFFFFFF
    rng = random.Random(seed)
    jitter = rng.uniform(0, jitter_ratio * delay)

    return min(delay + jitter, max_delay)
