"""ComputerSession — high-level orchestrator for computer use operations.

Encapsulates backend + screenshot processor + coordinate scaler into a
single cohesive API surface. Agent tools interact exclusively with this class.

[INPUT]
- backends.protocol::ComputerBackend (POS: platform-specific I/O)
- screenshot_processor::ScreenshotProcessor (POS: image preprocessing)
- coordinate_scaler::CoordinateScaler (POS: coordinate transformation)
- types::ComputerAction, ComputerUseConfig, ActionResult, PermissionStatus, ExecutionMode, ForegroundPermissionCallback, ForegroundPermissionScope (POS: shared types)

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
    ExecutionMode,
    ForegroundPermissionCallback,
    ForegroundPermissionScope,
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
        permission_callback: ForegroundPermissionCallback | None = None,
    ) -> None:
        self._backend = backend
        self._config = config or ComputerUseConfig()
        self._processor = ScreenshotProcessor(self._config.image_constraints)
        self._scaler: CoordinateScaler | None = None
        self._last_screenshot_bytes: bytes | None = None
        self._screen_info: ScreenInfo | None = None
        self._permission_callback = permission_callback
        self._session_permission_granted: bool = False
        self._always_permission_granted: bool = False
        self._operation_foreground_waived: bool = False

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

    async def check_foreground_permission(
        self,
        *,
        reason: str,
        operation: str,
        estimated_duration_seconds: float = 5.0,
        app_name: str = "",
        window_title: str = "",
    ) -> ActionResult | None:
        """Gate foreground-stealing operations behind user permission.

        Returns None if permission is granted (proceed with execution).
        Returns an ActionResult with error if permission is denied or unavailable.
        """
        mode = self._config.execution_mode

        if mode == ExecutionMode.foreground:
            return None

        if self._always_permission_granted or self._session_permission_granted:
            return None

        if self._operation_foreground_waived:
            return None

        if self._permission_callback is None:
            if mode == ExecutionMode.background_strict:
                return ActionResult(
                    success=False,
                    error="Foreground operation blocked: execution_mode is background_strict "
                    "and no permission callback is configured.",
                )
            return None

        result = await self._permission_callback(
            reason=reason,
            operation=operation,
            estimated_duration_seconds=estimated_duration_seconds,
            app_name=app_name,
            window_title=window_title,
            require_app_approval=False,
        )

        if not result.granted:
            return ActionResult(
                success=False,
                error=f"Foreground permission denied by user. Reason: {reason}",
            )

        if result.scope == ForegroundPermissionScope.session:
            self._session_permission_granted = True
        elif result.scope == ForegroundPermissionScope.always:
            self._always_permission_granted = True

        logger.info("Foreground permission granted (scope=%s): %s", result.scope.value, reason)
        return None

    async def check_app_approval(
        self,
        *,
        app_name: str,
        window_title: str,
        operation: str,
        estimated_duration_seconds: float = 5.0,
    ) -> ActionResult | None:
        """Gate first-time per-app desktop interaction behind user approval."""
        resolved_app = app_name.strip()
        resolved_title = window_title.strip()

        if not resolved_app:
            from myrm_agent_harness.toolkits.computer_use.perception.ax_dispatch import inspect_backend

            fg_info = inspect_backend(self._backend)
            resolved_app = str(fg_info.get("app_name", "") or "").strip()
            if not resolved_title:
                resolved_title = str(fg_info.get("window_title", "") or "").strip()

        if not resolved_app:
            if self._permission_callback is not None or self._config.execution_mode == ExecutionMode.background_strict:
                return ActionResult(
                    success=False,
                    error=(
                        "Desktop control blocked: could not identify the foreground application "
                        "for approval. Call desktop_snapshot_tool first or grant Accessibility access."
                    ),
                )
            return None

        if self._permission_callback is None:
            if self._config.execution_mode == ExecutionMode.background_strict:
                return ActionResult(
                    success=False,
                    error="Desktop app control blocked: no permission callback is configured.",
                )
            return None

        result = await self._permission_callback(
            reason=f"Agent wants to control application '{resolved_app}'",
            operation=operation,
            estimated_duration_seconds=estimated_duration_seconds,
            app_name=resolved_app,
            window_title=resolved_title,
            require_app_approval=True,
        )

        if not result.granted:
            return ActionResult(
                success=False,
                error=f"Desktop control denied for application '{resolved_app}'.",
            )

        self._operation_foreground_waived = True
        return None

    def clear_operation_foreground_waiver(self) -> None:
        """Clear one-shot foreground waiver after the current desktop tool call finishes."""
        self._operation_foreground_waived = False

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

    async def close(self) -> None:
        """Release backend resources (e.g. cua-driver MCP subprocess)."""
        close_fn = getattr(self._backend, "close", None)
        if close_fn is not None:
            try:
                await close_fn()
            except Exception as exc:
                logger.warning("Backend close error (non-fatal): %s", exc)


def create_computer_session(
    config: ComputerUseConfig | None = None,
) -> ComputerSession:
    """Factory: auto-detect platform and create appropriate ComputerSession.

    On all platforms, if ``cua-driver`` is installed, wraps the native backend
    with CuaDriverBackend for background (focus-free) input simulation.
    Otherwise falls back to platform-native backends transparently.
    """
    from myrm_agent_harness.toolkits.code_execution.platform import detect_platform

    platform_info = detect_platform()

    if platform_info.os_type == "macos":
        from myrm_agent_harness.toolkits.computer_use.backends.macos import MacOSBackend

        native_backend: ComputerBackend = MacOSBackend()
    elif platform_info.os_type == "windows":
        from myrm_agent_harness.toolkits.computer_use.backends.windows import WindowsBackend

        native_backend = WindowsBackend()
    else:
        from myrm_agent_harness.toolkits.computer_use.backends.linux import LinuxBackend

        native_backend = LinuxBackend()

    backend = _try_wrap_with_cua_driver(native_backend)
    return ComputerSession(backend=backend, config=config)


def _try_wrap_with_cua_driver(native_backend: ComputerBackend) -> ComputerBackend:
    """Wrap *native_backend* with CuaDriverBackend if cua-driver is available."""
    try:
        from myrm_agent_harness.toolkits.computer_use.backends.cua_driver import (
            CuaDriverBackend,
            is_cua_driver_available,
        )

        if is_cua_driver_available():
            logger.info("cua-driver detected — enabling background input mode")
            return CuaDriverBackend(fallback=native_backend)
        logger.debug("cua-driver not found — using native input (pyautogui)")
    except ImportError:
        logger.debug("mcp SDK not installed — cua-driver backend unavailable")
    return native_backend
