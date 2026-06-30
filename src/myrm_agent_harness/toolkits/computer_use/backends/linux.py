"""Linux backend — scrot/gnome-screenshot + xdotool.

Covers both native Linux desktops and SaaS sandbox environments (which run Linux).

[INPUT]
- types::ScreenInfo, ScreenContext, ActionResult, WindowTextResult (POS: shared type definitions)

[OUTPUT]
- LinuxBackend: ComputerBackend implementation for Linux

[POS]
Linux-specific screen I/O. Loaded for detect_platform().os_type == "linux".
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    ModifierKey,
    PermissionStatus,
    ScreenContext,
    ScreenInfo,
    WindowTextResult,
)

logger = logging.getLogger(__name__)

CLICK_BUTTONS = {
    "left": "1",
    "right": "3",
    "middle": "2",
}

_MODIFIER_TO_XDOTOOL: dict[ModifierKey, str] = {
    "ctrl": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "meta": "super",
}


def _parse_display_num() -> int | None:
    """Extract display number from $DISPLAY env var (e.g. ':1' → 1, ':99.0' → 99)."""
    display = os.getenv("DISPLAY", "")
    if ":" in display:
        try:
            return int(display.split(":")[1].split(".")[0])
        except (ValueError, IndexError):
            pass
    return None


class LinuxBackend:
    """Linux screen I/O via scrot/gnome-screenshot + xdotool."""

    def __init__(self, display_num: int | None = None) -> None:
        self._screen_info: ScreenInfo | None = None
        self._display_num = display_num if display_num is not None else _parse_display_num()
        self._display_prefix = f"DISPLAY=:{self._display_num} " if self._display_num is not None else ""

    async def _run_cmd(self, cmd: str) -> tuple[str, str, int]:
        """Run a shell command with display prefix."""
        full_cmd = f"{self._display_prefix}{cmd}"
        proc = await asyncio.create_subprocess_shell(
            full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return stdout.decode(), stderr.decode(), proc.returncode or 0

    async def screenshot(self) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            if shutil.which("gnome-screenshot"):
                cmd = f"gnome-screenshot -f {tmp_path} -p"
            elif shutil.which("scrot"):
                cmd = f"scrot -p {tmp_path}"
            else:
                raise RuntimeError("No screenshot tool found (install gnome-screenshot or scrot)")

            _stdout, stderr, returncode = await self._run_cmd(cmd)
            if returncode != 0:
                raise RuntimeError(f"Screenshot failed: {stderr}")
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
        xdotool_mods = [_MODIFIER_TO_XDOTOOL[m] for m in modifiers] if modifiers else []
        try:
            btn = CLICK_BUTTONS.get(button, "1")
            await self._run_cmd(f"xdotool mousemove --sync {x} {y}")

            for mod in xdotool_mods:
                await self._run_cmd(f"xdotool keydown {mod}")

            if clicks > 1:
                repeat_flag = f"--repeat {clicks} --delay 100"
                await self._run_cmd(f"xdotool click {repeat_flag} {btn}")
            else:
                await self._run_cmd(f"xdotool click {btn}")

            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
        finally:
            for mod in reversed(xdotool_mods):
                await self._run_cmd(f"xdotool keyup {mod}")

    async def type_text(self, text: str, delay_ms: int = 12, chunk_size: int = 50) -> ActionResult:
        """Type text — xdotool type for ASCII, xdotool key + xclip for non-ASCII."""
        try:
            if text.isascii():
                for i in range(0, len(text), chunk_size):
                    chunk = text[i : i + chunk_size]
                    await self._run_cmd(f"xdotool type --delay {delay_ms} -- {shlex.quote(chunk)}")
            else:
                await self._paste_text_xclip(text)
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
                proc = await asyncio.create_subprocess_shell(
                    f"{self._display_prefix}xdotool type --delay 12 --file -",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await proc.communicate(secret_text.encode("utf-8"))
                if proc.returncode != 0:
                    raise RuntimeError(f"xdotool type failed: {stderr.decode()}")
            else:
                await self._paste_text_xclip(secret_text)
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def _paste_text_xclip(self, text: str) -> None:
        """Type non-ASCII text via xclip + Ctrl+V, preserving original clipboard."""
        saved_stdout, _, _ = await self._run_cmd("xclip -selection clipboard -o")

        proc = await asyncio.create_subprocess_shell(
            f"{self._display_prefix}xclip -selection clipboard",
            stdin=asyncio.subprocess.PIPE,
        )
        await proc.communicate(text.encode("utf-8"))

        await self._run_cmd("xdotool key ctrl+v")
        await asyncio.sleep(0.1)

        if saved_stdout:
            restore_proc = await asyncio.create_subprocess_shell(
                f"{self._display_prefix}xclip -selection clipboard",
                stdin=asyncio.subprocess.PIPE,
            )
            await restore_proc.communicate(saved_stdout.encode("utf-8"))

    async def key(self, keys: str) -> ActionResult:
        try:
            xdotool_keys = keys.replace("+", " ")
            await self._run_cmd(f"xdotool key -- {xdotool_keys}")
            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))

    async def mouse_move(self, x: int, y: int) -> ActionResult:
        try:
            await self._run_cmd(f"xdotool mousemove --sync {x} {y}")
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
        xdotool_mods = [_MODIFIER_TO_XDOTOOL[m] for m in modifiers] if modifiers else []
        try:
            await self._run_cmd(f"xdotool mousemove --sync {x} {y}")

            for mod in xdotool_mods:
                await self._run_cmd(f"xdotool keydown {mod}")

            scroll_map = {"up": "4", "down": "5", "left": "6", "right": "7"}
            btn = scroll_map.get(direction, "5")
            for _ in range(amount):
                await self._run_cmd(f"xdotool click {btn}")

            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
        finally:
            for mod in reversed(xdotool_mods):
                await self._run_cmd(f"xdotool keyup {mod}")

    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        modifiers: list[ModifierKey] | None = None,
    ) -> ActionResult:
        xdotool_mods = [_MODIFIER_TO_XDOTOOL[m] for m in modifiers] if modifiers else []
        try:
            for mod in xdotool_mods:
                await self._run_cmd(f"xdotool keydown {mod}")

            await self._run_cmd(
                f"xdotool mousemove --sync {start_x} {start_y} mousedown 1 mousemove --sync {end_x} {end_y} mouseup 1"
            )

            return ActionResult(success=True)
        except Exception as e:
            return ActionResult(success=False, error=str(e))
        finally:
            for mod in reversed(xdotool_mods):
                await self._run_cmd(f"xdotool keyup {mod}")

    async def wait(self, seconds: float) -> ActionResult:
        await asyncio.sleep(seconds)
        return ActionResult(success=True)

    def screen_info(self) -> ScreenInfo:
        if self._screen_info is not None:
            return self._screen_info

        width = int(os.getenv("WIDTH", "0"))
        height = int(os.getenv("HEIGHT", "0"))

        if not width or not height:
            width, height = _detect_linux_resolution(self._display_prefix)

        self._screen_info = ScreenInfo(width=width, height=height, dpi_scale=1.0)
        return self._screen_info

    def screen_context(self) -> ScreenContext:
        try:
            result = subprocess.run(
                f"{self._display_prefix}xdotool getactivewindow getwindowname".split(),
                capture_output=True,
                text=True,
                timeout=2,
            )
            window_title = result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            window_title = ""

        try:
            result = subprocess.run(
                f"{self._display_prefix}xdotool getmouselocation".split(),
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split()
                mx = int(parts[0].split(":")[1])
                my = int(parts[1].split(":")[1])
            else:
                mx, my = 0, 0
        except Exception:
            mx, my = 0, 0

        return ScreenContext(active_window=window_title, mouse_x=mx, mouse_y=my)

    async def window_text(self) -> WindowTextResult:
        """Extract text from frontmost window via xdotool + xprop.

        Linux lacks a unified accessibility text API like macOS AX.
        Falls back to window name + WM class as minimal context.
        """
        try:
            result = await self._run_cmd("xdotool getactivewindow getwindowname")
            win_title = result[0].strip() if result[2] == 0 else ""

            wm_class = ""
            try:
                result2 = await self._run_cmd("xdotool getactivewindow")
                win_id = result2[0].strip()
                if win_id:
                    result3 = await self._run_cmd(f"xprop -id {win_id} WM_CLASS")
                    wm_class = result3[0].strip()
            except Exception:
                pass

            return WindowTextResult(
                window_title=win_title,
                app_name=wm_class,
                text="",
                success=True,
            )
        except Exception as e:
            logger.warning("Linux window text extraction failed: %s", e)
            return WindowTextResult(success=False)

    async def has_blocking_dialog(self, target_app_names: list[str] | None = None) -> bool:
        """Check if there is an OS-level dialog window blocking the target application.

        On Linux (X11), we check if the active window has _NET_WM_WINDOW_TYPE_DIALOG.
        """
        try:
            result = await self._run_cmd("xdotool getactivewindow")
            win_id = result[0].strip()
            if not win_id:
                return False

            result2 = await self._run_cmd(f"xprop -id {win_id} _NET_WM_WINDOW_TYPE")
            prop_out = result2[0].strip()

            has_dialog = "_NET_WM_WINDOW_TYPE_DIALOG" in prop_out
            if not has_dialog:
                return False

            if target_app_names:
                # We need to check if the dialog belongs to the target app
                # This is an approximation based on WM_CLASS
                result3 = await self._run_cmd(f"xprop -id {win_id} WM_CLASS")
                wm_class = result3[0].strip().lower()
                if not any(target.lower() in wm_class for target in target_app_names):
                    return False

            return True
        except Exception as e:
            logger.debug("Linux has_blocking_dialog check failed: %s", e)
            return False

    async def is_browser_active(self) -> bool:
        """Check if the currently active (frontmost) window is a web browser."""
        try:
            from myrm_agent_harness.toolkits.computer_use.types import KNOWN_BROWSER_NAMES

            result = await self._run_cmd("xdotool getactivewindow")
            win_id = result[0].strip()
            if not win_id:
                return False

            result2 = await self._run_cmd(f"xprop -id {win_id} WM_CLASS")
            wm_class = result2[0].strip().lower()

            return any(browser in wm_class for browser in KNOWN_BROWSER_NAMES)
        except Exception:
            return False

    async def check_permissions(self) -> PermissionStatus:
        """Linux (X11/Wayland) generally has no TCC-like permission gates."""
        return PermissionStatus(
            accessibility=True,
            screen_recording=True,
            platform="linux",
        )


def _detect_linux_resolution(display_prefix: str) -> tuple[int, int]:
    """Detect screen resolution via xdpyinfo or xrandr."""
    for cmd in [f"{display_prefix}xdpyinfo", f"{display_prefix}xrandr"]:
        try:
            result = subprocess.run(
                cmd.split(),
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if "dimensions:" in line:
                    parts = line.split("dimensions:")[1].strip().split()[0]
                    w, h = parts.split("x")
                    return int(w), int(h)
                if "*" in line and "x" in line:
                    parts = line.strip().split()[0]
                    w, h = parts.split("x")
                    return int(w.split(".")[0]), int(h.split(".")[0])
        except Exception:
            continue

    return 1920, 1080
