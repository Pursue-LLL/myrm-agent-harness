"""iPhone Mirroring (com.apple.ScreenContinuity) diagnostic probe and window locator.

Provides lightweight connection gating and viewport bounds detection on macOS Sequoia+.
Gracefully no-ops on Linux / Windows / Cloud environments.

[INPUT]
- Quartz / AppKit (macOS native optional runtime) or pyobjc
- Types: IPhoneMirrorState, IPhoneMirrorProbeResult

[OUTPUT]
- probe_iphone_mirror_state() -> IPhoneMirrorProbeResult
- is_iphone_mirror_app(app_name: str, app_id: str = "") -> bool
- is_iphone_mirror_bundle(bundle_id: str) -> bool
- is_iphone_mirror_connect_window(window_title: str) -> bool
- is_iphone_mirror_supported() -> bool

[POS]
Zero-daemon connection gate for mobile-only workflows on macOS.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from typing import Final

from myrm_agent_harness.toolkits.computer_use.types import (
    IPhoneMirrorProbeResult,
    IPhoneMirrorState,
)

IPHONE_MIRROR_BUNDLE_ID: Final[str] = "com.apple.ScreenContinuity"
IPHONE_MIRROR_APP_NAME: Final[str] = "iPhone Mirroring"
IPHONE_MIRROR_APP_NAME_ZH: Final[str] = "iPhone 镜像"


def is_iphone_mirror_bundle(bundle_id: str) -> bool:
    """Return True if bundle_id corresponds to macOS iPhone Mirroring."""
    return bundle_id.strip().lower() == IPHONE_MIRROR_BUNDLE_ID.lower()


def is_iphone_mirror_app(app_name: str, app_id: str = "") -> bool:
    """Return True if the target app is the macOS iPhone Mirroring host.

    Matches on bundle id (authoritative) or localized app name, so gates stay
    effective even when the snapshot backend cannot resolve an app id.
    """
    if "screencontinuity" in app_id.strip().lower():
        return True
    return "iphone" in app_name.strip().lower()


_CONNECT_WINDOW_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"connect", "连接", "解锁", "unlock", "passcode"}
)


def is_iphone_mirror_connect_window(window_title: str) -> bool:
    """Return True when the window title indicates a connect/unlock pairing prompt."""
    return any(keyword in window_title.lower() for keyword in _CONNECT_WINDOW_KEYWORDS)


def is_iphone_mirror_supported() -> bool:
    """Return True if current host OS is macOS 15.0+ (Sequoia or newer)."""
    if sys.platform != "darwin":
        return False
    try:
        mac_ver = platform.mac_ver()[0]
        if not mac_ver:
            return False
        major = int(mac_ver.split(".")[0])
        return major >= 15
    except Exception:
        return False


def probe_iphone_mirror_state() -> IPhoneMirrorProbeResult:
    """Probe the connection and window state of iPhone Mirroring.

    Returns an IPhoneMirrorProbeResult with state and actionable remedy hint.
    """
    if not is_iphone_mirror_supported():
        return IPhoneMirrorProbeResult(
            state=IPhoneMirrorState.NOT_SUPPORTED,
            is_supported=False,
            detail="iPhone Mirroring requires macOS Sequoia 15.0+ on physical host.",
            remedy_hint="Do not use mobile mirroring on non-macOS or unsupported environments.",
        )

    # Use AppleScript / System Events probe to detect running status and window title
    script = """
    tell application "System Events"
        set isRunning to (count of (processes whose bundle identifier is "com.apple.ScreenContinuity")) > 0
        if not isRunning then
            return "NOT_RUNNING"
        end if
        tell process "iPhone Mirroring"
            set wCount to count of windows
            if wCount is 0 then
                return "NO_WINDOW"
            end if
            set wTitle to name of window 1
            set wPos to position of window 1
            set wSize to size of window 1
            return "WINDOW|" & wTitle & "|" & (item 1 of wPos) & "," & (item 2 of wPos) & "," & (item 1 of wSize) & "," & (item 2 of wSize)
        end tell
    end tell
    """
    try:
        res = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
        output = res.stdout.strip()
        if not output or "NOT_RUNNING" in output:
            return IPhoneMirrorProbeResult(
                state=IPhoneMirrorState.NOT_RUNNING,
                is_supported=True,
                detail="iPhone Mirroring application is not running.",
                remedy_hint="Launch 'iPhone Mirroring' app manually or use native desktop/web alternative.",
            )

        if "NO_WINDOW" in output:
            return IPhoneMirrorProbeResult(
                state=IPhoneMirrorState.NOT_RUNNING,
                is_supported=True,
                detail="iPhone Mirroring is running but has no active visible window.",
                remedy_hint="Bring iPhone Mirroring to front and unlock your iPhone.",
            )

        if output.startswith("WINDOW|"):
            parts = output.split("|")
            title = parts[1] if len(parts) > 1 else ""
            bounds_raw = parts[2] if len(parts) > 2 else ""
            bounds: tuple[int, int, int, int] | None = None
            if bounds_raw:
                try:
                    bx, by, bw, bh = [int(p.strip()) for p in bounds_raw.split(",")]
                    bounds = (bx, by, bw, bh)
                except Exception:
                    bounds = None

            # Detect locked / connect prompt by title heuristics
            if is_iphone_mirror_connect_window(title):
                return IPhoneMirrorProbeResult(
                    state=IPhoneMirrorState.BLOCKED_CONNECT_PROMPT,
                    is_supported=True,
                    window_bounds=bounds,
                    detail=f"iPhone Mirroring requires user action: {title}",
                    remedy_hint="[REMEDY_HINT: iPhone is locked or awaiting connection confirmation. Please unlock/confirm on your device. Agent must NOT click connect automatically.]",
                )

            return IPhoneMirrorProbeResult(
                state=IPhoneMirrorState.READY,
                is_supported=True,
                window_bounds=bounds,
                detail=f"iPhone Mirroring is active: {title}",
            )

        return IPhoneMirrorProbeResult(
            state=IPhoneMirrorState.READY,
            is_supported=True,
            detail="iPhone Mirroring detected.",
        )
    except Exception as exc:
        return IPhoneMirrorProbeResult(
            state=IPhoneMirrorState.NOT_RUNNING,
            is_supported=True,
            detail=f"Probe failed with exception: {exc}",
            remedy_hint="Ensure macOS Accessibility & Screen Recording permissions are granted.",
        )
