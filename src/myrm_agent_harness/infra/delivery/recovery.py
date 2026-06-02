"""Delivery queue recovery logic.

Handles retry backoff calculation and permanent error detection.

[INPUT]
- QueuedDelivery (POS: 队列投递)

[OUTPUT]
- compute_backoff_ms: 计算退避时间
- is_permanent_error: 判断永久错误
- recover_pending_deliveries: 恢复待投递

[POS]
Delivery recovery logic. Exponential backoff calculation, permanent error identification, and startup recovery.

"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .storage import QueuedDelivery

logger = logging.getLogger(__name__)

MAX_RETRIES = 5

# Backoff delays in milliseconds indexed by retry count (1-based)
BACKOFF_MS: tuple[int, ...] = (
    5_000,  # retry 1: 5s
    25_000,  # retry 2: 25s
    120_000,  # retry 3: 2m
    600_000,  # retry 4: 10m
)

# Permanent error patterns (should not retry)
PERMANENT_ERROR_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"no conversation reference found", re.IGNORECASE),
    re.compile(r"chat not found", re.IGNORECASE),
    re.compile(r"user not found", re.IGNORECASE),
    re.compile(r"bot was blocked by the user", re.IGNORECASE),
    re.compile(r"forbidden: bot was kicked", re.IGNORECASE),
    re.compile(r"chat_id is empty", re.IGNORECASE),
    re.compile(r"recipient is not a valid", re.IGNORECASE),
    re.compile(r"invalid recipient", re.IGNORECASE),
    re.compile(r"permission denied", re.IGNORECASE),
    re.compile(r"unauthorized", re.IGNORECASE),
    re.compile(r"forbidden", re.IGNORECASE),
)


def compute_backoff_ms(retry_count: int) -> int:
    """Compute backoff delay in milliseconds.

    Uses predefined backoff schedule for first 4 retries, then caps at 10 minutes.

    Args:
        retry_count: Number of retries (1-based)

    Returns:
        Backoff delay in milliseconds
    """
    if retry_count <= 0:
        return 0

    # Use predefined schedule
    if retry_count <= len(BACKOFF_MS):
        return BACKOFF_MS[retry_count - 1]

    # Cap at 10 minutes for retries beyond schedule
    return BACKOFF_MS[-1]


def is_permanent_error(error: Exception) -> bool:
    """Check if error is permanent (should not retry).

    Permanent errors include:
    - Invalid recipient
    - User not found
    - Bot blocked
    - Permission denied

    Args:
        error: Exception to check

    Returns:
        True if error is permanent
    """
    error_str = str(error)

    return any(pattern.search(error_str) for pattern in PERMANENT_ERROR_PATTERNS)


def is_entry_eligible_for_recovery(delivery: QueuedDelivery, now_ms: float) -> bool:
    """Check if delivery entry is eligible for recovery retry.

    Args:
        delivery: Queued delivery
        now_ms: Current timestamp in milliseconds

    Returns:
        True if eligible for retry
    """
    # Check max retries
    if delivery.retry_count >= MAX_RETRIES:
        return False

    # Check if backoff period has elapsed
    if delivery.last_attempt_at is not None:
        backoff_ms = compute_backoff_ms(delivery.retry_count)
        next_retry_at = delivery.last_attempt_at * 1000 + backoff_ms

        if now_ms < next_retry_at:
            return False

    return True


async def recover_pending_deliveries(
    deliveries: list[QueuedDelivery], now_ms: float
) -> tuple[list[QueuedDelivery], list[QueuedDelivery], list[QueuedDelivery]]:
    """Filter deliveries into eligible, deferred, and skipped.

    Args:
        deliveries: List of pending deliveries
        now_ms: Current timestamp in milliseconds

    Returns:
        Tuple of (eligible, deferred, skipped) deliveries
    """
    eligible = []
    deferred = []
    skipped = []

    for delivery in deliveries:
        if delivery.retry_count >= MAX_RETRIES:
            skipped.append(delivery)
        elif is_entry_eligible_for_recovery(delivery, now_ms):
            eligible.append(delivery)
        else:
            deferred.append(delivery)

    return eligible, deferred, skipped
