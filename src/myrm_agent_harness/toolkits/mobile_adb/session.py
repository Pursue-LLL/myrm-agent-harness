"""Mobile Session Orchestrator for Android Wireless ADB.

[INPUT]
- driver::AdbDeviceDriver (POS: low-level adb execution driver)
- types::MobileDeviceState, MobileActionResult (POS: data models)

[OUTPUT]
- MobileSession: High-level orchestrator managing connected devices and safe interactions.

[POS]
Device state and multi-device connection manager for Agent mobile tools.
"""

from __future__ import annotations

import logging
from typing import Any

from myrm_agent_harness.toolkits.mobile_adb.driver import AdbDeviceDriver
from myrm_agent_harness.toolkits.mobile_adb.types import (
    MobileActionResult,
    MobileDeviceState,
)

logger = logging.getLogger(__name__)


class MobileSession:
    """Manages active wireless ADB sessions, device tracking, and security checks."""

    def __init__(self, default_device: str = "", adb_path: str = "adb") -> None:
        self.default_device = default_device
        self.driver = AdbDeviceDriver(adb_path=adb_path)
        self._connected_devices: set[str] = set()

    def set_default_device(self, target: str) -> None:
        """Set the active default target device (e.g. '192.168.1.100:5555')."""
        self.default_device = target.strip()

    def get_target(self, explicit_target: str = "") -> str:
        """Resolve effective target device."""
        target = explicit_target.strip() or self.default_device
        if not target:
            raise ValueError(
                "No target device specified and no default device set. Please connect to a device first."
            )
        return target

    async def pair_device(self, host: str, port: int, pairing_code: str) -> MobileActionResult:
        """Pair with an Android 11+ device."""
        return await self.driver.pair(host, port, pairing_code)

    async def connect_device(self, host: str, port: int = 5555) -> MobileActionResult:
        """Connect to device and register in active session."""
        res = await self.driver.connect(host, port)
        if res.success:
            target = f"{host}:{port}"
            self._connected_devices.add(target)
            if not self.default_device:
                self.default_device = target
        return res

    async def disconnect_device(self, host: str, port: int = 5555) -> MobileActionResult:
        """Disconnect device."""
        target = f"{host}:{port}"
        res = await self.driver.disconnect(host, port)
        self._connected_devices.discard(target)
        if self.default_device == target:
            self.default_device = next(iter(self._connected_devices), "")
        return res

    async def snapshot(
        self, target: str = "", include_screenshot: bool = False
    ) -> tuple[MobileDeviceState, bytes | None]:
        """Capture current UI tree snapshot and optional screenshot binary."""
        device_target = self.get_target(target)
        state = await self.driver.get_device_state(device_target)
        screenshot_bytes: bytes | None = None
        if include_screenshot:
            screenshot_bytes = await self.driver.capture_screenshot_bytes(device_target)
        return state, screenshot_bytes

    async def interact(
        self,
        ref: str,
        action: str,
        text: str = "",
        target: str = "",
    ) -> MobileActionResult:
        """Execute semantic action against element ref (e.g. @mref_1)."""
        device_target = self.get_target(target)
        return await self.driver.execute_semantic_action(
            target=device_target,
            ref_id=ref,
            action=action,
            text_value=text,
        )

    async def global_action(
        self,
        action: str,
        param: str = "",
        target: str = "",
    ) -> MobileActionResult:
        """Execute device-level global action (back, home, launch_app, stop_app)."""
        device_target = self.get_target(target)
        return await self.driver.execute_global_action(
            target=device_target,
            action=action,
            param=param,
        )
