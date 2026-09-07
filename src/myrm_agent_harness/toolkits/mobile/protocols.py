"""Mobile toolkit protocols defining modular contracts.

[INPUT]
- types::MobileDevice, ScreencapResult, MobileHierarchy, MobileActionResult, SensitiveActionVerdict, Point2D, KeyCode, TouchAction

[OUTPUT]
- MobileDeviceManagerProtocol
- MobileInspectorProtocol
- MobileInputControllerProtocol
- MobileAppManagerProtocol
- MobileSafetyBarrierProtocol
- MobileBridgeEngineProtocol

[POS]
Protocol contracts for platform-agnostic Android wireless debugging and automation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from myrm_agent_harness.toolkits.mobile.types import (
    KeyCode,
    MobileActionResult,
    MobileDevice,
    MobileHierarchy,
    Point2D,
    ScreencapResult,
    SensitiveActionVerdict,
    TouchAction,
)


@runtime_checkable
class MobileDeviceManagerProtocol(Protocol):
    """Manages ADB device discovery, pairing, and dynamic wireless connection."""

    async def list_devices(self) -> list[MobileDevice]:
        """List all connected or reachable ADB devices."""
        ...

    async def pair_device(self, host: str, port: int, pairing_code: str) -> MobileActionResult:
        """Perform Android 11+ one-time wireless pairing handshake."""
        ...

    async def connect_device(self, host: str, port: int = 5555) -> MobileActionResult:
        """Connect to device via TCP/IP."""
        ...

    async def disconnect_device(self, host_or_serial: str) -> MobileActionResult:
        """Disconnect wireless device."""
        ...

    async def ensure_active_device(self, preferred_serial: str | None = None) -> MobileDevice:
        """Resolve and verify online status of target device."""
        ...


@runtime_checkable
class MobileInspectorProtocol(Protocol):
    """Captures screen imagery and extracts structural UI hierarchy."""

    async def screencap(
        self,
        serial: str | None = None,
        max_dimension: int | None = 1920,
        quality: int = 80,
    ) -> ScreencapResult:
        """Capture screenshot as bytes/base64."""
        ...

    async def dump_hierarchy(
        self,
        serial: str | None = None,
        compressed: bool = True,
    ) -> MobileHierarchy:
        """Extract and parse UI Automator accessibility tree."""
        ...

    async def get_screen_resolution(self, serial: str | None = None) -> Point2D:
        """Get physical screen resolution (width, height)."""
        ...


@runtime_checkable
class MobileInputControllerProtocol(Protocol):
    """Executes normalized or pixel-level touch, gesture, and text inputs."""

    async def tap(
        self,
        x: int | float,
        y: int | float,
        normalized: bool = False,
        serial: str | None = None,
    ) -> MobileActionResult:
        """Perform tap at coordinate."""
        ...

    async def swipe(
        self,
        x1: int | float,
        y1: int | float,
        x2: int | float,
        y2: int | float,
        duration_ms: int = 300,
        normalized: bool = False,
        serial: str | None = None,
    ) -> MobileActionResult:
        """Perform swipe/drag gesture."""
        ...

    async def type_text(
        self,
        text: str,
        use_broadcast_ime: bool = True,
        serial: str | None = None,
    ) -> MobileActionResult:
        """Inject text, supporting Chinese and Unicode characters."""
        ...

    async def press_key(
        self,
        key_code: KeyCode | int,
        serial: str | None = None,
    ) -> MobileActionResult:
        """Simulate hardware key event."""
        ...


@runtime_checkable
class MobileAppManagerProtocol(Protocol):
    """Manages Android application lifecycles and intent dispatching."""

    async def launch_app(
        self,
        package_or_alias: str,
        activity: str | None = None,
        serial: str | None = None,
    ) -> MobileActionResult:
        """Launch app by package name or common alias."""
        ...

    async def terminate_app(
        self,
        package_name: str,
        serial: str | None = None,
    ) -> MobileActionResult:
        """Force stop package."""
        ...

    async def get_current_app(self, serial: str | None = None) -> tuple[str, str]:
        """Get current foreground (package, activity)."""
        ...


@runtime_checkable
class MobileSafetyBarrierProtocol(Protocol):
    """Evaluates screen hierarchy and action intent to intercept high-risk operations."""

    def evaluate_hierarchy(self, hierarchy: MobileHierarchy) -> SensitiveActionVerdict:
        """Check if current visible screen contains sensitive UI patterns."""
        ...

    def evaluate_action(
        self,
        action: TouchAction | str,
        target_text: str = "",
        target_package: str = "",
    ) -> SensitiveActionVerdict:
        """Evaluate if proposed mobile action should be gated or confirmed."""
        ...


@runtime_checkable
class MobileBridgeEngineProtocol(
    MobileDeviceManagerProtocol,
    MobileInspectorProtocol,
    MobileInputControllerProtocol,
    MobileAppManagerProtocol,
    Protocol,
):
    """Composite facade protocol for high-level mobile wireless bridge operations."""
    ...
