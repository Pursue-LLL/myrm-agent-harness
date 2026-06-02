"""Events related to idle background tasks.

[INPUT]
- (none)

[OUTPUT]
- IdleTaskProgressEvent: Emitted when an idle background task updates its progress...

[POS]
Events related to idle background tasks.
"""

from dataclasses import dataclass
from typing import Any

from .bus import BaseEvent


@dataclass
class IdleTaskProgressEvent(BaseEvent):
    """Emitted when an idle background task updates its progress or status.

    This is meant to be intercepted by the Server layer and pushed to the
    frontend (e.g., via SSE) to drive the "breathing light" UI.
    """

    session_id: str
    status: str  # e.g., "started", "working", "completed", "error", "idle"
    user_id: str | None = None
    task_name: str | None = None
    progress_pct: int | None = None
    message: str | None = None
    data: dict[str, Any] | None = None
