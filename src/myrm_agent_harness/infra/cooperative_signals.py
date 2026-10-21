"""Cooperative cancellation and pause probe signals for background cognitive tasks.

[INPUT]
- None (pure stdlib primitives)

[OUTPUT]
- PauseRequestedError: Exception raised when cooperative pause is enforced.
- CooperativePauseSignal: Non-blocking probe token passed into long-running tasks; a pause may carry a TTL so it lapses on its own.

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
        self._pause_deadline: float | None = None
        self._cursor: str | None = None

    @property
    def is_pause_requested(self) -> bool:
        """Check if foreground activity or system constraints require task yield.

        A pause requested with a TTL lapses on its own, so a requester that never polls
        its own expiry cannot leave background work blocked indefinitely.
        """
        if self._pause_requested and self._pause_deadline is not None and time.monotonic() >= self._pause_deadline:
            self.clear()
        return self._pause_requested

    @property
    def pause_reason(self) -> str:
        return self._pause_reason

    def request_pause(self, reason: str = "foreground_user_activity", ttl_seconds: float | None = None) -> None:
        """Signal background worker to yield at the earliest safe transaction boundary.

        Args:
            reason: Why background work should yield.
            ttl_seconds: Seconds after which the pause lapses by itself; ``None`` holds it until ``clear()``.
        """
        self._pause_requested = True
        self._pause_reason = reason
        self._pause_deadline = None if ttl_seconds is None else time.monotonic() + ttl_seconds

    def clear(self) -> None:
        """Resume or reset pause state."""
        self._pause_requested = False
        self._pause_reason = ""
        self._pause_deadline = None

    def checkpoint_cursor(self, cursor: str) -> None:
        """Persist safe resumption cursor before exiting."""
        self._cursor = cursor

    @property
    def cursor(self) -> str | None:
        """Return persisted cursor for incremental resumption."""
        return self._cursor

    def raise_if_paused(self) -> None:
        """Raise PauseRequestedError if pause was requested at transaction boundary."""
        if self.is_pause_requested:
            raise PauseRequestedError(self._pause_reason)


_GLOBAL_PAUSE_SIGNAL: CooperativePauseSignal | None = None


def get_global_pause_signal() -> CooperativePauseSignal:
    """Obtain or initialize the global shared cooperative pause signal singleton."""
    global _GLOBAL_PAUSE_SIGNAL
    if _GLOBAL_PAUSE_SIGNAL is None:
        _GLOBAL_PAUSE_SIGNAL = CooperativePauseSignal()
    return _GLOBAL_PAUSE_SIGNAL
