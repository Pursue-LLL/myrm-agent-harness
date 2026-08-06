"""Tests for compression_streak_store."""

from myrm_agent_harness.agent.context_management.strategies.compression.compression_streak_store import (
    InMemoryCompressionStreakStore,
    register_compression_streak_store,
)
from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
    clear_task_metrics,
    get_task_metrics,
)


def test_in_memory_store_round_trips_via_task_metrics() -> None:
    register_compression_streak_store(InMemoryCompressionStreakStore())
    try:
        store = InMemoryCompressionStreakStore()
        register_compression_streak_store(store)
        chat_id = "chat-streak-store-1"
        clear_task_metrics(chat_id)

        assert store.get_streak(chat_id) == 0
        store.set_streak(chat_id, 2)
        assert store.get_streak(chat_id) == 2

        metrics = get_task_metrics(chat_id)
        assert metrics is not None
        assert metrics.compression_ineffective_streak == 2
    finally:
        register_compression_streak_store(None)
        clear_task_metrics("chat-streak-store-1")
