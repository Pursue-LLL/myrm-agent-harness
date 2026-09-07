"""Touch, gesture, keyboard, and hardware button input controller for Android devices.

[INPUT]
- types.py, protocols.py, device_manager.py

[OUTPUT]
- MobileInputController

[POS]
Handles precise coordinate clicks, normalized gestures, and Chinese/Unicode Base64 text injection.
"""

from __future__ import annotations

import base64
import logging
import shlex
from typing import Any

from .protocols import MobileInputProtocol
from .types import MobileKeyEvent

logger = logging.getLogger(__name__)

KEYEVENT_MAP: dict[MobileKeyEvent, int] = {
    "HOME": 3,
    "BACK": 4,
    "POWER": 26,
    "TAB": 61,
    "ENTER": 66,
    "DELETE": 67,
    "VOLUME_UP": 24,
    "VOLUME_DOWN": 25,
    "APP_SWITCH": 187,
}


class MobileInputController(MobileInputProtocol):
    """Controls touch inputs and text injection on Android devices."""

    def __init__(self, device_manager: Any) -> None:
        self.dm = device_manager

    def _resolve_coords(
        self,
        serial: str,
        x: int | float,
        y: int | float,
        is_normalized: bool,
    ) -> tuple[int, int]:
        """Convert normalized (0.0~1.0) coordinates to absolute pixels."""
        if not is_normalized:
            return int(x), int(y)

        cached_dev = getattr(self.dm, "_cached_devices", {}).get(serial)
        screen_w = cached_dev.screen_width if cached_dev else 1080
        screen_h = cached_dev.screen_height if cached_dev else 2400

        abs_x = int(float(x) * screen_w)
        abs_y = int(float(y) * screen_h)
        return abs_x, abs_y

    async def tap(
        self,
        serial: str,
        x: int | float,
        y: int | float,
        is_normalized: bool = False,
    ) -> bool:
        """Tap at coordinate."""
        abs_x, abs_y = self._resolve_coords(serial, x, y, is_normalized)
        out = await self.dm.execute_shell(serial, f"input tap {abs_x} {abs_y}")
        return "Error" not in out

    async def swipe(
        self,
        serial: str,
        start_x: int | float,
        start_y: int | float,
        end_x: int | float,
        end_y: int | float,
        duration_ms: int = 300,
        is_normalized: bool = False,
    ) -> bool:
        """Swipe between coordinates with specified duration."""
        x1, y1 = self._resolve_coords(serial, start_x, start_y, is_normalized)
        x2, y2 = self._resolve_coords(serial, end_x, end_y, is_normalized)
        out = await self.dm.execute_shell(
            serial,
            f"input swipe {x1} {y1} {x2} {y2} {duration_ms}",
        )
        return "Error" not in out

    async def input_text(self, serial: str, text: str, clear_before: bool = False) -> bool:
        """Inject text, automatically handling non-ASCII / Chinese characters."""
        if clear_before:
            # Select all and delete
            await self.dm.execute_shell(serial, "input keyevent 29 --meta 113")  # Ctrl+A
            await self.dm.execute_shell(serial, "input keyevent 67")  # DEL

        # Check if text is pure ASCII
        if all(ord(c) < 128 for c in text):
            # Escape spaces and shell specials
            escaped = text.replace(" ", "%s").replace("&", "\\&").replace(";", "\\;")
            out = await self.dm.execute_shell(serial, f"input text {shlex.quote(escaped)}")
            return "Error" not in out

        # For non-ASCII (Chinese / Emojis), try broadcast IME or Base64 clipboard
        b64_str = base64.b64encode(text.encode("utf-8")).decode("ascii")
        # 1. Try ADBKeyboard / FastInput broadcast if installed
        out = await self.dm.execute_shell(
            serial,
            f"am broadcast -a ADB_INPUT_B64 --es msg {b64_str}",
        )
        if "Broadcast completed: result=0" in out:
            return True

        # 2. Fallback: URL encode spaces and try standard input
        escaped_text = text.replace(" ", "%s")
        out = await self.dm.execute_shell(serial, f"input text {shlex.quote(escaped_text)}")
        return "Error" not in out

    async def press_key(self, serial: str, key: MobileKeyEvent) -> bool:
        """Send hardware key event."""
        keycode = KEYEVENT_MAP.get(key)
        if keycode is None:
            logger.warning("Unsupported keyevent: %s", key)
            return False

        out = await self.dm.execute_shell(serial, f"input keyevent {keycode}")
        return "Error" not in out
