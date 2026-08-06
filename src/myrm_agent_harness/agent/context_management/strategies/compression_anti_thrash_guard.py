"""Anti-thrashing guard for automatic compression paths.

[INPUT]
- compression_streak_store::get_compression_streak_store (POS: pluggable streak persistence)
- tracking.task_metrics::get_or_create_task_metrics (POS: in-memory mirror for pipeline metrics)

[OUTPUT]
- should_block_automatic_compression: skip when ineffective streak is high and below safety net
- record_compression_effectiveness: update streak after a compaction attempt

[POS]
Framework guard export shared by Pipeline CompressProcessor and server ``compact_chat``.
Mirrors CompressProcessor anti-thrashing semantics (streak limit + 90% safety net).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

ANTI_THRASHING_STREAK_LIMIT: int = 2
EFFECTIVE_SAVINGS_THRESHOLD: float = 0.10
SAFETY_NET_RATIO: float = 0.90


def _read_ineffective_streak(chat_id: str | None) -> int:
    if not chat_id:
        return 0
    from myrm_agent_harness.agent.context_management.strategies.compression_streak_store import (
        get_compression_streak_store,
    )

    return get_compression_streak_store().get_streak(chat_id)


def should_block_automatic_compression(
    chat_id: str | None,
    total_tokens: int,
    max_context_tokens: int,
) -> bool:
    """Return True when recent ineffective compactions should block this attempt."""
    streak = _read_ineffective_streak(chat_id)
    if streak < ANTI_THRASHING_STREAK_LIMIT:
        return False
    window = max_context_tokens or 128_000
    if total_tokens < int(window * SAFETY_NET_RATIO):
        logger.info(
            "[Compress] Anti-thrashing: skipping (streak=%d, tokens=%d < 90%% hard limit)",
            streak,
            total_tokens,
        )
        return True
    logger.warning(
        "[Compress] Anti-thrashing overridden by 90%% safety net (streak=%d, tokens=%d)",
        streak,
        total_tokens,
    )
    return False


def record_compression_effectiveness(
    chat_id: str | None,
    *,
    original_tokens: int,
    tokens_saved: int,
) -> None:
    """Update ineffective streak from compaction token savings."""
    if not chat_id or original_tokens <= 0:
        return
    from myrm_agent_harness.agent.context_management.strategies.compression_streak_store import (
        get_compression_streak_store,
    )
    from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
        get_or_create_task_metrics,
    )

    store = get_compression_streak_store()
    current = store.get_streak(chat_id)
    savings_pct = tokens_saved / original_tokens
    if savings_pct >= EFFECTIVE_SAVINGS_THRESHOLD:
        next_streak = 0
    else:
        next_streak = current + 1
    store.set_streak(chat_id, next_streak)

    metrics = get_or_create_task_metrics(chat_id)
    if metrics is not None:
        metrics.compression_ineffective_streak = next_streak
