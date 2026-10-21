"""Events related to idle background tasks.

[INPUT]
- runtime.events.bus::BaseEvent (POS: base class of all runtime events)

[OUTPUT]
- IdleTaskProgressEvent: Structured progress/status of one idle background task (status Literal, task_name, progress_pct, data)

[POS]
Idle-task progress event published by the background worker and forwarded by the host (e.g. over SSE) to drive the idle status UI.
"""

from dataclasses import dataclass
from typing import Literal

from .bus import BaseEvent


@dataclass
class IdleTaskProgressEvent(BaseEvent):
    """Emitted when an idle background task updates its progress or status.

    This is meant to be intercepted by the Server layer and pushed to the
    frontend (e.g., via SSE) to drive the "breathing light" UI. The event carries
    structure only (``task_name``, ``status``, ``progress_pct``, ``data``); user-facing
    text is the UI layer's responsibility so it can be localized.
    """

    session_id: str
    status: Literal["working", "completed", "notification", "error", "idle"]
    user_id: str | None = None
    task_name: str | None = None
    progress_pct: int | None = None
    data: dict[str, object] | None = None
