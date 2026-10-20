"""Dynamic watermark pre-warning heartbeat guard for subagent task execution.

Monitors execution turn usage and emits a structured pre-warning alert when a subagent
crosses the 80% watermark threshold of its configured turn budget.

[INPUT]
- threading
- types

[OUTPUT]
- SubagentWatermarkGuard

[POS]
Dynamic watermark pre-warning heartbeat guard for subagent task execution.
"""

import threading

from .types import (
    DEFAULT_WATERMARK_THRESHOLD_RATIO,
    WatermarkAlert,
)


class SubagentWatermarkGuard:
    """Thread-safe watcher monitoring subagent turn usage against the 80% alert watermark."""

    def __init__(self, threshold_ratio: float = DEFAULT_WATERMARK_THRESHOLD_RATIO) -> None:
        self._threshold_ratio: float = max(0.1, min(0.99, threshold_ratio))
        self._alerted_tasks: set[str] = set()
        self._current_turns: dict[str, int] = {}
        self._lock: threading.Lock = threading.Lock()

    @property
    def threshold_ratio(self) -> float:
        """Configured alert watermark threshold ratio (e.g. 0.80)."""
        return self._threshold_ratio

    def record_turn_and_check(
        self,
        task_id: str,
        current_turn: int,
        max_turns: int,
    ) -> WatermarkAlert | None:
        """Record turn step and check if the 80% watermark threshold is newly crossed.

        Returns a WatermarkAlert only upon the first transition across the watermark.
        """
        if max_turns <= 0:
            return None

        with self._lock:
            self._current_turns[task_id] = current_turn
            ratio = current_turn / max_turns

            if ratio >= self._threshold_ratio and task_id not in self._alerted_tasks:
                self._alerted_tasks.add(task_id)
                remaining = max(0, max_turns - current_turn)
                msg = (
                    f"Subagent task '{task_id}' reached {ratio * 100:.1f}% of turn budget "
                    f"({current_turn}/{max_turns} turns, {remaining} turns remaining). "
                    "Consider checkpointing or delegating further steps."
                )
                return WatermarkAlert(
                    task_id=task_id,
                    current_turn=current_turn,
                    max_turns=max_turns,
                    usage_ratio=round(ratio, 4),
                    turns_remaining=remaining,
                    warning_message=msg,
                )

            return None

    def is_task_alerted(self, task_id: str) -> bool:
        """Check whether an alert has already fired for this task."""
        with self._lock:
            return task_id in self._alerted_tasks

    def get_current_turn(self, task_id: str) -> int:
        """Query the last recorded turn for the task."""
        with self._lock:
            return self._current_turns.get(task_id, 0)

    def clear_task(self, task_id: str) -> None:
        """Clean up tracking state when a task completes or terminates."""
        with self._lock:
            self._alerted_tasks.discard(task_id)
            self._current_turns.pop(task_id, None)

    def reset_all(self) -> None:
        """Clear all active monitoring state."""
        with self._lock:
            self._alerted_tasks.clear()
            self._current_turns.clear()
