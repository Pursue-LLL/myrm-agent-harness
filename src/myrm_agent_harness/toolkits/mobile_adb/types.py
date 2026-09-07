"""Type definitions for Mobile ADB toolkit.

[INPUT]
- (none)

[OUTPUT]
- MobileAction, MobileDeviceState, MobileDeviceInfo, MobileScreenInfo, MobileUIElement, MobileElementRef, MobileActionResult, MobileBridgeConfig

[POS]
Shared type definitions consumed by all mobile_adb submodules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

MobileAction = Literal[
    "tap",
    "double_tap",
    "long_press",
    "swipe",
    "drag",
    "type_text",
    "key_event",
    "launch_app",
    "stop_app",
    "press_back",
    "press_home",
    "press_recents",
    "wait",
]

MobileDeviceState = Literal[
    "disconnected",
    "unauthorized",
    "connecting",
    "connected",
    "pairing",
]


@dataclass(frozen=True)
class MobileScreenInfo:
    """Screen resolution and density info for a mobile device."""

    width: int
    height: int
    density_dpi: int = 420


@dataclass(frozen=True)
class MobileDeviceInfo:
    """Metadata describing a connected or paired mobile device."""

    device_id: str
    host: str
    port: int
    model: str = "Unknown Android Device"
    state: MobileDeviceState = "disconnected"
    screen_info: MobileScreenInfo | None = None
    pairing_port: int | None = None
    is_wireless: bool = True


@dataclass(frozen=True)
class MobileUIElement:
    """Semantic UI element extracted from Android Accessibility / UIAutomator dump."""

    ref_id: str
    resource_id: str
    class_name: str
    package_name: str
    text: str
    content_desc: str
    bounds: tuple[int, int, int, int]  # (left, top, right, bottom)
    center_x: int
    center_y: int
    is_clickable: bool
    is_editable: bool
    is_scrollable: bool
    is_focused: bool


@dataclass
class MobileActionResult:
    """Result of an action performed on a mobile device."""

    success: bool
    message: str
    error: str | None = None
    elapsed_ms: float = 0.0
    screenshot_base64: str | None = None
    ui_elements: list[MobileUIElement] = field(default_factory=list)


@dataclass
class MobileBridgeConfig:
    """Configuration options for ADB Wireless Bridge."""

    adb_path: str = "adb"
    connect_timeout_seconds: float = 10.0
    command_timeout_seconds: float = 15.0
    default_host: str = "127.0.0.1"
    default_port: int = 5555
    auto_reconnect: bool = True
