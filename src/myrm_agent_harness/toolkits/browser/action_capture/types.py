"""Structured types for browser action capture.


[INPUT]

[OUTPUT]
- ActionType: Enum of capturable browser action types
- ActionStep: Immutable captured browser action with metadata
- CaptureSession: Recording session state container

[POS]
Defines the data contracts for browser action capture. All types are immutable
(frozen dataclass) to ensure thread-safe read access from SSE consumers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class ActionType(str, Enum):
    """Capturable browser action types."""

    CLICK = "click"
    DBLCLICK = "dblclick"
    TYPE = "type"
    FILL = "fill"
    SELECT = "select"
    CHECK = "check"
    UNCHECK = "uncheck"
    NAVIGATE = "navigate"
    UPLOAD = "upload"
    PRESS = "press"
    SCROLL = "scroll"
    HOVER = "hover"
    DRAG = "drag"


@dataclass(frozen=True)
class ActionStep:
    """Single captured browser action (immutable).

    Attributes:
        seq: Monotonic sequence number within a capture session.
        action: The type of browser action performed.
        selector: CSS/ARIA selector identifying the target element.
        value: Action payload — typed text, selected option, pressed key, URL, etc.
        url: Page URL at the time of the action.
        title: Page title at the time of the action.
        timestamp: Unix timestamp (seconds) when the action was captured.
        screenshot_b64: Base64-encoded PNG screenshot taken after the action, or None.
        element_text: Visible text content of the interacted element, if available.
        element_role: ARIA role of the interacted element, if available.
        is_password: Whether the target field is a password/sensitive input.
    """

    seq: int
    action: ActionType
    selector: str
    value: str = ""
    url: str = ""
    title: str = ""
    timestamp: float = field(default_factory=time.time)
    screenshot_b64: str | None = None
    element_text: str = ""
    element_role: str = ""
    is_password: bool = False


@dataclass
class CaptureSession:
    """Mutable recording session state.

    Attributes:
        session_id: Unique identifier for this capture session.
        status: Current session lifecycle state.
        steps: Ordered list of captured action steps.
        start_url: URL when recording started.
        start_time: Unix timestamp when recording started.
    """

    session_id: str
    status: Literal["recording", "paused", "stopped"] = "recording"
    steps: list[ActionStep] = field(default_factory=list)
    start_url: str = ""
    start_time: float = field(default_factory=time.time)

    @property
    def next_seq(self) -> int:
        return len(self.steps) + 1

    def add_step(self, step: ActionStep) -> None:
        self.steps.append(step)
