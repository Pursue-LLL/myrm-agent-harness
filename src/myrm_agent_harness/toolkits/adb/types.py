"""ADB toolkit domain types and models.

[INPUT]
- None (pure domain models)

[OUTPUT]
- DeviceConnectionState: enum for device lifecycle (DISCONNECTED, PAIRING, CONNECTED, UNAUTHORIZED, ERROR)
- AdbTouchAction: enum for touch interaction (TAP, SWIPE, PRESS_KEY, TEXT_INPUT)
- AdbElementNode: Accessibility hierarchy node with semantic bounds and text/desc
- AdbDeviceSnapshot: Full device visual & semantic snapshot
- AdbCommandResult: Execution output with status and timing

[POS]
Data structures for Android Wireless ADB toolkit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DeviceConnectionState(str, Enum):
    """Lifecycle states of wireless ADB device connection."""

    DISCONNECTED = "disconnected"
    PAIRING = "pairing"
    CONNECTED = "connected"
    UNAUTHORIZED = "unauthorized"
    ERROR = "error"


class AdbTouchAction(str, Enum):
    """Primitive mobile touch & input actions."""

    TAP = "tap"
    SWIPE = "swipe"
    PRESS_KEY = "press_key"
    TEXT_INPUT = "text_input"


@dataclass(slots=True)
class AdbElementNode:
    """Parsed semantic accessibility UI element."""

    ref_id: str
    resource_id: str = ""
    class_name: str = ""
    text: str = ""
    content_desc: str = ""
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)  # (left, top, right, bottom)
    clickable: bool = False
    editable: bool = False
    scrollable: bool = False

    @property
    def center(self) -> tuple[int, int]:
        """Compute center (x, y) coordinates of the element."""
        left, top, right, bottom = self.bounds
        return ((left + right) // 2, (top + bottom) // 2)


@dataclass(slots=True)
class AdbDeviceSnapshot:
    """Snapshot containing UI hierarchy, focused package, and optional screenshot."""

    package_name: str
    activity_name: str
    elements: list[AdbElementNode] = field(default_factory=list)
    screenshot_base64: str = ""
    screenshot_bytes: bytes = b""
    screen_width: int = 1080
    screen_height: int = 2400


@dataclass(slots=True)
class AdbCommandResult:
    """Result of an executed ADB command."""

    success: bool
    output: str = ""
    error: str = ""
    elapsed_ms: int = 0
