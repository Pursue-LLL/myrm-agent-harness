"""Mobile Action and Native Input Execution Engine.

[INPUT]
- myrm_agent_harness.toolkits.mobile_adb.executor::ADBExecutor
- myrm_agent_harness.toolkits.mobile_adb.types::MobileActionResult, MobileAction

[OUTPUT]
- MobileExecutionEngine: Executes tap, swipe, type, back, home, app launch actions on mobile device.

[POS]
Input and action execution adapter for Android devices.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.mobile_adb.executor import ADBExecutor
    from myrm_agent_harness.toolkits.mobile_adb.types import MobileActionResult

logger = logging.getLogger(__name__)


class MobileExecutionEngine:
    """Dispatches touch, keyboard, and system control actions to Android devices."""

    def __init__(self, executor: ADBExecutor) -> None:
        self.executor = executor

    async def tap(self, device_id: str, x: int, y: int) -> MobileActionResult:
        """Tap at coordinate (x, y)."""
        from myrm_agent_harness.toolkits.mobile_adb.types import MobileActionResult

        start = time.perf_counter()
        rc, out, err = await self.executor.run_adb(
            ["shell", "input", "tap", str(x), str(y)],
            target_device=device_id,
        )
        elapsed = (time.perf_counter() - start) * 1000
        return MobileActionResult(
            success=(rc == 0),
            message=f"Tapped at ({x}, {y})",
            error=err if rc != 0 else None,
            elapsed_ms=elapsed,
        )

    async def swipe(
        self,
        device_id: str,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: int = 300,
    ) -> MobileActionResult:
        """Swipe from (start_x, start_y) to (end_x, end_y)."""
        from myrm_agent_harness.toolkits.mobile_adb.types import MobileActionResult

        start = time.perf_counter()
        rc, out, err = await self.executor.run_adb(
            [
                "shell",
                "input",
                "swipe",
                str(start_x),
                str(start_y),
                str(end_x),
                str(end_y),
                str(duration_ms),
            ],
            target_device=device_id,
        )
        elapsed = (time.perf_counter() - start) * 1000
        return MobileActionResult(
            success=(rc == 0),
            message=f"Swiped from ({start_x}, {start_y}) to ({end_x}, {end_y}) in {duration_ms}ms",
            error=err if rc != 0 else None,
            elapsed_ms=elapsed,
        )

    async def type_text(self, device_id: str, text: str) -> MobileActionResult:
        """Type text into active input field (auto-escapes whitespace)."""
        from myrm_agent_harness.toolkits.mobile_adb.types import MobileActionResult

        start = time.perf_counter()
        # ADB input text replaces spaces with %s
        escaped_text = text.replace(" ", "%s")
        rc, out, err = await self.executor.run_adb(
            ["shell", "input", "text", escaped_text],
            target_device=device_id,
        )
        elapsed = (time.perf_counter() - start) * 1000
        return MobileActionResult(
            success=(rc == 0),
            message=f"Typed text into active element",
            error=err if rc != 0 else None,
            elapsed_ms=elapsed,
        )

    async def press_key(self, device_id: str, key_code: int | str) -> MobileActionResult:
        """Send physical/virtual key event (e.g. 3 for HOME, 4 for BACK)."""
        from myrm_agent_harness.toolkits.mobile_adb.types import MobileActionResult

        start = time.perf_counter()
        rc, out, err = await self.executor.run_adb(
            ["shell", "input", "keyevent", str(key_code)],
            target_device=device_id,
        )
        elapsed = (time.perf_counter() - start) * 1000
        return MobileActionResult(
            success=(rc == 0),
            message=f"Pressed key {key_code}",
            error=err if rc != 0 else None,
            elapsed_ms=elapsed,
        )

    async def launch_app(
        self,
        device_id: str,
        package_name: str,
        activity_name: str | None = None,
    ) -> MobileActionResult:
        """Launch app by package name or monkey launcher."""
        from myrm_agent_harness.toolkits.mobile_adb.types import MobileActionResult

        start = time.perf_counter()
        if activity_name:
            target = f"{package_name}/{activity_name}"
            cmd = ["shell", "am", "start", "-n", target]
        else:
            # Launch default activity via monkey launcher
            cmd = [
                "shell",
                "monkey",
                "-p",
                package_name,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ]

        rc, out, err = await self.executor.run_adb(cmd, target_device=device_id)
        elapsed = (time.perf_counter() - start) * 1000
        return MobileActionResult(
            success=(rc == 0),
            message=f"Launched app {package_name}",
            error=err if rc != 0 else None,
            elapsed_ms=elapsed,
        )

    async def stop_app(self, device_id: str, package_name: str) -> MobileActionResult:
        """Force stop package."""
        from myrm_agent_harness.toolkits.mobile_adb.types import MobileActionResult

        start = time.perf_counter()
        rc, out, err = await self.executor.run_adb(
            ["shell", "am", "force-stop", package_name],
            target_device=device_id,
        )
        elapsed = (time.perf_counter() - start) * 1000
        return MobileActionResult(
            success=(rc == 0),
            message=f"Force stopped app {package_name}",
            error=err if rc != 0 else None,
            elapsed_ms=elapsed,
        )
