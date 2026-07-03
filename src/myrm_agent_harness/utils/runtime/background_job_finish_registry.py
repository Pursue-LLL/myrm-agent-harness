"""Global registry for background bash job finish notifications.

Decouples harness finish listeners from the server layer so chat history
can record job completion without a headless LLM run.

[INPUT]
- agent.meta_tools.bash._background_types::BackgroundProcessInfo (POS: job snapshot)

[OUTPUT]
- BackgroundJobFinishResult: Immutable finish payload for server handlers
- BackgroundJobFinishHandler: Protocol for business-layer chat persistence
- set/get_global_background_job_finish_handler: Singleton registration

[POS]
Harness runtime bridge — mirrors ``wakeup_registry`` for bash background jobs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class BackgroundJobFinishResult:
    """Terminal state of a background bash job."""

    session_id: str
    pid: int
    command: str
    status: str
    exit_code: int | None
    error_category: str | None


class BackgroundJobFinishHandler(Protocol):
    """Business hook invoked when a tracked background bash job finishes."""

    async def on_background_job_finish(self, result: BackgroundJobFinishResult) -> None:
        """Persist or notify the user; must not block the registry thread."""
        ...


_global_finish_handler: BackgroundJobFinishHandler | None = None


def set_global_background_job_finish_handler(handler: BackgroundJobFinishHandler | None) -> None:
    """Register the server-side finish handler."""
    global _global_finish_handler
    _global_finish_handler = handler


def get_global_background_job_finish_handler() -> BackgroundJobFinishHandler | None:
    """Return the registered finish handler, if any."""
    return _global_finish_handler
