"""Type definitions and data models for Mobile ADB Toolkit.

[INPUT]
- (none)

[OUTPUT]
- MobileActionType, MobileUIElement, MobileDeviceState, MobileActionResult, MobileSessionConfig

[POS]
Type definitions and data structures for Android Wireless ADB control and semantic UI inspection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

MobileActionType = Literal[
    "click",
    "long_press",
    "input_text",
    "clear_text",
    "key_event",
    "scroll",
    "swipe",
    "launch_app",
    "stop_app",
    "back",
    "home",
]

MobileVisionActionType = Literal[
    "tap_coordinate",
    "swipe_coordinate",
    "screencap",
    "press_key",
    "wait",
]


class MobileDeviceConnectionStatus(str, Enum):
    """Device wireless connection status."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    UNAUTHORIZED = "unauthorized"
    PAIRING_REQUIRED = "pairing_required"


@dataclass(slots=True)
class MobileUIElement:
    """Parsed accessibility UI element node from Android uiautomator dump."""

    ref_id: str  # e.g., "@mref_1"
    class_name: str
    resource_id: str
    text: str
    content_desc: str
    bounds: tuple[int, int, int, int]  # (left, top, right, bottom)
    clickable: bool
    scrollable: bool
    editable: bool
    enabled: bool
    focused: bool
    package_name: str = ""

    @property
    def center(self) -> tuple[int, int]:
        """Calculate the center coordinate (X, Y) of the element."""
        left, top, right, bottom = self.bounds
        return (left + right) // 2, (top + bottom) // 2

    def to_summary(self) -> str:
        """Render concise summary for LLM prompt context."""
        parts = [f"[{self.ref_id}]"]
        if self.text:
            parts.append(f'text="{self.text}"')
        if self.content_desc:
            parts.append(f'desc="{self.content_desc}"')
        if self.resource_id:
            short_id = self.resource_id.split("/")[-1]
            parts.append(f"id={short_id}")
        parts.append(f"role={self.class_name.split('.')[-1]}")
        center_x, center_y = self.center
        parts.append(f"pos=({center_x},{center_y})")
        return " ".join(parts)


@dataclass(slots=True)
class MobileDeviceState:
    """Snapshot state of a target Android mobile device."""

    device_id: str
    ip_address: str
    port: int
    connection_status: MobileDeviceConnectionStatus
    current_package: str = ""
    current_activity: str = ""
    screen_width: int = 1080
    screen_height: int = 2400
    elements: list[MobileUIElement] = field(default_factory=list)
    xml_tree: str = ""


@dataclass(slots=True)
class MobileActionResult:
    """Result of an executed mobile action."""

    success: bool
    action: str
    message: str
    error: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
