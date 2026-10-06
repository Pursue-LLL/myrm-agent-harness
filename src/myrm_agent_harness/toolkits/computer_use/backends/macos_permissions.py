"""macOS TCC permission probes — Accessibility, Screen Recording, capture usability.

[INPUT]
- types::PermissionStatus (POS: shared type definitions)
- backends.macos_background::_check_post_event_access (POS: event-posting permission probe)
- capture_probe::png_bytes_look_capturable (POS: shared functional capture probe, imported lazily)

[OUTPUT]
- _check_macos_permissions: PermissionStatus snapshot consumed by MacOSBackend.check_permissions
- _MACOS_DEEPLINKS: System Settings deep links (also consumed by perception.macos_ax)
- _check_accessibility / _check_screen_recording / _probe_screencapture_capturable / _osascript_ax_capable

[POS]
Permission probes of the macOS backend, kept apart from screen I/O. Every probe is a blocking,
side-effect-free OS query; callers run them in a worker thread.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.computer_use.backends.macos_background import _check_post_event_access
from myrm_agent_harness.toolkits.computer_use.types import PermissionStatus

_MACOS_DEEPLINKS: dict[str, str] = {
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "screen_recording": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
}


def _osascript_ax_capable() -> bool:
    """Probe whether /usr/bin/osascript can actually read the AX tree.

    AX snapshots are executed by the ``osascript`` subprocess, whose macOS TCC
    Accessibility grant is a separate per-binary entry from this Python
    process. AXIsProcessTrusted() only reflects the current (Python) process,
    so an additional probe is required to catch the partial-grant case
    (Python trusted but osascript denied), which would otherwise report
    ``accessibility=True`` while every snapshot still fails.

    The probe must be AX-sensitive AND not depend on the frontmost app having
    a window: ``count of windows of first application process whose frontmost
    is true`` fails with -1728 when the frontmost process has no window,
    which would misreport an already-granted environment as denied.
    ``name of every process whose frontmost is true`` returns the frontmost
    process name with AX access and errors (-25211/-1719) without it.
    """
    script = 'tell application "System Events" to get name of every process whose frontmost is true'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        # Transient slowness under load (backend boot, CPU 90%+) can exceed the
        # 5s budget; the TCC grant itself is persistent, so retry once with a
        # larger budget before reporting a (false) denial.
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip())


def _check_accessibility() -> bool:
    """Check if the desktop automation stack is trusted for Accessibility (AX) access.

    Guards on AXIsProcessTrusted() for the current process (authoritative;
    an AppleScript frontmost-name query succeeds even without AX permission,
    producing false positives) AND an osascript capability probe, because AX
    tree captures run in the osascript subprocess with its own TCC entry.
    """
    import ctypes
    import ctypes.util

    ax_path = ctypes.util.find_library("ApplicationServices")
    if not ax_path:
        return False
    try:
        ax = ctypes.cdll.LoadLibrary(ax_path)
        ax.AXIsProcessTrusted.restype = ctypes.c_bool
        if not bool(ax.AXIsProcessTrusted()):
            return False
    except (OSError, AttributeError):
        return False
    return _osascript_ax_capable()


def _check_screen_recording() -> bool:
    """Check if Screen Recording permission is granted via CGPreflightScreenCaptureAccess."""
    import ctypes
    import ctypes.util

    cg_path = ctypes.util.find_library("CoreGraphics")
    if not cg_path:
        return False
    try:
        cg = ctypes.cdll.LoadLibrary(cg_path)
        cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        return bool(cg.CGPreflightScreenCaptureAccess())
    except (OSError, AttributeError):
        return False


def _probe_screencapture_capturable(*, timeout_s: float = 1.5) -> bool:
    """Functional capture probe: screencapture must yield a non-black usable PNG."""
    from myrm_agent_harness.toolkits.computer_use.capture_probe import (
        png_bytes_look_capturable,
    )

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        result = subprocess.run(
            ["screencapture", "-x", "-C", "-t", "png", str(tmp_path)],
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
        if result.returncode != 0 or not tmp_path.is_file():
            return False
        return png_bytes_look_capturable(tmp_path.read_bytes())
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        tmp_path.unlink(missing_ok=True)


def _check_macos_permissions(probe_capture: bool = False) -> PermissionStatus:
    accessibility = _check_accessibility()
    screen_recording = _check_screen_recording()
    capturable: bool | None = None
    if probe_capture:
        capturable = _probe_screencapture_capturable() if screen_recording else False
    return PermissionStatus(
        accessibility=accessibility,
        screen_recording=screen_recording,
        screen_recording_capturable=capturable,
        post_event_access=_check_post_event_access(),
        platform="macos",
        settings_deeplinks=_MACOS_DEEPLINKS,
    )
