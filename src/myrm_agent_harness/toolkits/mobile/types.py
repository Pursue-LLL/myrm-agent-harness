"""Type definitions for mobile Android ADB toolkit.

[INPUT]
- (none)

[OUTPUT]
- MobileActionType, MobileKey, DeviceInfo, DeviceConnectionStatus, TouchGesture, UIElementNode, MobileActionResult, MobileScreenshotResult, MobileUIDumpResult

[POS]
Shared type definitions consumed by all mobile toolkit submodules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class DeviceConnectionStatus(str, Enum):
    """Device wireless ADB connection state."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    UNAUTHORIZED = "unauthorized"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


MobileKey = Literal[
    "HOME",
    "BACK",
    "APP_SWITCH",
    "POWER",
    "VOLUME_UP",
    "VOLUME_DOWN",
    "ENTER",
    "TAB",
    "DELETE",
    "ESCAPE",
]

MobileActionType = Literal[
    "tap",
    "double_tap",
    "long_press",
    "swipe",
    "drag",
    "type_text",
    "key_event",
    "launch_app",
    "stop_app",
]


@dataclass(slots=True)
class DeviceInfo:
    """Android device metadata representation."""

    serial: str
    model: str = "Unknown"
    manufacturer: str = "Unknown"
    android_version: str = "Unknown"
    sdk_level: int = 0
    screen_width: int = 1080
    screen_height: int = 2400
    density_dpi: int = 440
    status: DeviceConnectionStatus = DeviceConnectionStatus.CONNECTED
    is_wireless: bool = False
    ip_address: str = ""
    port: int = 5555


@dataclass(slots=True)
class TouchGesture:
    """Touch/drag gesture definition."""

    x: int
    y: int
    end_x: int | None = None
    end_y: int | None = None
    duration_ms: int = 300


@dataclass(slots=True)
class UIElementNode:
    """Parsed Android Accessibility / UIAutomator View Node."""

    index: int
    text: str
    resource_id: str
    class_name: str
    package: str
    content_desc: str
    checkable: bool
    checked: bool
    clickable: bool
    enabled: bool
    focusable: bool
    focused: bool
    scrollable: bool
    long_clickable: bool
    password: bool
    selected: bool
    bounds: tuple[int, int, int, int]  # (left, top, right, bottom)
    center_x: int
    center_y: int
    norm_x: float  # Normalized 0.0 ~ 1.0
    norm_y: float  # Normalized 0.0 ~ 1.0
    children: list[UIElementNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert node to compact dictionary for inspection."""
        res: dict[str, Any] = {
            "text": self.text,
            "resource_id": self.resource_id,
            "class_name": self.class_name,
            "clickable": self.clickable,
            "bounds": list(self.bounds),
            "center": [self.center_x, self.center_y],
            "norm_center": [round(self.norm_x, 4), round(self.norm_y, 4)],
        }
        if self.content_desc:
            res["content_desc"] = self.content_desc
        if self.scrollable:
            res["scrollable"] = True
        if self.password:
            res["password"] = True
        if self.children:
            res["children"] = [child.to_dict() for child in self.children]
        return res


@dataclass(slots=True)
class MobileActionResult:
    """Result of an executed mobile action."""

    success: bool
    action: str
    output: str = ""
    error: str | None = None
    duration_ms: int = 0
    interrupted_by_safety: bool = False
    safety_reason: str | None = None


@dataclass(slots=True)
class MobileScreenshotResult:
    """Mobile screen capture payload."""

    image_bytes: bytes
    format: str = "png"
    width: int = 1080
    height: int = 2400
    base64_data: str = ""


@dataclass(slots=True)
class MobileUIDumpResult:
    """Mobile Accessibility hierarchy inspection dump."""

    root: UIElementNode | None
    clickable_elements: list[UIElementNode] = field(default_factory=list)
    raw_xml: str = ""
    top_activity: str = ""
    top_package: str = ""
