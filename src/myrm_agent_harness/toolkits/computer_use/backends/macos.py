"""macOS backend — screencapture + Quartz CGEvent 原生输入.

Uses native `screencapture` for screenshots (zero-dependency, handles Retina)
and Quartz CGEvent (via pyobjc) for keyboard/mouse input. Replaces pyautogui,
whose top-level import pulls in mouseinfo → rubicon-objc, which fails on
arm64 (Apple Silicon) due to a missing `objc_msgSendSuper_stret` symbol
(upstream rubicon-objc bug, unfixed in 0.5.6).

[INPUT]
- types::ScreenInfo, ScreenContext, ActionResult, WindowTextResult (POS: shared type definitions)
- backends.macos_input (POS: Quartz CGEvent keyboard/mouse primitives, global HID unless a target pid is set)
- backends.macos_background (POS: window targeting, window-only capture, foreground guard, event-post permission, overlay-window probe)
- backends.macos_ax_scripts (POS: AppleScript sources of the accessibility probes)
- backends.macos_permissions (POS: TCC permission probes — Accessibility, Screen Recording, capture usability)

[OUTPUT]
- MacOSBackend: ComputerBackend implementation for macOS

[POS]
macOS-specific screen I/O. Only loaded when detect_platform().os_type == "macos".
While an injected overlay window (see set_excluded_capture_window_titles) is on screen,
pointer actions on the global HID path are refused: they would hit the overlay, not the target.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.computer_use.backends import macos_input
from myrm_agent_harness.toolkits.computer_use.backends.macos_ax_scripts import AX_DIALOG_SCRIPT, AX_TEXT_SCRIPT
from myrm_agent_harness.toolkits.computer_use.backends.macos_background import (
    _capture_screen_excluding_titles,
    _capture_window_png,
    _lowest_overlay_window_id,
    _resolve_target_window,
)
from myrm_agent_harness.toolkits.computer_use.backends.macos_permissions import _check_macos_permissions
from myrm_agent_harness.toolkits.computer_use.capture_title_contracts import (
    SNAPSHOT_ONLY_EXCLUDED_CAPTURE_TITLES,
)
from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    ModifierKey,
    PermissionStatus,
    ScreenContext,
    ScreenInfo,
    WindowTextResult,
)

logger = logging.getLogger(__name__)

_MODIFIER_TO_QUARTZ_KEY: dict[ModifierKey, str] = {
    "ctrl": "ctrl",
    "shift": "shift",
    "alt": "option",
    "meta": "command",
}

_POINTER_OCCLUDED_ERROR = (
    "Safety: A screen overlay is covering the desktop, so coordinate-based pointer input "
    "would land on the overlay instead of the target app.\n"
    "[REMEDY_HINT: Use desktop_interact_tool with an @dref element, or keyboard actions, instead.]"
)


class MacOSBackend:
    """macOS screen I/O via screencapture + Quartz CGEvent."""

    def __init__(self) -> None:
        self._screen_info: ScreenInfo | None = None
        self._excluded_capture_titles: frozenset[str] = frozenset()

    def set_excluded_capture_window_titles(self, titles: list[str]) -> None:
        """置顶遮罩窗 title 注入（隐私帷幕等场景）：仅影响全屏截图，定向截窗不受影响。

        通用能力：不携带任何调用方业务语义，帷幕识别契约由注入方持有。
        """
        self._excluded_capture_titles = frozenset(titles)

    def _fullscreen_screenshot_exclusion_titles(self) -> frozenset[str]:
        """Pointer-guard titles plus click-through overlays excluded from captures only."""
        return self._excluded_capture_titles | SNAPSHOT_ONLY_EXCLUDED_CAPTURE_TITLES

    def _pointer_occluded(self) -> ActionResult | None:
        """遮罩窗在屏时拒绝全局 HID 指针投递；放行（含无遮罩/定向投递）返回 None。

        全局投递的事件命中最上层窗口，即遮罩窗本身：遮罩（如隐私帷幕）若把指针输入视作
        路过者操作并回锁屏幕，放行就是 AI 自己的点击锁死自己的会话，且点击也到不了目标应用。
        定向投递（pid）不经 HID 命中测试，键盘事件走焦点应用（遮罩不抢焦点），均不受影响。
        """
        if not self._excluded_capture_titles or macos_input.has_input_target():
            return None
        if _lowest_overlay_window_id(self._excluded_capture_titles) is None:
            return None
        return ActionResult(success=False, error=_POINTER_OCCLUDED_ERROR)

    async def resolve_window_target(self, app_name: str, window_index: int = 0) -> tuple[int, int, int, int] | None:
        target = _resolve_target_window(app_name, window_index)
        return target.bounds if target else None

    async def screenshot(self, app_name: str | None = None, window_index: int = 0) -> bytes:
        """Capture PNG bytes: target window when ``app_name`` is set.

        Targeted capture never activates the window; a missing window raises
        instead of silently returning fullscreen pixels.
        """
        if app_name:
            target = _resolve_target_window(app_name, window_index)
            if target is None:
                raise RuntimeError(
                    f"no on-screen window for app '{app_name}' (index {window_index}); refusing fullscreen fallback"
                )
            return await _capture_window_png(target.window_id)
        capture_titles = self._fullscreen_screenshot_exclusion_titles()
        if capture_titles:
            excluded = _capture_screen_excluding_titles(capture_titles)
            if excluded is not None:
                return excluded
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            proc = await asyncio.create_subprocess_exec(
                "screencapture",
                "-x",
                "-C",
                str(tmp_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"screencapture failed: {stderr.decode()}")
            return tmp_path.read_bytes()
        finally:
            tmp_path.unlink(missing_ok=True)

    async def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        if (occluded := self._pointer_occluded()) is not None:
            return occluded
        modifier_keys = [_MODIFIER_TO_QUARTZ_KEY[m] for m in modifiers] if modifiers else []
        try:
            for key in modifier_keys:
                await asyncio.to_thread(macos_input.key_down, key)
            await asyncio.to_thread(macos_input.click, x=x, y=y, button=button, clicks=clicks)
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
        finally:
            for key in reversed(modifier_keys):
                await asyncio.to_thread(macos_input.key_up, key)

    async def type_text(self, text: str, delay_ms: int = 12, chunk_size: int = 50) -> ActionResult:
        """Type text — ASCII via Quartz unicode input, non-ASCII via clipboard paste."""
        try:
            if text.isascii():
                interval = delay_ms / 1000.0
                for i in range(0, len(text), chunk_size):
                    chunk = text[i : i + chunk_size]
                    await asyncio.to_thread(macos_input.write, chunk, interval=interval)
            else:
                await self._paste_text(text)
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def type_credential(self, label: str) -> ActionResult:
        """Type a credential (password or TOTP) securely from the CredentialVault."""
        from myrm_agent_harness.core.security.credential_vault import (
            get_global_credential_vault,
        )

        vault = get_global_credential_vault()

        is_totp = label.endswith("-totp")
        try:
            if is_totp:
                secret_text = vault.get_totp_token(label)
            else:
                secret_text = vault.get_password(label)
        except Exception:
            return ActionResult(
                success=False,
                error=f"Failed to retrieve credential for label '{label}'",
            )

        try:
            if secret_text.isascii():
                interval = 12 / 1000.0
                # Quartz unicode input — direct OS event injection, no subprocess exposure
                await asyncio.to_thread(macos_input.write, secret_text, interval=interval)
            else:
                await self._paste_text(secret_text)
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _paste_text(self, text: str) -> None:
        """Type non-ASCII text via clipboard paste (Cmd+V), preserving original clipboard."""
        saved = await asyncio.to_thread(_get_clipboard)

        await asyncio.to_thread(_set_clipboard, text)
        await asyncio.to_thread(macos_input.hotkey, "command", "v")
        await asyncio.sleep(0.1)

        if saved is not None:
            await asyncio.to_thread(_set_clipboard, saved)

    async def key(self, keys: str) -> ActionResult:
        try:
            parts = [k.strip() for k in keys.split("+")]
            if len(parts) > 1:
                await asyncio.to_thread(macos_input.hotkey, *parts)
            else:
                await asyncio.to_thread(macos_input.press, parts[0])
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def mouse_move(self, x: int, y: int) -> ActionResult:
        if (occluded := self._pointer_occluded()) is not None:
            return occluded
        try:
            await asyncio.to_thread(macos_input.move_to, x, y)
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def scroll(
        self,
        x: int,
        y: int,
        direction: str,
        amount: int = 3,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        if (occluded := self._pointer_occluded()) is not None:
            return occluded
        modifier_keys = [_MODIFIER_TO_QUARTZ_KEY[m] for m in modifiers] if modifiers else []
        try:
            await asyncio.to_thread(macos_input.move_to, x, y)
            for key in modifier_keys:
                await asyncio.to_thread(macos_input.key_down, key)

            scroll_amount = amount if direction in ("up", "left") else -amount
            if direction in ("up", "down"):
                await asyncio.to_thread(macos_input.scroll, scroll_amount)
            else:
                await asyncio.to_thread(macos_input.hscroll, scroll_amount)

            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
        finally:
            for key in reversed(modifier_keys):
                await asyncio.to_thread(macos_input.key_up, key)

    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        if (occluded := self._pointer_occluded()) is not None:
            return occluded
        modifier_keys = [_MODIFIER_TO_QUARTZ_KEY[m] for m in modifiers] if modifiers else []
        try:
            for key in modifier_keys:
                await asyncio.to_thread(macos_input.key_down, key)

            await asyncio.to_thread(macos_input.move_to, start_x, start_y)
            await asyncio.to_thread(
                macos_input.drag,
                end_x - start_x,
                end_y - start_y,
                duration=0.5,
            )

            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
        finally:
            for key in reversed(modifier_keys):
                await asyncio.to_thread(macos_input.key_up, key)

    async def wait(self, seconds: float) -> ActionResult:
        await asyncio.sleep(seconds)
        return ActionResult(success=True)

    def screen_info(self) -> ScreenInfo:
        if self._screen_info is not None:
            return self._screen_info

        size = macos_input.size()
        dpi_scale = _detect_dpi_scale_quartz(size.width)
        self._screen_info = ScreenInfo(
            width=size.width,
            height=size.height,
            dpi_scale=dpi_scale,
        )
        return self._screen_info

    def screen_context(self) -> ScreenContext:
        pos = macos_input.position()
        return ScreenContext(
            active_window=_get_active_window_title(),
            mouse_x=pos.x,
            mouse_y=pos.y,
        )

    async def window_text(self) -> WindowTextResult:
        """Extract text from frontmost window via Accessibility API (AppleScript)."""
        return await asyncio.to_thread(_extract_window_text)

    async def has_blocking_dialog(self, target_app_names: list[str] | None = None) -> bool:
        """Check if there is an OS-level dialog window blocking the target application."""
        return await asyncio.to_thread(_has_blocking_dialog, target_app_names)

    async def is_browser_active(self) -> bool:
        """Check if the currently active (frontmost) window is a web browser."""
        return await asyncio.to_thread(_is_browser_active)

    def is_screen_locked(self) -> bool:
        from myrm_agent_harness.toolkits.computer_use.screen_detector import get_default_screen_detector

        return get_default_screen_detector().is_locked()

    def is_display_asleep(self) -> bool:
        from myrm_agent_harness.toolkits.computer_use.screen_detector import (
            get_default_screen_detector,
        )
        from myrm_agent_harness.toolkits.computer_use.types import ScreenLockState

        return get_default_screen_detector().get_state() == ScreenLockState.SLEEPING

    async def check_permissions(self, *, probe_capture: bool = False) -> PermissionStatus:
        """Probe macOS Accessibility and Screen Recording TCC permissions."""
        return await asyncio.to_thread(_check_macos_permissions, probe_capture)


def _extract_window_text() -> WindowTextResult:
    """Blocking call to extract window text via AppleScript AXValue traversal."""
    try:
        result = subprocess.run(
            ["osascript", "-e", AX_TEXT_SCRIPT],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "不允许辅助访问" in stderr or "not allowed assistive" in stderr.lower():
                app_name = _get_active_window_title()
                return WindowTextResult(
                    app_name=app_name,
                    success=False,
                    needs_permission=True,
                )
            return WindowTextResult(success=False)

        output = result.stdout.strip()
        parts = output.split("|||", 2)
        app_name = parts[0] if len(parts) > 0 else ""
        win_title = parts[1] if len(parts) > 1 else ""
        text = parts[2] if len(parts) > 2 else ""

        return WindowTextResult(
            app_name=app_name,
            window_title=win_title,
            text=text,
            success=True,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Window text extraction timed out")
        return WindowTextResult(success=False)
    except Exception as e:
        logger.warning("Window text extraction failed: %s", e)
        return WindowTextResult(success=False)


def _detect_dpi_scale_quartz(logical_width: int) -> float:
    """Detect DPI scale via subprocess-isolated AppKit probe, then system_profiler fallback."""
    try:
        probe = subprocess.run(
            [
                "python3",
                "-c",
                "from AppKit import NSScreen; print(NSScreen.mainScreen().backingScaleFactor())",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if probe.returncode == 0:
            scale = float(probe.stdout.strip())
            if scale > 0:
                return scale
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass

    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if "retina" in line.lower() or "@2x" in line:
                return 2.0
    except (subprocess.TimeoutExpired, OSError):
        pass

    return 1.0


def _get_active_window_title() -> str:
    """Get frontmost application window title via AppleScript."""
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get name of first application process whose frontmost is true',
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _is_browser_active() -> bool:
    """Check if the active application is a known web browser."""
    from myrm_agent_harness.toolkits.computer_use.types import KNOWN_BROWSER_NAMES

    app_name = _get_active_window_title().lower()
    return any(browser in app_name for browser in KNOWN_BROWSER_NAMES)


def _has_blocking_dialog(target_app_names: list[str] | None = None) -> bool:
    """Check if the frontmost app has a blocking dialog (AXDialog or AXSheet)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", AX_DIALOG_SCRIPT],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return False

        output = result.stdout.strip()
        parts = output.split("|||")
        if len(parts) != 2:
            return False

        app_name = parts[0]
        has_dialog = parts[1] == "true"

        if not has_dialog:
            return False

        if target_app_names:
            app_name_lower = app_name.lower()
            if not any(target.lower() in app_name_lower for target in target_app_names):
                return False

        return True
    except Exception as e:
        logger.debug("Failed to check for blocking dialog: %s", e)
        return False


def _get_clipboard() -> str | None:
    """Read current clipboard text."""
    try:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2)
        return result.stdout if result.returncode == 0 else None
    except Exception:
        return None


def _set_clipboard(text: str) -> None:
    """Set clipboard text."""
    try:
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(text.encode("utf-8"), timeout=2)
    except Exception:
        pass
