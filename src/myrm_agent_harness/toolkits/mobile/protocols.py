"""Mobile device protocols and abstraction interfaces.

[INPUT]
- types::DeviceInfo, MobileActionResult, MobileScreenshotResult, MobileUIDumpResult, TouchGesture, MobileKey

[OUTPUT]
- MobileDeviceManagerProtocol, MobileInspectorProtocol, MobileInputControllerProtocol, MobileAppManagerProtocol, MobileBridgeProtocol

[POS]
Dependency-inversion boundaries for Android ADB abstraction layers.
"""

from __future__ import annotations

from typing import Protocol

from myrm_agent_harness.toolkits.mobile.types import (
    DeviceInfo,
    MobileActionResult,
    MobileKey,
    MobileScreenshotResult,
    MobileUIDumpResult,
    TouchGesture,
)


class MobileDeviceManagerProtocol(Protocol):
    """Protocol for discovering, pairing and connecting to Android devices."""

    async def list_devices(self) -> list[DeviceInfo]:
        """List all attached or discovered wireless devices."""
        ...

    async def pair_wireless(self, host: str, port: int, pairing_code: str) -> bool:
        """Pair with an Android 11+ device via pairing code."""
        ...

    async def connect_wireless(self, host: str, port: int) -> bool:
        """Connect to an Android device via Wi-Fi."""
        ...

    async def disconnect(self, serial: str) -> bool:
        """Disconnect wireless device."""
        ...

    async def get_device_info(self, serial: str | None = None) -> DeviceInfo | None:
        """Get properties and screen resolution of the active device."""
        ...


class MobileInspectorProtocol(Protocol):
    """Protocol for screen capture and accessibility hierarchy inspection."""

    async def screencap(
        self, serial: str | None = None, quality: int = 80
    ) -> MobileScreenshotResult:
        """Capture the screen as bytes."""
        ...

    async def dump_ui_hierarchy(
        self, serial: str | None = None, timeout_s: float = 5.0
    ) -> MobileUIDumpResult:
        """Extract current Accessibility XML tree and compute clickable element coordinates."""
        ...

    async def get_top_activity(self, serial: str | None = None) -> tuple[str, str]:
        """Return (package, activity) of current foreground app."""
        ...


class MobileInputControllerProtocol(Protocol):
    """Protocol for sending touch gestures, keystrokes, and text to device."""

    async def tap(
        self, x: int | float, y: int | float, normalized: bool = False, serial: str | None = None
    ) -> MobileActionResult:
        """Tap at (x, y) coordinates."""
        ...

    async def swipe(
        self,
        start_x: int | float,
        start_y: int | float,
        end_x: int | float,
        end_y: int | float,
        duration_ms: int = 300,
        normalized: bool = False,
        serial: str | None = None,
    ) -> MobileActionResult:
        """Perform a swipe gesture from start to end."""
        ...

    async def type_text(self, text: str, serial: str | None = None) -> MobileActionResult:
        """Input text (supports Chinese and Unicode via Broadcast IME or base64 fallback)."""
        ...

    async def press_key(self, key: MobileKey, serial: str | None = None) -> MobileActionResult:
        """Simulate hardware or navigation key press."""
        ...


class MobileAppManagerProtocol(Protocol):
    """Protocol for launching, stopping, and monitoring apps."""

    async def launch_app(
        self, package_or_alias: str, activity: str | None = None, serial: str | None = None
    ) -> MobileActionResult:
        """Launch an application by package name or common alias (e.g. 'wechat', 'settings')."""
        ...

    async def stop_app(self, package_name: str, serial: str | None = None) -> MobileActionResult:
        """Force stop a background or foreground app."""
        ...

    async def list_installed_packages(
        self, third_party_only: bool = True, serial: str | None = None
    ) -> list[str]:
        """List installed package names on device."""
        ...


class MobileBridgeProtocol(Protocol):
    """Unified facade protocol for complete mobile automation."""

    device_manager: MobileDeviceManagerProtocol
    inspector: MobileInspectorProtocol
    input_controller: MobileInputControllerProtocol
    app_manager: MobileAppManagerProtocol
