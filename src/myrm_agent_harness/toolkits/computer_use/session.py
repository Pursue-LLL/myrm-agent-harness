"""ComputerSession — high-level orchestrator for computer use operations.

Encapsulates backend + screenshot processor + coordinate scaler into a
single cohesive API surface. Agent tools interact exclusively with this class.

[INPUT]
- backends.protocol::ComputerBackend (POS: platform-specific I/O)
- screenshot_processor::ScreenshotProcessor (POS: image preprocessing)
- coordinate_scaler::CoordinateScaler (POS: coordinate transformation)
- types::ComputerAction, ComputerUseConfig, ActionResult, PermissionStatus (POS: shared types)

[OUTPUT]
- ComputerSession: high-level session manager
- create_computer_session: factory function with platform auto-detection

[POS]
Session lifecycle manager. One instance per agent-with-computer-use-enabled.
"""

from __future__ import annotations

import asyncio
import logging

from myrm_agent_harness.toolkits.computer_use.backends.protocols import ComputerBackend
from myrm_agent_harness.toolkits.computer_use.coordinate_scaler import CoordinateScaler
from myrm_agent_harness.toolkits.computer_use.screenshot_processor import ScreenshotProcessor
from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    ComputerUseConfig,
    ModifierKey,
    PermissionStatus,
    ScreenContext,
    ScreenInfo,
)

logger = logging.getLogger(__name__)


class ComputerSession:
    """High-level computer use session.

    Lifecycle: create → take_screenshot → click_at/type_text/key_press/... → close
    """

    def __init__(
        self,
        backend: ComputerBackend,
        config: ComputerUseConfig | None = None,
    ) -> None:
        self._backend = backend
        self._config = config or ComputerUseConfig()
        self._processor = ScreenshotProcessor(self._config.image_constraints)
        self._scaler: CoordinateScaler | None = None
        self._last_screenshot_bytes: bytes | None = None
        self._screen_info: ScreenInfo | None = None

    @property
    def screen_info(self) -> ScreenInfo:
        if self._screen_info is None:
            self._screen_info = self._backend.screen_info()
        return self._screen_info

    @property
    def scaler(self) -> CoordinateScaler | None:
        return self._scaler

    @property
    def screen_context(self) -> ScreenContext:
        return self._backend.screen_context()

    async def take_screenshot(self) -> ActionResult:
        """Capture screen, preprocess, and return as base64 JPEG with screen metadata."""
        info = self.screen_info
        raw_bytes = await self._backend.screenshot()
        self._last_screenshot_bytes = raw_bytes

        b64, (sent_w, sent_h) = self._processor.process(raw_bytes, info)

        self._scaler = CoordinateScaler(
            screen_width=info.width,
            screen_height=info.height,
            sent_width=sent_w,
            sent_height=sent_h,
            dpi_scale=info.dpi_scale,
        )

        return ActionResult(
            success=True,
            screenshot_base64=b64,
            screenshot_size=(sent_w, sent_h),
            output=f"Screenshot captured: {sent_w}x{sent_h} (screen: {info.width}x{info.height}, DPI: {info.dpi_scale}x)",
        )

    async def zoom_region(
        self,
        center_x: int,
        center_y: int,
        size: int = 400,
    ) -> ActionResult:
        """Zoom into a region around (center_x, center_y) in API coordinates.

        Takes a fresh screenshot, crops a region around the target, and returns
        the zoomed-in view for better small-target identification.
        """
        if self._scaler is None:
            await self.take_screenshot()
        assert self._scaler is not None

        screen_x, screen_y = self._scaler.api_to_screen(center_x, center_y)
        info = self.screen_info
        phys_x = int(screen_x * info.dpi_scale)
        phys_y = int(screen_y * info.dpi_scale)
        phys_size = int(size * info.dpi_scale)

        raw_bytes = await self._backend.screenshot()
        self._last_screenshot_bytes = raw_bytes

        left = max(0, phys_x - phys_size // 2)
        top = max(0, phys_y - phys_size // 2)
        right = left + phys_size
        bottom = top + phys_size

        b64, (sent_w, sent_h) = self._processor.crop_and_process(
            raw_bytes,
            (left, top, right, bottom),
            info,
        )

        return ActionResult(
            success=True,
            screenshot_base64=b64,
            screenshot_size=(sent_w, sent_h),
            output=f"Zoomed region around ({center_x},{center_y}): {sent_w}x{sent_h}",
        )

    async def click_at(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        """Click at API coordinates, auto-scaling to screen coordinates."""
        if self._scaler is None:
            await self.take_screenshot()
        assert self._scaler is not None

        if not self._scaler.validate_api_coords(x, y):
            return ActionResult(
                success=False,
                error=f"Coordinates ({x}, {y}) out of bounds (image: {self._scaler.sent_width}x{self._scaler.sent_height})",
            )

        screen_x, screen_y = self._scaler.api_to_screen(x, y)
        result = await self._backend.click(screen_x, screen_y, button, clicks, modifiers=modifiers)

        if result.success:
            await asyncio.sleep(self._config.screenshot_delay)
            screenshot = await self.take_screenshot()
            result.screenshot_base64 = screenshot.screenshot_base64
            result.screenshot_size = screenshot.screenshot_size

        return result

    async def type_text(self, text: str) -> ActionResult:
        """Type text at current cursor position."""
        result = await self._backend.type_text(
            text,
            delay_ms=self._config.typing_delay_ms,
            chunk_size=self._config.typing_chunk_size,
        )
        if result.success:
            screenshot = await self.take_screenshot()
            result.screenshot_base64 = screenshot.screenshot_base64
            result.screenshot_size = screenshot.screenshot_size
        return result

    async def key_press(self, keys: str) -> ActionResult:
        """Press key combination."""
        result = await self._backend.key(keys)
        if result.success:
            await asyncio.sleep(self._config.screenshot_delay)
            screenshot = await self.take_screenshot()
            result.screenshot_base64 = screenshot.screenshot_base64
            result.screenshot_size = screenshot.screenshot_size
        return result

    async def mouse_move_to(self, x: int, y: int) -> ActionResult:
        """Move mouse to API coordinates."""
        if self._scaler is None:
            await self.take_screenshot()
        assert self._scaler is not None

        screen_x, screen_y = self._scaler.api_to_screen(x, y)
        return await self._backend.mouse_move(screen_x, screen_y)

    async def scroll_at(
        self,
        x: int,
        y: int,
        direction: str,
        amount: int = 3,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        """Scroll at API coordinates."""
        if self._scaler is None:
            await self.take_screenshot()
        assert self._scaler is not None

        screen_x, screen_y = self._scaler.api_to_screen(x, y)
        result = await self._backend.scroll(screen_x, screen_y, direction, amount, modifiers=modifiers)

        if result.success:
            await asyncio.sleep(self._config.screenshot_delay)
            screenshot = await self.take_screenshot()
            result.screenshot_base64 = screenshot.screenshot_base64
            result.screenshot_size = screenshot.screenshot_size

        return result

    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        """Drag from start to end in API coordinates."""
        if self._scaler is None:
            await self.take_screenshot()
        assert self._scaler is not None

        sx, sy = self._scaler.api_to_screen(start_x, start_y)
        ex, ey = self._scaler.api_to_screen(end_x, end_y)
        result = await self._backend.drag(sx, sy, ex, ey, modifiers=modifiers)

        if result.success:
            await asyncio.sleep(self._config.screenshot_delay)
            screenshot = await self.take_screenshot()
            result.screenshot_base64 = screenshot.screenshot_base64
            result.screenshot_size = screenshot.screenshot_size

        return result

    async def wait_seconds(self, seconds: float) -> ActionResult:
        """Wait and then take a screenshot."""
        result = await self._backend.wait(seconds)
        screenshot = await self.take_screenshot()
        result.screenshot_base64 = screenshot.screenshot_base64
        result.screenshot_size = screenshot.screenshot_size
        return result

    async def check_permissions(self) -> PermissionStatus:
        """Probe OS-level permissions required for desktop automation."""
        return await self._backend.check_permissions()


def create_computer_session(
    config: ComputerUseConfig | None = None,
) -> ComputerSession:
    """Factory: auto-detect platform and create appropriate ComputerSession."""
    from myrm_agent_harness.toolkits.code_execution.platform import detect_platform

    platform_info = detect_platform()

    if platform_info.os_type == "macos":
        from myrm_agent_harness.toolkits.computer_use.backends.macos import MacOSBackend

        backend: ComputerBackend = MacOSBackend()
    elif platform_info.os_type == "windows":
        from myrm_agent_harness.toolkits.computer_use.backends.windows import WindowsBackend

        backend = WindowsBackend()
    else:
        from myrm_agent_harness.toolkits.computer_use.backends.linux import LinuxBackend

        backend = LinuxBackend()

    return ComputerSession(backend=backend, config=config)
