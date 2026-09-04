"""Automatic approval guard for Chrome remote debugging dialogs.

[INPUT]
- CoreGraphics & ApplicationServices (macOS) via standard library ctypes or fallback AppleScript
- asyncio, contextlib, logging, sys, platform

[OUTPUT]
- watch_chrome_remote_debugging_prompt: async context manager guarding CDP connection
- approve_chrome_remote_debugging_prompt: one-shot probe & approve function
- is_accessibility_trusted: probe for macOS accessibility permissions

[POS]
Physical-layer connect guard in BrowserLauncher. Intercepts Chrome 144+ 'Allow remote debugging?'
modal sheets during connect_over_cdp, automatically approving via system-level AX without bringing
Chrome to the foreground, or providing fast structured fallback if accessibility is disabled.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import contextlib
import logging
import platform
import subprocess
import sys
from typing import Final

logger = logging.getLogger(__name__)


__all__ = [
    "ChromePromptGuard",
    "approve_chrome_remote_debugging_prompt",
    "is_accessibility_trusted",
    "watch_chrome_remote_debugging_prompt",
]


_TARGET_PROCESS_NAMES: Final[frozenset[str]] = frozenset({
    "Google Chrome",
    "Chromium",
    "Microsoft Edge",
    "Brave Browser",
    "Google Chrome Canary",
})

# Multilingual keywords for dialog title detection
_DIALOG_TITLE_KEYWORDS: Final[tuple[str, ...]] = (
    "remote debugging",
    "远程调试",
    "遠端除錯",
    "Remote-Debugging",
    "リモート",
    "원격 디버깅",
    "débogage à distance",
)

# Multilingual approve button names
_APPROVE_BUTTON_NAMES: Final[frozenset[str]] = frozenset({
    "Allow",
    "允许",
    "允許",
    "Zulassen",
    "許可",
    "허용",
    "Autoriser",
    "OK",
    "确定",
})

_MACOS_APPROVE_SCRIPT: Final[str] = """\
try
    tell application "System Events"
        set procList to every process whose name is in {"Google Chrome", "Chromium", "Microsoft Edge", "Brave Browser", "Google Chrome Canary"}
        repeat with proc in procList
            repeat with win in (every window of proc)
                set winTitle to ""
                try
                    set winTitle to name of win
                end try
                set titleMatched to false
                if winTitle contains "remote debugging" or winTitle contains "远程调试" or winTitle contains "遠端除錯" or winTitle contains "Remote-Debugging" or winTitle contains "リモート" or winTitle contains "원격 디버깅" then
                    set titleMatched to true
                end if
                if titleMatched then
                    repeat with btn in (every button of win)
                        try
                            set btnName to name of btn
                            if btnName is in {"Allow", "允许", "允許", "Zulassen", "許可", "허용", "Autoriser", "OK", "确定"} then
                                click btn
                                return "clicked:" & btnName
                            end if
                        end try
                    end repeat
                    if (count of (every button of win)) > 0 then
                        try
                            set defaultBtn to button 1 of win
                            click defaultBtn
                            return "clicked_first:" & (name of defaultBtn)
                        end try
                    end if
                end if
            end repeat
        end repeat
    end tell
on error errMsg
    return "error:" & errMsg
end try
return "none"
"""


def is_accessibility_trusted() -> bool:
    """Check if the current process has macOS Accessibility permissions (TCC)."""
    if platform.system() != "Darwin":
        return True
    try:
        import ctypes

        app_services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        app_services.AXIsProcessTrusted.restype = ctypes.c_bool
        app_services.AXIsProcessTrusted.argtypes = []
        return bool(app_services.AXIsProcessTrusted())
    except Exception as exc:
        logger.debug("Failed to query AXIsProcessTrusted: %s", exc)
        return False


def _try_approve_dialog_applescript() -> str:
    """Execute synchronous AppleScript probe to approve Chrome remote debugging dialog.

    Returns:
        Status string: 'clicked:<name>', 'clicked_first:<name>', 'none', or 'error:<msg>'.
    """
    try:
        proc = subprocess.run(
            ["osascript", "-e", _MACOS_APPROVE_SCRIPT],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
        )
        return proc.stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug("AppleScript execution suppressed: %s", exc)
        return f"error:{exc}"


def approve_chrome_remote_debugging_prompt() -> bool:
    """Attempt to detect and approve Chrome's remote debugging prompt on macOS.

    Returns True if approved, False otherwise.
    """
    if platform.system() != "Darwin":
        return False

    status = _try_approve_dialog_applescript()
    if status.startswith("clicked:") or status.startswith("clicked_first:"):
        button_name = status.split(":", 1)[1] if ":" in status else "OK"
        logger.info(
            "Auto-approved Chrome remote debugging prompt via button '%s'",
            button_name,
        )
        return True
    return False


async def _poll_and_approve(stop_event: asyncio.Event, timeout: float, interval: float) -> None:
    """Background polling loop attempting to detect and approve the debugging prompt."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    trusted_warned = False

    while not stop_event.is_set() and loop.time() < deadline:
        if not trusted_warned and not is_accessibility_trusted():
            trusted_warned = True
            logger.info(
                "macOS Accessibility not granted: Chrome remote debugging prompt "
                "may require manual approval. If prompt appears, please click 'Allow'."
            )

        try:
            approved = await asyncio.to_thread(approve_chrome_remote_debugging_prompt)
            if approved:
                break
        except Exception as exc:
            logger.debug("Prompt approval probe error: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except TimeoutError:
            pass


@contextlib.asynccontextmanager
async def watch_chrome_remote_debugging_prompt(
    timeout: float = 4.0,
    interval: float = 0.25,
) -> AsyncIterator[None]:
    """Context manager watching for and auto-approving Chrome remote debugging dialogs.

    Active only on macOS during the connection window. Immediately short-circuits
    and cancels background polling once the protected block exits.
    """
    if sys.platform != "darwin":
        yield
        return

    stop_event = asyncio.Event()
    task = asyncio.create_task(_poll_and_approve(stop_event, timeout, interval))
    try:
        yield
    finally:
        stop_event.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


class ChromePromptGuard:
    """Wrapper class providing static and instance access to Chrome prompt approval guards."""

    watch = staticmethod(watch_chrome_remote_debugging_prompt)
    approve = staticmethod(approve_chrome_remote_debugging_prompt)
    is_trusted = staticmethod(is_accessibility_trusted)

