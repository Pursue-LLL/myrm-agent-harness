"""macOS backend — screencapture + pyautogui.

Uses native `screencapture` for screenshots (zero-dependency, handles Retina)
and `pyautogui` for keyboard/mouse input.

[INPUT]
- types::ScreenInfo, ScreenContext, ActionResult, WindowTextResult (POS: shared type definitions)

[OUTPUT]
- MacOSBackend: ComputerBackend implementation for macOS

[POS]
macOS-specific screen I/O. Only loaded when detect_platform().os_type == "macos".
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    ModifierKey,
    ScreenContext,
    ScreenInfo,
    WindowTextResult,
)

logger = logging.getLogger(__name__)

_MODIFIER_TO_PYAUTOGUI: dict[ModifierKey, str] = {
    "ctrl": "ctrl",
    "shift": "shift",
    "alt": "option",
    "meta": "command",
}


class MacOSBackend:
    """macOS screen I/O via screencapture + pyautogui."""

    def __init__(self) -> None:
        self._screen_info: ScreenInfo | None = None

    async def screenshot(self) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            proc = await asyncio.create_subprocess_exec(
                "screencapture", "-x", "-C", str(tmp_path),
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
        self, x: int, y: int, button: str = "left", clicks: int = 1,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        import pyautogui
        pyautogui_keys = [_MODIFIER_TO_PYAUTOGUI[m] for m in modifiers] if modifiers else []
        try:
            for key in pyautogui_keys:
                await asyncio.to_thread(pyautogui.keyDown, key)
            await asyncio.to_thread(
                pyautogui.click, x=x, y=y, button=button, clicks=clicks,
            )
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
        finally:
            for key in reversed(pyautogui_keys):
                await asyncio.to_thread(pyautogui.keyUp, key)

    async def type_text(self, text: str, delay_ms: int = 12, chunk_size: int = 50) -> ActionResult:
        """Type text — ASCII via pyautogui.write(), non-ASCII via clipboard paste."""
        try:
            if text.isascii():
                import pyautogui
                interval = delay_ms / 1000.0
                for i in range(0, len(text), chunk_size):
                    chunk = text[i : i + chunk_size]
                    await asyncio.to_thread(pyautogui.write, chunk, interval=interval)
            else:
                await self._paste_text(text)
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def type_credential(self, label: str) -> ActionResult:
        """Type a credential (password or TOTP) securely from the CredentialVault."""
        from myrm_agent_harness.toolkits.security.credential_vault import get_global_credential_vault
        vault = get_global_credential_vault()

        is_totp = label.endswith("-totp")
        try:
            if is_totp:
                secret_text = vault.get_totp_token(label)
            else:
                secret_text = vault.get_password(label)
        except Exception as e:
            return ActionResult(success=False, error=f"Failed to retrieve credential for label '{label}': {e}")

        try:
            if secret_text.isascii():
                import pyautogui
                interval = 12 / 1000.0
                # pyautogui.write calls OS APIs directly, no subprocess arguments exposed
                await asyncio.to_thread(pyautogui.write, secret_text, interval=interval)
            else:
                await self._paste_text(secret_text)
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _paste_text(self, text: str) -> None:
        """Type non-ASCII text via clipboard paste (Cmd+V), preserving original clipboard."""
        import pyautogui

        saved = await asyncio.to_thread(_get_clipboard)

        await asyncio.to_thread(_set_clipboard, text)
        await asyncio.to_thread(pyautogui.hotkey, "command", "v")
        await asyncio.sleep(0.1)

        if saved is not None:
            await asyncio.to_thread(_set_clipboard, saved)

    async def key(self, keys: str) -> ActionResult:
        import pyautogui
        try:
            parts = [k.strip() for k in keys.split("+")]
            if len(parts) > 1:
                await asyncio.to_thread(pyautogui.hotkey, *parts)
            else:
                await asyncio.to_thread(pyautogui.press, parts[0])
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def mouse_move(self, x: int, y: int) -> ActionResult:
        import pyautogui
        try:
            await asyncio.to_thread(pyautogui.moveTo, x, y)
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def scroll(
        self, x: int, y: int, direction: str, amount: int = 3,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        import pyautogui
        pyautogui_keys = [_MODIFIER_TO_PYAUTOGUI[m] for m in modifiers] if modifiers else []
        try:
            await asyncio.to_thread(pyautogui.moveTo, x, y)
            for key in pyautogui_keys:
                await asyncio.to_thread(pyautogui.keyDown, key)

            scroll_amount = amount if direction in ("up", "left") else -amount
            if direction in ("up", "down"):
                await asyncio.to_thread(pyautogui.scroll, scroll_amount)
            else:
                await asyncio.to_thread(pyautogui.hscroll, scroll_amount)

            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
        finally:
            for key in reversed(pyautogui_keys):
                await asyncio.to_thread(pyautogui.keyUp, key)

    async def drag(
        self, start_x: int, start_y: int, end_x: int, end_y: int,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        import pyautogui
        pyautogui_keys = [_MODIFIER_TO_PYAUTOGUI[m] for m in modifiers] if modifiers else []
        try:
            for key in pyautogui_keys:
                await asyncio.to_thread(pyautogui.keyDown, key)

            await asyncio.to_thread(pyautogui.moveTo, start_x, start_y)
            await asyncio.to_thread(
                pyautogui.drag,
                end_x - start_x, end_y - start_y,
                duration=0.5,
            )

            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
        finally:
            for key in reversed(pyautogui_keys):
                await asyncio.to_thread(pyautogui.keyUp, key)

    async def wait(self, seconds: float) -> ActionResult:
        await asyncio.sleep(seconds)
        return ActionResult(success=True)

    def screen_info(self) -> ScreenInfo:
        if self._screen_info is not None:
            return self._screen_info

        import pyautogui
        size = pyautogui.size()
        dpi_scale = _detect_dpi_scale_quartz(size.width)
        self._screen_info = ScreenInfo(
            width=size.width,
            height=size.height,
            dpi_scale=dpi_scale,
        )
        return self._screen_info

    def screen_context(self) -> ScreenContext:
        import pyautogui
        pos = pyautogui.position()
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


_AX_TEXT_SCRIPT = '''
tell application "System Events"
    set frontApp to first application process whose frontmost is true
    set appName to name of frontApp
    set winTitle to ""
    try
        set winTitle to name of window 1 of frontApp
    end try

    set textParts to {}
    try
        set uiElements to entire contents of window 1 of frontApp
        set maxElements to (count of uiElements)
        if maxElements > 500 then set maxElements to 500
        repeat with i from 1 to maxElements
            set elem to item i of uiElements
            try
                set elemRole to role of elem
                if elemRole is in {"AXTextField", "AXTextArea", "AXStaticText"} then
                    set elemValue to value of elem
                    if elemValue is not missing value and elemValue is not "" then
                        set end of textParts to elemValue
                    end if
                end if
            end try
        end repeat
    end try

    set AppleScript's text item delimiters to linefeed
    return appName & "|||" & winTitle & "|||" & (textParts as string)
end tell
'''


def _extract_window_text() -> WindowTextResult:
    """Blocking call to extract window text via AppleScript AXValue traversal."""
    try:
        result = subprocess.run(
            ["osascript", "-e", _AX_TEXT_SCRIPT],
            capture_output=True, text=True, timeout=10,
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
    """Detect DPI scale via AppKit NSScreen.backingScaleFactor (accurate, no string parsing)."""
    try:
        from AppKit import NSScreen
        screen = NSScreen.mainScreen()
        scale = screen.backingScaleFactor()
        if scale > 0:
            return float(scale)
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "Retina" in line.lower() or "@2x" in line:
                return 2.0
    except Exception:
        pass

    return 1.0


def _get_active_window_title() -> str:
    """Get frontmost application window title via AppleScript."""
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of first application process '
             'whose frontmost is true'],
            capture_output=True, text=True, timeout=2,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _is_browser_active() -> bool:
    """Check if the active application is a known web browser."""
    from myrm_agent_harness.toolkits.computer_use.types import KNOWN_BROWSER_NAMES
    app_name = _get_active_window_title().lower()
    return any(browser in app_name for browser in KNOWN_BROWSER_NAMES)


_AX_DIALOG_SCRIPT = '''
tell application "System Events"
    set frontApp to first application process whose frontmost is true
    set appName to name of frontApp

    -- If target_app_names is provided, check if frontApp matches
    -- (This logic is handled in Python, here we just return the app name and dialog status)

    set hasDialog to false
    try
        set win1 to window 1 of frontApp
        set winRole to role of win1
        set winSubrole to subrole of win1

        if winRole is "AXWindow" and winSubrole is "AXDialog" then
            set hasDialog to true
        else if winRole is "AXWindow" and winSubrole is "AXSystemDialog" then
            set hasDialog to true
        else if winRole is "AXSheet" then
            set hasDialog to true
        end if
    end try

    return appName & "|||" & (hasDialog as string)
end tell
'''

def _has_blocking_dialog(target_app_names: list[str] | None = None) -> bool:
    """Check if the frontmost app has a blocking dialog (AXDialog or AXSheet)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", _AX_DIALOG_SCRIPT],
            capture_output=True, text=True, timeout=2,
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
