"""Protocols and interfaces for Mobile ADB Bridge Toolkit.

[INPUT]
- types.py: MobileDevice, MobileUIElement, MobileActionResult, MobileOrientation

[OUTPUT]
- DeviceManagerProtocol, UIInspectorProtocol, InputControllerProtocol, SafetyBarrierProtocol

[POS]
Abstract protocol definitions decoupling mobile implementation modules.
"""

from __future__ import annotations

from typing import Protocol

from myrm_agent_harness.toolkits.mobile.types import (
    MobileActionResult,
    MobileDevice,
    MobileOrientation,
    MobileUIElement,
)


class DeviceManagerProtocol(Protocol):
    """Protocol for discovering, connecting and managing Android devices."""

    async def list_devices(self) -> list[MobileDevice]:
        """List all attached/wireless Android devices."""
        ...

    async def connect_wireless(self, host: str, port: int, pair_code: str = "") -> MobileDevice:
        """Connect to a wireless debugging device with optional pairing."""
        ...

    async def get_device_info(self, serial: str) -> MobileDevice:
        """Fetch screen dimensions, model name and density."""
        ...

    async def get_orientation(self, serial: str) -> MobileOrientation:
        """Get current screen orientation."""
        ...

    async def wake_and_unlock(self, serial: str) -> bool:
        """Ensure device screen is awake and unlocked."""
        ...


class UIInspectorProtocol(Protocol):
    """Protocol for capturing screenshots and dumping UI hierarchies."""

    async def capture_screenshot(self, serial: str) -> bytes:
        """Capture raw screenshot bytes from device."""
        ...

    async def dump_ui_hierarchy(
        self, serial: str, screen_size: tuple[int, int]
    ) -> list[MobileUIElement]:
        """Dump UIAutomator XML and parse into normalized UI elements."""
        ...


class InputControllerProtocol(Protocol):
    """Protocol for sending touch, gesture, text and key events."""

    async def tap(self, serial: str, x: int, y: int) -> bool:
        """Tap at physical coordinates."""
        ...

    async def swipe(
        self,
        serial: str,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int = 300,
    ) -> bool:
        """Perform swipe gesture."""
        ...

    async def input_text(self, serial: str, text: str) -> bool:
        """Input Unicode / Chinese text safely."""
        ...

    async def send_key(self, serial: str, key_code: int) -> bool:
        """Send Android KeyEvent (e.g. 3=Home, 4=Back)."""
        ...

    async def launch_app(self, serial: str, package_or_intent: str) -> bool:
        """Launch app by package name or deep intent."""
        ...


class SafetyBarrierProtocol(Protocol):
    """Protocol for inspecting sensitive interfaces and triggering HITL barriers."""

    def check_sensitive_elements(self, elements: list[MobileUIElement]) -> tuple[bool, str]:
        """Check if current UI contains sensitive password/payment triggers."""
        ...
