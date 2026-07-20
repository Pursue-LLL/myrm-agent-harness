"""Shared data types for the background bash-process registry.

These dataclasses / exception / typing aliases live in a dedicated module
so that:

1. The registry implementation file stays small enough to fit one screen
   of mental working set (logic + I/O without a 400-line type block).
2. Downstream consumers (bash tool, surface tools) can import the
   snapshot type without pulling in the registry singleton and its
   ``atexit`` hook — useful for type-only imports in callsites that
   never spawn jobs.

[INPUT]
- toolkits.code_execution.executors.models::AsyncProcessProtocol (POS: AsyncProcessProtocol — wait/terminate/kill handle.)

[OUTPUT]
- BackgroundProcessInfo: Snapshot dataclass exposed to UI/LLM.
- BackgroundQuotaError: Per-session concurrency cap breach.
- FinishListener / ProgressListener: Async callback type aliases used by
  the bash tool to bridge registry lifecycle events into ``ptc_notify`` UI
  updates.

[POS]
PTC-adjacent runtime helper. Pure data types — no I/O, no logging.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


class BackgroundQuotaError(RuntimeError):
    """Raised when a session would exceed its allowed concurrent background jobs."""

    def __init__(self, session_id: str | None, limit: int) -> None:
        super().__init__(f"Session {session_id!r} already has {limit} active background jobs.")
        self.session_id = session_id
        self.limit = limit


@dataclass
class BackgroundProcessInfo:
    """Snapshot of a tracked background process (LLM/UI consumable).

    ``last_progress`` is the most recent ptc_notify payload distilled out of
    stdout/stderr (explicit ``MYRM_PROGRESS`` marker or heuristic ``42%`` /
    ``3/10 tests`` parse). It lets ``bash_process_tool`` list action answer the
    "how far along is each background job?" question in a single token-cheap
    call instead of forcing the LLM to follow up with one
    ``bash_process_tool(action='output')`` per pid. The ``updated_at`` epoch second is
    embedded by the registry so a multi-minute-old snapshot is recognisable
    without extra bookkeeping. Mirrors ``jcode``'s
    ``TaskStatusFile.progress`` field.
    """

    pid: int
    command: str
    session_id: str | None
    started_at: float
    status: str  # "running" | "exited" | "killed"
    exit_code: int | None = None
    error_category: str | None = None
    last_stdout_tail: list[str] = field(default_factory=list)
    last_stderr_tail: list[str] = field(default_factory=list)
    last_progress: dict[str, object] | None = None

    @property
    def uptime_seconds(self) -> float:
        return max(0.0, time.time() - self.started_at)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "pid": self.pid,
            "command": self.command,
            "session_id": self.session_id,
            "started_at": self.started_at,
            "status": self.status,
            "exit_code": self.exit_code,
            "uptime_seconds": round(self.uptime_seconds, 2),
        }
        if self.error_category is not None:
            payload["error_category"] = self.error_category
        if self.last_progress is not None:
            payload["last_progress"] = self.last_progress
        return payload


FinishListener = Callable[[BackgroundProcessInfo], Awaitable[None]]
ProgressListener = Callable[[BackgroundProcessInfo, dict[str, object]], Awaitable[None]]


__all__ = [
    "BackgroundProcessInfo",
    "BackgroundQuotaError",
    "FinishListener",
    "ProgressListener",
]
