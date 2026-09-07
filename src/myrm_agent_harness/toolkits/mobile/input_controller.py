"""Mobile Touch, Gesture and Text Input Controller.

[INPUT]
- types::MobileActionResult, MobileKey, DeviceInfo (POS: shared mobile types)
- protocols::MobileInputControllerProtocol (POS: input control contract)
- safety::MobileSafetyGuard (POS: safety filter)

[OUTPUT]
- MobileInputController: Implementation of tap, swipe, long press, Chinese/Unicode text input, and hardware keypresses

[POS]
Input synthesis and device gesture driver for Android devices.
"""

from __future__ import annotations

import base64
import logging
import shlex
import time
from typing import Any

from myrm_agent_harness.toolkits.mobile.device_manager import MobileDeviceManager
from myrm_agent_harness.toolkits.mobile.safety import MobileSafetyGuard
from myrm_agent_harness.toolkits.mobile.types import (
    MobileActionResult,
    MobileKey,
)

logger = logging.getLogger(__name__)

_KEY_CODES: dict[MobileKey, int] = {
    "HOME": 3,
    "BACK": 4,
    "APP_SWITCH": 187,
    "POWER": 26,
    "VOLUME_UP": 24,
    "VOLUME_DOWN": 25,
    "ENTER": 66,
    "TAB": 61,
    "DELETE": 67,
    "ESCAPE": 111,
}


class MobileInputController:
    """Sends touch events, gestures, text input and hardware keys to Android device."""

    def __init__(
        self,
        device_manager: MobileDeviceManager,
        safety_guard: MobileSafetyGuard | None = None,
    ) -> None:
        self._device_manager = device_manager
        self._safety_guard = safety_guard or MobileSafetyGuard()

    async def tap(
        self,
        x: int | float,
        y: int | float,
        normalized: bool = False,
        serial: str | None = None,
    ) -> MobileActionResult:
        """Tap at (x, y) coordinates."""
        t0 = time.monotonic()
        px_x, px_y = await self._resolve_coords(x, y, normalized, serial)

        code, stdout, stderr = await self._device_manager.execute_adb_command(
            ["shell", "input", "tap", str(px_x), str(px_y)], serial=serial
        )
        dur = int((time.monotonic() - t0) * 1000)

        if code == 0:
            return MobileActionResult(
                success=True,
                action=f"tap({px_x}, {px_y})",
                output=f"Tapped at ({px_x}, {px_y})",
                duration_ms=dur,
            )
        err = stderr.decode("utf-8", errors="ignore")
        return MobileActionResult(
            success=False,
            action=f"tap({px_x}, {px_y})",
            error=err or "Tap failed",
            duration_ms=dur,
        )

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
        """Perform a smooth drag/swipe gesture."""
        t0 = time.monotonic()
        sx, sy = await self._resolve_coords(start_x, start_y, normalized, serial)
        ex, ey = await self._resolve_coords(end_x, end_y, normalized, serial)

        code, stdout, stderr = await self._device_manager.execute_adb_command(
            ["shell", "input", "swipe", str(sx), str(sy), str(ex), str(ey), str(duration_ms)],
            serial=serial,
        )
        dur = int((time.monotonic() - t0) * 1000)

        if code == 0:
            return MobileActionResult(
                success=True,
                action=f"swipe(({sx}, {sy}) -> ({ex}, {ey}), {duration_ms}ms)",
                output=f"Swiped from ({sx}, {sy}) to ({ex}, {ey})",
                duration_ms=dur,
            )
        return MobileActionResult(
            success=False,
            action=f"swipe(({sx}, {sy}) -> ({ex}, {ey}))",
            error=stderr.decode("utf-8", errors="ignore") or "Swipe failed",
            duration_ms=dur,
        )

    async def type_text(self, text: str, serial: str | None = None) -> MobileActionResult:
        """Type text supporting ASCII, Chinese and Unicode characters."""
        t0 = time.monotonic()
        # 1. Try ADB Broadcast IME (if installed) or fallback to base64 intent
        # If standard ASCII without special whitespace
        if text.isascii() and not any(c in text for c in (" ", "\n", "'", '"', "&", "|", ";")):
            code, stdout, stderr = await self._device_manager.execute_adb_command(
                ["shell", "input", "text", text], serial=serial
            )
            dur = int((time.monotonic() - t0) * 1000)
            return MobileActionResult(
                success=code == 0,
                action=f"type_text({text[:10]}...)",
                output=f"Typed {len(text)} chars",
                duration_ms=dur,
            )

        # 2. Universal Unicode / Chinese broadcast injection
        b64_str = base64.b64encode(text.encode("utf-8")).decode("ascii")
        code, stdout, stderr = await self._device_manager.execute_adb_command(
            [
                "shell",
                "am",
                "broadcast",
                "-a",
                "ADB_INPUT_B64",
                "--es",
                "msg",
                b64_str,
            ],
            serial=serial,
        )

        # Fallback to escaped input text if broadcast was not handled
        if code != 0 or b"Broadcast completed" not in stdout:
            # Escaped whitespace ASCII typing
            safe_text = shlex.quote(text).replace(" ", "%s")
            code, stdout, stderr = await self._device_manager.execute_adb_command(
                ["shell", f"input text {safe_text}"], serial=serial
            )

        dur = int((time.monotonic() - t0) * 1000)
        return MobileActionResult(
            success=code == 0,
            action=f"type_text({len(text)} chars)",
            output=f"Typed text: {text}",
            duration_ms=dur,
        )

    async def press_key(self, key: MobileKey, serial: str | None = None) -> MobileActionResult:
        """Simulate hardware or navigation key event."""
        t0 = time.monotonic()
        keycode = _KEY_CODES.get(key, 0)
        if not keycode:
            return MobileActionResult(
                success=False,
                action=f"press_key({key})",
                error=f"Unsupported mobile key '{key}'",
            )

        code, _, stderr = await self._device_manager.execute_adb_command(
            ["shell", "input", "keyevent", str(keycode)], serial=serial
        )
        dur = int((time.monotonic() - t0) * 1000)
        return MobileActionResult(
            success=code == 0,
            action=f"press_key({key})",
            output=f"Key {key} (code {keycode}) pressed",
            duration_ms=dur,
        )

    async def _resolve_coords(
        self,
        x: int | float,
        y: int | float,
        normalized: bool,
        serial: str | None,
    ) -> tuple[int, int]:
        """Convert relative normalized 0.0~1.0 coordinates to exact pixel coordinates."""
        if not normalized and isinstance(x, int) and isinstance(y, int):
            return x, y

        info = await self._device_manager.get_device_info(serial)
        w = info.screen_width if info else 1080
        h = info.screen_height if info else 2400

        if normalized or (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return int(round(float(x) * w)), int(round(float(y) * h))

        return int(x), int(y)
