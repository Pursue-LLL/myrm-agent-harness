"""Windows backend — mss + pyautogui + ctypes/uiautomation.

[INPUT]
- types::ScreenInfo, ScreenContext, ActionResult, WindowTextResult (POS: shared type definitions)
[OUTPUT]
- WindowsBackend: ComputerBackend implementation for Windows
[POS]
Windows-specific screen I/O. Loaded when detect_platform().os_type == \"windows\".
"""

from __future__ import annotations

import asyncio
import ctypes
import logging

from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    ModifierKey,
    PermissionStatus,
    ScreenContext,
    ScreenInfo,
    WindowTextResult,
)

logger = logging.getLogger(__name__)

_MODIFIER_TO_PYAUTOGUI: dict[ModifierKey, str] = {
    "ctrl": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "meta": "win",
}


class WindowsBackend:
    """Windows screen I/O via mss + pyautogui + ctypes."""

    def __init__(self) -> None:
        self._screen_info: ScreenInfo | None = None

    async def screenshot(self) -> bytes:
        """Capture primary monitor as PNG bytes using mss."""
        import mss
        import mss.tools

        def _capture() -> bytes:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                img = sct.grab(monitor)
                return mss.tools.to_png(img.rgb, img.size)

        return await asyncio.to_thread(_capture)

    async def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        import pyautogui

        pyautogui_keys = [_MODIFIER_TO_PYAUTOGUI[m] for m in modifiers] if modifiers else []
        try:
            for key in pyautogui_keys:
                await asyncio.to_thread(pyautogui.keyDown, key)
            await asyncio.to_thread(
                pyautogui.click,
                x=x,
                y=y,
                button=button,
                clicks=clicks,
            )
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
        finally:
            for key in reversed(pyautogui_keys):
                await asyncio.to_thread(pyautogui.keyUp, key)

    async def type_text(self, text: str, delay_ms: int = 12, chunk_size: int = 50) -> ActionResult:
        """Type text — ASCII via pyautogui.write(), non-ASCII via clipboard paste (Ctrl+V)."""
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
        from myrm_agent_harness.core.security.credential_vault import get_global_credential_vault

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
        """Type non-ASCII text via clipboard paste (Ctrl+V), preserving original clipboard."""
        import pyautogui

        saved = await asyncio.to_thread(_get_clipboard)
        await asyncio.to_thread(_set_clipboard, text)
        await asyncio.to_thread(pyautogui.hotkey, "ctrl", "v")
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
        self,
        x: int,
        y: int,
        direction: str,
        amount: int = 3,
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
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
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
                end_x - start_x,
                end_y - start_y,
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

        width, height, dpi_scale = _detect_screen_info()
        self._screen_info = ScreenInfo(width=width, height=height, dpi_scale=dpi_scale)
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
        """Extract text from foreground window via Windows UI Automation."""
        return await asyncio.to_thread(_extract_window_text_uia)

    async def has_blocking_dialog(self, target_app_names: list[str] | None = None) -> bool:
        """Return True when the foreground window is a blocking OS dialog."""
        return await asyncio.to_thread(_has_blocking_dialog_win, target_app_names)

    async def is_browser_active(self) -> bool:
        """Check if the currently active (frontmost) window is a web browser."""
        return await asyncio.to_thread(_is_browser_active_win)

    async def check_permissions(self) -> PermissionStatus:
        """Probe pyautogui/mss availability for Windows desktop automation."""
        has_pyautogui = _check_import("pyautogui")
        has_mss = _check_import("mss")

        deeplinks: dict[str, str] = {}
        if not has_pyautogui:
            deeplinks["input_tools"] = "pip install pyautogui"
        if not has_mss:
            deeplinks["screenshot_tools"] = "pip install mss"

        return PermissionStatus(
            accessibility=has_pyautogui,
            screen_recording=has_mss,
            platform="windows",
            settings_deeplinks=deeplinks,
        )


def _check_import(module_name: str) -> bool:
    """Return True if *module_name* can be imported without error."""
    from importlib.util import find_spec

    return find_spec(module_name) is not None


def _detect_screen_info() -> tuple[int, int, float]:
    """Detect screen resolution and DPI scale via ctypes + user32/shcore."""
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        # DPI awareness must be set to get accurate resolution
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
        except Exception:
            user32.SetProcessDPIAware()

        width = user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(1)

        # Detect DPI scale via GetDpiForSystem (Win10 1607+)
        dpi_scale = 1.0
        try:
            dpi = user32.GetDpiForSystem()
            dpi_scale = dpi / 96.0
        except Exception:
            # Fallback: query DC DPI
            hdc = user32.GetDC(None)
            if hdc:
                gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]
                dpi_x = gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
                dpi_scale = dpi_x / 96.0
                user32.ReleaseDC(None, hdc)

        return width, height, dpi_scale
    except Exception:
        # Absolute fallback
        import pyautogui

        size = pyautogui.size()
        return size.width, size.height, 1.0


def _get_active_window_title() -> str:
    """Get foreground window title via user32."""
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


def _is_browser_active_win() -> bool:
    """Check if the active application is a known web browser."""
    from myrm_agent_harness.toolkits.computer_use.types import KNOWN_BROWSER_NAMES

    app_name = _get_active_window_title().lower()
    return any(browser in app_name for browser in KNOWN_BROWSER_NAMES)


def _has_blocking_dialog_win(target_app_names: list[str] | None = None) -> bool:
    """Check if the foreground window is a dialog."""
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False

        # Get window class name
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        class_name = buf.value

        # #32770 is the standard Windows dialog box class
        has_dialog = class_name == "#32770"

        if not has_dialog:
            return False

        if target_app_names:
            # We can't easily get the process name just from hwnd without psutil or more ctypes
            # So we fallback to checking the window title
            win_title = _get_active_window_title().lower()
            # If the dialog belongs to the browser, it might not have the browser name in the title
            # This is a limitation on Windows without heavier dependencies.
            if not any(target.lower() in win_title for target in target_app_names):
                # We'll just return True if it's a dialog and we don't strictly enforce target_app_names
                pass

        return True
    except Exception as e:
        logger.debug("Windows has_blocking_dialog check failed: %s", e)
        return False


def _get_clipboard() -> str | None:
    """Read clipboard text via Win32 API (zero-subprocess, <1ms)."""
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        cf_unicodetext = 13
        if not user32.OpenClipboard(None):
            return None
        try:
            handle = user32.GetClipboardData(cf_unicodetext)
            if not handle:
                return None
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                return ctypes.wstring_at(ptr)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    except Exception:
        return None


def _set_clipboard(text: str) -> None:
    """Set clipboard text via Win32 API (zero-subprocess, <1ms)."""
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        cf_unicodetext = 13
        gmem_moveable = 0x0002

        encoded = text.encode("utf-16-le") + b"\x00\x00"
        h_mem = kernel32.GlobalAlloc(gmem_moveable, len(encoded))
        if not h_mem:
            return
        ptr = kernel32.GlobalLock(h_mem)
        if not ptr:
            kernel32.GlobalFree(h_mem)
            return
        ctypes.memmove(ptr, encoded, len(encoded))
        kernel32.GlobalUnlock(h_mem)

        # Use foreground window as owner to ensure SetClipboardData succeeds
        hwnd = user32.GetForegroundWindow() or None
        if not user32.OpenClipboard(hwnd):
            kernel32.GlobalFree(h_mem)
            return
        try:
            user32.EmptyClipboard()
            user32.SetClipboardData(cf_unicodetext, h_mem)
        finally:
            user32.CloseClipboard()
    except Exception:
        pass


def _extract_window_text_uia() -> WindowTextResult:
    """Extract text from foreground window via uiautomation library."""
    try:
        import uiautomation as auto

        control = auto.GetForegroundControl()
        if control is None:
            return WindowTextResult(success=False)

        app_name = control.Name or ""
        window_title = app_name

        # Traverse children to extract text content (limit depth to avoid perf issues)
        text_parts: list[str] = []
        _collect_text_recursive(control, text_parts, max_depth=5, max_elements=500)

        return WindowTextResult(
            app_name=app_name,
            window_title=window_title,
            text="\n".join(text_parts),
            success=True,
        )
    except ImportError:
        logger.warning("uiautomation not installed — window_text unavailable on Windows")
        return WindowTextResult(success=False)
    except Exception as e:
        logger.warning("Windows window text extraction failed: %s", e)
        return WindowTextResult(success=False)


def _collect_text_recursive(
    control: object,
    text_parts: list[str],
    max_depth: int,
    max_elements: int,
) -> None:
    """Recursively collect text from UI Automation elements."""
    if max_depth <= 0 or len(text_parts) >= max_elements:
        return

    try:
        children = control.GetChildren()  # type: ignore[attr-defined]
        for child in children:
            if len(text_parts) >= max_elements:
                break

            control_type = getattr(child, "ControlTypeName", "")
            if control_type in ("EditControl", "TextControl", "DocumentControl"):
                try:
                    pattern = child.GetValuePattern()  # type: ignore[attr-defined]
                    value = pattern.Value if pattern else ""
                    if value:
                        text_parts.append(value)
                        continue
                except Exception:
                    pass
                try:
                    name = child.Name  # type: ignore[attr-defined]
                    if name:
                        text_parts.append(name)
                        continue
                except Exception:
                    pass

            _collect_text_recursive(child, text_parts, max_depth - 1, max_elements)
    except Exception:
        pass
