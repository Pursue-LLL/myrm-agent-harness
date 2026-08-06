"""Pluggable compression ineffective-streak persistence.

[INPUT]
- tracking.task_metrics::get_or_create_task_metrics, get_task_metrics (POS: default in-memory backend)

[OUTPUT]
- CompressionStreakStore: Protocol for get/set streak by chat_id
- InMemoryCompressionStreakStore: TaskMetrics-backed default
- register_compression_streak_store / get_compression_streak_store

[POS]
Framework boundary for server DB-backed streak without reverse SQL dependencies in harness.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

_store: CompressionStreakStore | None = None


@runtime_checkable
class CompressionStreakStore(Protocol):
    """Read/write anti-thrash ineffective streak for a chat/session id."""

    def get_streak(self, chat_id: str | None) -> int:
        """Return persisted ineffective streak (0 when unknown/disabled)."""
        ...

    def set_streak(self, chat_id: str | None, streak: int) -> None:
        """Persist ineffective streak for chat_id."""
        ...


class InMemoryCompressionStreakStore:
    """Default store backed by process-local TaskMetrics."""

    def get_streak(self, chat_id: str | None) -> int:
        if not chat_id:
            return 0
        from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
            get_task_metrics,
        )

        metrics = get_task_metrics(chat_id)
        if metrics is None:
            return 0
        return max(0, metrics.compression_ineffective_streak)

    def set_streak(self, chat_id: str | None, streak: int) -> None:
        if not chat_id:
            return
        from myrm_agent_harness.agent.context_management.tracking.task_metrics import (
            get_or_create_task_metrics,
        )

        metrics = get_or_create_task_metrics(chat_id)
        if metrics is None:
            return
        metrics.compression_ineffective_streak = max(0, int(streak))


def get_compression_streak_store() -> CompressionStreakStore:
    """Return the active streak store (in-memory when unset)."""
    if _store is not None:
        return _store
    return InMemoryCompressionStreakStore()


def register_compression_streak_store(store: CompressionStreakStore | None) -> None:
    """Register a product-layer streak backend (None restores in-memory default)."""
    global _store
    _store = store
