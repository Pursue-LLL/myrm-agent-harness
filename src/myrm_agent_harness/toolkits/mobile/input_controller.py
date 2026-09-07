"""Mobile touch, gesture, and text input controller.

[INPUT]
- types::KeyCode, MobileActionResult, Point2D
- protocols::MobileInputControllerProtocol
- device_manager::MobileDeviceManager
- inspector::MobileInspector

[OUTPUT]
- MobileInputController: Simulates taps, swipes, hardware keys, and Unicode/Chinese text inputs

[POS]
Input and gesture automation layer in toolkits/mobile.
"""

from __future__ import annotations

import base64
import logging

from myrm_agent_harness.toolkits.mobile.device_manager import MobileDeviceManager
from myrm_agent_harness.toolkits.mobile.inspector import MobileInspector
from myrm_agent_harness.toolkits.mobile.protocols import MobileInputControllerProtocol
from myrm_agent_harness.toolkits.mobile.types import KeyCode, MobileActionResult

logger = logging.getLogger(__name__)


class MobileInputController(MobileInputControllerProtocol):
    """Executes touch inputs and key events via ADB shell."""

    def __init__(
        self,
        device_manager: MobileDeviceManager,
        inspector: MobileInspector,
    ) -> None:
        self.device_manager = device_manager
        self.inspector = inspector

    async def _resolve_coordinates(
        self,
        x: int | float,
        y: int | float,
        normalized: bool,
        serial: str | None,
    ) -> tuple[int, int]:
        """Convert normalized (0.0-1.0) or raw coordinates to physical integer pixel values."""
        if not normalized:
            return int(x), int(y)

        res = await self.inspector.get_screen_resolution(serial)
        px_x = int(float(x) * res.x)
        px_y = int(float(y) * res.y)
        return max(0, min(res.x - 1, px_x)), max(0, min(res.y - 1, px_y))

    async def tap(
        self,
        x: int | float,
        y: int | float,
        normalized: bool = False,
        serial: str | None = None,
    ) -> MobileActionResult:
        """Tap at coordinate."""
        device = await self.device_manager.ensure_active_device(serial)
        target_x, target_y = await self._resolve_coordinates(x, y, normalized, device.serial)

        code, stdout, stderr = await self.device_manager._run_adb(
            "-s", device.serial, "shell", "input", "tap", str(target_x), str(target_y)
        )
        return MobileActionResult(
            success=code == 0,
            action="tap",
            message=f"Tapped at ({target_x}, {target_y})" if code == 0 else stderr,
            exit_code=code,
            data={"x": target_x, "y": target_y, "normalized": normalized},
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
        """Execute swipe gesture."""
        device = await self.device_manager.ensure_active_device(serial)
        start_x, start_y = await self._resolve_coordinates(x1, y1, normalized, device.serial)
        end_x, end_y = await self._resolve_coordinates(x2, y2, normalized, device.serial)

        code, stdout, stderr = await self.device_manager._run_adb(
            "-s",
            device.serial,
            "shell",
            "input",
            "swipe",
            str(start_x),
            str(start_y),
            str(end_x),
            str(end_y),
            str(duration_ms),
        )
        return MobileActionResult(
            success=code == 0,
            action="swipe",
            message=f"Swiped ({start_x},{start_y}) -> ({end_x},{end_y}) in {duration_ms}ms" if code == 0 else stderr,
            exit_code=code,
            data={
                "start_x": start_x,
                "start_y": start_y,
                "end_x": end_x,
                "end_y": end_y,
                "duration_ms": duration_ms,
            },
        )

    async def type_text(
        self,
        text: str,
        use_broadcast_ime: bool = True,
        serial: str | None = None,
    ) -> MobileActionResult:
        """Inject text into focused input field, handling Chinese and Unicode via Base64 injection."""
        device = await self.device_manager.ensure_active_device(serial)

        # If ASCII only and broadcast IME not forced, use standard input text with escape
        is_ascii = all(ord(c) < 128 for c in text)
        if is_ascii and not use_broadcast_ime:
            escaped_text = text.replace(" ", "%s").replace("&", "\\&").replace("<", "\\<").replace(">", "\\>")
            code, stdout, stderr = await self.device_manager._run_adb(
                "-s", device.serial, "shell", "input", "text", escaped_text
            )
            return MobileActionResult(
                success=code == 0,
                action="type_text",
                message="Injected ASCII text via input text" if code == 0 else stderr,
                exit_code=code,
            )

        # Unicode/Chinese text injection: Attempt ADBKeyBoard / Broadcast IME injection first
        b64_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
        code, stdout, stderr = await self.device_manager._run_adb(
            "-s",
            device.serial,
            "shell",
            "am",
            "broadcast",
            "-a",
            "ADB_INPUT_B64",
            "--es",
            "msg",
            b64_text,
        )

        # If broadcast IME succeeded
        if code == 0 and "result=-1" in (stdout + stderr):
            return MobileActionResult(
                success=True,
                action="type_text",
                message=f"Injected Unicode text via Broadcast IME: '{text}'",
                exit_code=0,
            )

        # Fallback: Character by character or fallback input text
        escaped_text = text.replace(" ", "%s")
        code, stdout, stderr = await self.device_manager._run_adb(
            "-s", device.serial, "shell", "input", "text", escaped_text
        )
        return MobileActionResult(
            success=code == 0,
            action="type_text",
            message=f"Injected text via input fallback: '{text}'" if code == 0 else stderr,
            exit_code=code,
        )

    async def press_key(
        self,
        key_code: KeyCode | int,
        serial: str | None = None,
    ) -> MobileActionResult:
        """Simulate hardware key event."""
        device = await self.device_manager.ensure_active_device(serial)
        code_val = key_code.value if isinstance(key_code, KeyCode) else int(key_code)

        code, stdout, stderr = await self.device_manager._run_adb(
            "-s", device.serial, "shell", "input", "keyevent", str(code_val)
        )
        return MobileActionResult(
            success=code == 0,
            action="press_key",
            message=f"Pressed key code {code_val}" if code == 0 else stderr,
            exit_code=code,
            data={"key_code": code_val},
        )
