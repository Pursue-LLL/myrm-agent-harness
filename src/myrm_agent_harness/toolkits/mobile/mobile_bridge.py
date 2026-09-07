"""Mobile wireless bridge unified facade.

[INPUT]
- device_manager::MobileDeviceManager
- inspector::MobileInspector
- input_controller::MobileInputController
- app_manager::MobileAppManager
- safety::MobileSafetyBarrier

[OUTPUT]
- MobileBridge: Composite facade implementing MobileBridgeEngineProtocol

[POS]
Main entry point and orchestrator for mobile automation in toolkits/mobile.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.toolkits.mobile.app_manager import MobileAppManager
from myrm_agent_harness.toolkits.mobile.device_manager import MobileDeviceManager
from myrm_agent_harness.toolkits.mobile.inspector import MobileInspector
from myrm_agent_harness.toolkits.mobile.input_controller import MobileInputController
from myrm_agent_harness.toolkits.mobile.protocols import MobileBridgeEngineProtocol
from myrm_agent_harness.toolkits.mobile.safety import MobileSafetyBarrier
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

logger = logging.getLogger(__name__)


class MobileBridge(MobileBridgeEngineProtocol):
    """Unified Mobile Wireless Bridge orchestrating device, screen, input, app, and safety."""

    def __init__(
        self,
        adb_path: str | None = None,
        strict_safety: bool = True,
    ) -> None:
        self.device_manager = MobileDeviceManager(adb_path=adb_path)
        self.inspector = MobileInspector(device_manager=self.device_manager)
        self.input_controller = MobileInputController(
            device_manager=self.device_manager,
            inspector=self.inspector,
        )
        self.app_manager = MobileAppManager(device_manager=self.device_manager)
        self.safety_barrier = MobileSafetyBarrier(strict_mode=strict_safety)

    # ---------------- Device Manager Delegations ----------------

    async def list_devices(self) -> list[MobileDevice]:
        return await self.device_manager.list_devices()

    async def pair_device(self, host: str, port: int, pairing_code: str) -> MobileActionResult:
        return await self.device_manager.pair_device(host, port, pairing_code)

    async def connect_device(self, host: str, port: int = 5555) -> MobileActionResult:
        return await self.device_manager.connect_device(host, port)

    async def disconnect_device(self, host_or_serial: str) -> MobileActionResult:
        return await self.device_manager.disconnect_device(host_or_serial)

    async def ensure_active_device(self, preferred_serial: str | None = None) -> MobileDevice:
        return await self.device_manager.ensure_active_device(preferred_serial)

    # ---------------- Inspector Delegations ----------------

    async def screencap(
        self,
        serial: str | None = None,
        max_dimension: int | None = 1920,
        quality: int = 80,
    ) -> ScreencapResult:
        return await self.inspector.screencap(
            serial=serial,
            max_dimension=max_dimension,
            quality=quality,
        )

    async def dump_hierarchy(
        self,
        serial: str | None = None,
        compressed: bool = True,
    ) -> MobileHierarchy:
        return await self.inspector.dump_hierarchy(
            serial=serial,
            compressed=compressed,
        )

    async def get_screen_resolution(self, serial: str | None = None) -> Point2D:
        return await self.inspector.get_screen_resolution(serial)

    # ---------------- Input Controller Delegations (Gated by Safety) ----------------

    async def tap(
        self,
        x: int | float,
        y: int | float,
        normalized: bool = False,
        serial: str | None = None,
    ) -> MobileActionResult:
        return await self.input_controller.tap(
            x=x,
            y=y,
            normalized=normalized,
            serial=serial,
        )

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
        return await self.input_controller.swipe(
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            duration_ms=duration_ms,
            normalized=normalized,
            serial=serial,
        )

    async def type_text(
        self,
        text: str,
        use_broadcast_ime: bool = True,
        serial: str | None = None,
    ) -> MobileActionResult:
        # Safety gate for text
        verdict = self.safety_barrier.evaluate_action(
            action="type_text",
            target_text=text,
        )
        if verdict.is_sensitive and verdict.requires_confirmation:
            return MobileActionResult(
                success=False,
                action="type_text",
                message=f"Action blocked by MobileSafetyBarrier: {verdict.reason}",
                exit_code=-2,
                data={"risk_level": verdict.risk_level, "patterns": ",".join(verdict.matched_patterns)},
            )

        return await self.input_controller.type_text(
            text=text,
            use_broadcast_ime=use_broadcast_ime,
            serial=serial,
        )

    async def press_key(
        self,
        key_code: KeyCode | int,
        serial: str | None = None,
    ) -> MobileActionResult:
        return await self.input_controller.press_key(key_code=key_code, serial=serial)

    # ---------------- App Manager Delegations ----------------

    async def launch_app(
        self,
        package_or_alias: str,
        activity: str | None = None,
        serial: str | None = None,
    ) -> MobileActionResult:
        verdict = self.safety_barrier.evaluate_action(
            action="launch_app",
            target_package=package_or_alias,
        )
        if verdict.is_sensitive and verdict.requires_confirmation:
            return MobileActionResult(
                success=False,
                action="launch_app",
                message=f"Action blocked by MobileSafetyBarrier: {verdict.reason}",
                exit_code=-2,
                data={"risk_level": verdict.risk_level},
            )

        return await self.app_manager.launch_app(
            package_or_alias=package_or_alias,
            activity=activity,
            serial=serial,
        )

    async def terminate_app(
        self,
        package_name: str,
        serial: str | None = None,
    ) -> MobileActionResult:
        return await self.app_manager.terminate_app(
            package_name=package_name,
            serial=serial,
        )

    async def get_current_app(self, serial: str | None = None) -> tuple[str, str]:
        return await self.app_manager.get_current_app(serial=serial)

    def evaluate_hierarchy(self, hierarchy: MobileHierarchy) -> SensitiveActionVerdict:
        return self.safety_barrier.evaluate_hierarchy(hierarchy)

    def evaluate_action(
        self,
        action: TouchAction | str,
        target_text: str = "",
        target_package: str = "",
    ) -> SensitiveActionVerdict:
        return self.safety_barrier.evaluate_action(
            action=action,
            target_text=target_text,
            target_package=target_package,
        )
