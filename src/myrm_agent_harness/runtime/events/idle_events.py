"""Events related to idle background tasks.

[INPUT]
- (none)

[OUTPUT]
- IdleTaskProgressEvent: Emitted when an idle background task updates its progress...

[POS]
Events related to idle background tasks.
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
