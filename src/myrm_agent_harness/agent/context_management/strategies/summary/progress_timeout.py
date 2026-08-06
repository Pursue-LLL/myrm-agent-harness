"""Progress-aware summarization timeout primitives.

Provides the building blocks for detecting stalled LLM summarization calls:
- ProgressClock: concrete inactivity tracker with monotonic timestamps
- SummaryProgressTracker: minimal Protocol for dependency inversion
- InactivityTimeoutError / TotalCeilingTimeoutError: typed timeout exceptions

[INPUT]
- (none — self-contained primitives)

[OUTPUT]
- SummaryProgressTracker: Protocol — minimal touch() interface for progress signals
- ProgressClock: class — concrete tracker with seconds_since_last_touch measurement
- InactivityTimeoutError: exception — raised when no token arrives within inactivity window
- TotalCeilingTimeoutError: exception — raised when total wall-clock ceiling is exceeded

[POS]
Progress-aware timeout primitives for summarization. Decouples timeout detection
from LLM invocation, allowing watchdog coroutines to observe liveness without
coupling to specific streaming implementations.
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class SummaryProgressTracker(Protocol):
    """Protocol for tracking streaming progress during summarization.

    Implementations are injected by the caller (Processor / compact_service)
    to allow upper layers to observe token-level liveness without coupling
    the summarizer to any specific timeout implementation.
    """

    def touch(self) -> None:
        """Signal that a new token/chunk has been received (resets inactivity clock)."""
        ...


class ProgressClock:
    """Concrete progress tracker with inactivity measurement.

    Used by watchdog coroutines to detect stalled summarization.
    Also satisfies SummaryProgressTracker protocol.
    """

    __slots__ = ("_last_touch",)

    def __init__(self) -> None:
        self._last_touch: float = time.monotonic()

    def touch(self) -> None:
        self._last_touch = time.monotonic()

    @property
    def seconds_since_last_touch(self) -> float:
        return time.monotonic() - self._last_touch


class InactivityTimeoutError(asyncio.TimeoutError):
    """Raised when summarization exceeds the inactivity timeout."""

    def __init__(self, idle_seconds: float) -> None:
        self.idle_seconds = idle_seconds
        super().__init__(f"Summarization inactivity timeout: no token for {idle_seconds:.1f}s")


class TotalCeilingTimeoutError(asyncio.TimeoutError):
    """Raised when summarization exceeds the total ceiling timeout."""

    def __init__(self, elapsed_seconds: float) -> None:
        self.elapsed_seconds = elapsed_seconds
        super().__init__(f"Summarization total ceiling timeout: {elapsed_seconds:.1f}s elapsed")
