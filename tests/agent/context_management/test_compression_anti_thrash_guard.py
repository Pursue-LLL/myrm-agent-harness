"""Unit tests for compression_anti_thrash_guard."""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.strategies.compression.compression_anti_thrash_guard import (
    ANTI_THRASHING_STREAK_LIMIT,
    record_compression_effectiveness,
    should_block_automatic_compression,
)
from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
    create_task_metrics,
    get_task_metrics,
)


def test_should_block_when_streak_high_and_below_safety_net() -> None:
    chat_id = "guard-block-test"
    metrics = create_task_metrics(chat_id)
    metrics.compression_ineffective_streak = ANTI_THRASHING_STREAK_LIMIT

    assert should_block_automatic_compression(
        chat_id, total_tokens=50_000, max_context_tokens=128_000
    )


def test_should_not_block_when_above_safety_net() -> None:
    chat_id = "guard-override-test"
    metrics = create_task_metrics(chat_id)
    metrics.compression_ineffective_streak = ANTI_THRASHING_STREAK_LIMIT

    assert not should_block_automatic_compression(
        chat_id,
        total_tokens=int(128_000 * 0.91),
        max_context_tokens=128_000,
    )


def test_record_resets_streak_on_effective_savings() -> None:
    chat_id = "guard-record-reset"
    metrics = create_task_metrics(chat_id)
    metrics.compression_ineffective_streak = 2

    record_compression_effectiveness(
        chat_id, original_tokens=10_000, tokens_saved=2_000
    )

    updated = get_task_metrics(chat_id)
    assert updated is not None
    assert updated.compression_ineffective_streak == 0


def test_record_increments_streak_on_ineffective_savings() -> None:
    chat_id = "guard-record-inc"
    metrics = create_task_metrics(chat_id)
    metrics.compression_ineffective_streak = 1

    record_compression_effectiveness(chat_id, original_tokens=10_000, tokens_saved=50)

    updated = get_task_metrics(chat_id)
    assert updated is not None
    assert updated.compression_ineffective_streak == 2


def test_record_creates_metrics_when_missing() -> None:
    chat_id = "guard-record-missing-metrics"

    record_compression_effectiveness(chat_id, original_tokens=10_000, tokens_saved=50)

    updated = get_task_metrics(chat_id)
    assert updated is not None
    assert updated.compression_ineffective_streak == 1
