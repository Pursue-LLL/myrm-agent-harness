"""Type definitions and data models for Mobile ADB Bridge Toolkit.

[INPUT]
- (none)

[OUTPUT]
- MobileDevice, DeviceConnectionState, MobileOrientation, MobileUIElement, MobileActionResult, MobileActionType, MobileConfig

[POS]
Shared type definitions consumed by all mobile toolkit submodules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

MobileActionType = Literal[
    "screencap",
    "ui_dump",
    "tap",
    "swipe",
    "input_text",
    "key_event",
    "launch_app",
    "press_home",
    "press_back",
    "wake_unlock",
]


class DeviceConnectionState(str, Enum):
    """Connection state of the mobile device."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    UNAUTHORIZED = "unauthorized"
    OFFLINE = "offline"


class MobileOrientation(int, Enum):
    """Device screen orientation in degrees."""

    PORTRAIT = 0
    LANDSCAPE_90 = 90
    REVERSE_PORTRAIT = 180
    LANDSCAPE_270 = 270


@dataclass(frozen=True)
class MobileDevice:
    """Represents an Android device connected via ADB / Wireless Debugging."""

    serial: str
    model: str = "Android Device"
    connection_state: DeviceConnectionState = DeviceConnectionState.CONNECTED
    host: str = "127.0.0.1"
    port: int = 5555
    is_wireless: bool = True
    screen_width: int = 1080
    screen_height: int = 2400
    density_dpi: int = 420


@dataclass(frozen=True)
class MobileUIElement:
    """Represents a UI node parsed from UIAutomator hierarchy."""

    node_id: str
    class_name: str
    text: str = ""
    resource_id: str = ""
    content_desc: str = ""
    package_name: str = ""
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)  # left, top, right, bottom
    normalized_center: tuple[float, float] = (0.0, 0.0)  # (x_rel, y_rel) in [0.0, 1.0]
    is_clickable: bool = False
    is_editable: bool = False
    is_sensitive: bool = False  # Matches password / payment keywords


@dataclass(frozen=True)
class MobileActionResult:
    """Result of a mobile action execution."""

    success: bool
    action: str
    output: str = ""
    error: str = ""
    screenshot_base64: str = ""
    elements: list[MobileUIElement] = field(default_factory=list)
    hitl_barrier_triggered: bool = False
    barrier_reason: str = ""


@dataclass
class MobileConfig:
    """Configuration for Mobile ADB Bridge Toolkit."""

    adb_path: str = "adb"
    auto_reconnect: bool = True
    connection_timeout_seconds: float = 10.0
    action_timeout_seconds: float = 30.0
    screenshot_format: Literal["png", "webp", "jpeg"] = "webp"
    webp_quality: int = 80
    enable_sensitive_barrier: bool = True
