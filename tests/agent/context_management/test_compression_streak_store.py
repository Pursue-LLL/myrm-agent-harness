"""Tests for compression_streak_store."""

from unittest.mock import patch

from myrm_agent_harness.agent.context_management.strategies.compression.compression_streak_store import (
    InMemoryCompressionStreakStore,
    get_compression_streak_store,
    register_compression_streak_store,
)
from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
    clear_task_metrics,
    get_task_metrics,
)


def test_in_memory_store_round_trips_via_task_metrics() -> None:
    store = InMemoryCompressionStreakStore()
    register_compression_streak_store(store)
    try:
        # Registered store is served by get_compression_streak_store (registered branch).
        assert get_compression_streak_store() is store
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


def test_get_streak_with_empty_chat_id_returns_zero() -> None:
    """Empty chat_id must short-circuit to 0 (no task-metrics lookup)."""
    store = InMemoryCompressionStreakStore()
    assert store.get_streak(None) == 0
    assert store.get_streak("") == 0


def test_set_streak_with_empty_chat_id_is_noop() -> None:
    """Empty chat_id must be a silent no-op (no task-metrics write)."""
    store = InMemoryCompressionStreakStore()
    store.set_streak(None, 5)
    store.set_streak("", 5)


def test_set_streak_when_task_metrics_unavailable_is_noop() -> None:
    """get_or_create_task_metrics returning None must not raise."""
    store = InMemoryCompressionStreakStore()
    with patch(
        "myrm_agent_harness.agent.context_management.tracking.task_metrics.get_or_create_task_metrics",
        return_value=None,
    ):
        store.set_streak("chat-missing-metrics", 3)
    assert store.get_streak("chat-missing-metrics") == 0


def test_get_store_falls_back_to_in_memory_when_unregistered() -> None:
    """Unregistered store must fall back to the in-memory implementation."""
    register_compression_streak_store(None)
    try:
        store = get_compression_streak_store()
        assert isinstance(store, InMemoryCompressionStreakStore)
    finally:
        register_compression_streak_store(None)
