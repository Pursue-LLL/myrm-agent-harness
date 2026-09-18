"""Cooperative cancellation and pause probe signals for background cognitive tasks.

[INPUT]
- None (pure stdlib primitives)

[OUTPUT]
- PauseRequestedError: Exception raised when cooperative pause is enforced.
- CooperativePauseSignal: Non-blocking probe token passed into long-running tasks.

[POS]
Infrastructure layer. Provides transaction-boundary cooperative yielding
so background consolidation immediately yields SQLite write locks when
foreground users type. Stdlib-only and framework-agnostic; imported by
toolkits/memory/ and runtime/cognitive_clock/.
"""

from __future__ import annotations

import time


class PauseRequestedError(Exception):
    """Raised when a cooperative cognitive task is halted at transaction boundary."""

    def __init__(self, reason: str = "user_activity_detected") -> None:
        super().__init__(f"Cognitive task cooperatively paused: {reason}")
        self.reason = reason


class CooperativePauseSignal:
    """Thread-safe cooperative pause probe token for long-running cognitive maintenance."""

    def __init__(self) -> None:
        self._pause_requested: bool = False
        self._pause_reason: str = ""
        self._cursor: str | None = None
        self._last_requested_at: float = 0.0

    @property
    def is_pause_requested(self) -> bool:
        """Check if foreground activity or system constraints require task yield."""
        return self._pause_requested

    @property
    def pause_reason(self) -> str:
        return self._pause_reason

    def request_pause(self, reason: str = "foreground_user_activity") -> None:
        """Signal background worker to yield at the earliest safe transaction boundary."""
        self._pause_requested = True
        self._pause_reason = reason
        self._last_requested_at = time.time()

    def clear(self) -> None:
        """Resume or reset pause state."""
        self._pause_requested = False
        self._pause_reason = ""

    def checkpoint_cursor(self, cursor: str) -> None:
        """Persist safe resumption cursor before exiting."""
        self._cursor = cursor

    @property
    def cursor(self) -> str | None:
        """Return persisted cursor for incremental resumption."""
        return self._cursor

    def raise_if_paused(self) -> None:
        """Raise PauseRequestedError if pause was requested at transaction boundary."""
        if self._pause_requested:
            raise PauseRequestedError(self._pause_reason)


_GLOBAL_PAUSE_SIGNAL: CooperativePauseSignal | None = None


def get_global_pause_signal() -> CooperativePauseSignal:
    """Obtain or initialize the global shared cooperative pause signal singleton."""
    global _GLOBAL_PAUSE_SIGNAL
    if _GLOBAL_PAUSE_SIGNAL is None:
        _GLOBAL_PAUSE_SIGNAL = CooperativePauseSignal()
    return _GLOBAL_PAUSE_SIGNAL
