"""Compression guards: anti-thrash protection and effectiveness streak tracking.

[INPUT]
- 压缩前后上下文 token 统计（由压缩执行器提供）

[OUTPUT]
- should_block_automatic_compression(): 是否阻止自动压缩（防抖）
- record_compression_effectiveness(): 记录压缩有效性
- ANTI_THRASHING_STREAK_LIMIT / EFFECTIVE_SAVINGS_THRESHOLD / SAFETY_NET_RATIO: 保护常量

[POS]
Guard rails for automatic context compression — blocks thrashing and only
repeats compression when it measurably saves tokens.
"""

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
    "EFFECTIVE_SAVINGS_THRESHOLD",
    "SAFETY_NET_RATIO",
    "CompressionStreakStore",
    "get_compression_streak_store",
    "record_compression_effectiveness",
    "register_compression_streak_store",
    "should_block_automatic_compression",
]
