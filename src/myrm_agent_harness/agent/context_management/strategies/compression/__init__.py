"""Compression guards: anti-thrash protection and effectiveness streak tracking."""

from .compression_anti_thrash_guard import (
    ANTI_THRASHING_STREAK_LIMIT,
    EFFECTIVE_SAVINGS_THRESHOLD,
    SAFETY_NET_RATIO,
    record_compression_effectiveness,
    should_block_automatic_compression,
)
from .compression_streak_store import (
    CompressionStreakStore,
    get_compression_streak_store,
    register_compression_streak_store,
)

__all__ = [
    "ANTI_THRASHING_STREAK_LIMIT",
    "CompressionStreakStore",
    "EFFECTIVE_SAVINGS_THRESHOLD",
    "SAFETY_NET_RATIO",
    "get_compression_streak_store",
    "record_compression_effectiveness",
    "register_compression_streak_store",
    "should_block_automatic_compression",
]
