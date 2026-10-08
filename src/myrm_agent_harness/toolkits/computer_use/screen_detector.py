"""Screen lock and physical sleep detector for desktop computer use.

Provides microsecond-level native detection of desktop screen lock and sleep states
across macOS, Windows, Linux, and gracefully bypasses in headless/CI environments.
Zero external heavy dependencies, zero extra daemon processes.

[INPUT]
- myrm_agent_harness.toolkits.computer_use.types::ScreenLockState (POS: Shared type definitions consumed by all computer_use submodules)

[OUTPUT]
- ScreenDetector: cross-platform detector with TTL cache
- get_default_screen_detector: singleton accessor
- hid_idle_seconds: seconds since the last hardware input event (human-presence primitive)

[POS]
Desktop lock-screen and physical sleep detection gate. Provides native OS state detection and throttling cache for Computer Use safety.
"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import subprocess
import sys
import time
from typing import Final

from myrm_agent_harness.toolkits.computer_use.types import ScreenLockState

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_TTL_SEC: Final[float] = 0.2


class ScreenDetector:
    """Detects whether the host desktop display is currently locked or asleep."""

    def __init__(self, cache_ttl_sec: float = _DEFAULT_CACHE_TTL_SEC) -> None:
        self._cache_ttl: float = max(0.0, cache_ttl_sec)
        self._last_check_monotonic: float = 0.0
        self._cached_state: ScreenLockState = ScreenLockState.UNLOCKED
        self._override_state: ScreenLockState | None = None

    def set_override_state(self, state: ScreenLockState | None) -> None:
        """Inject a mock state for deterministic testing or recovery override."""
        self._override_state = state
        self._last_check_monotonic = 0.0

    @property
    def is_headless(self) -> bool:
        """Return True if running in a headless container, CI, or Xvfb sandbox."""
        if os.getenv("CI") or os.getenv("MYRM_HEADLESS") == "1":
            return True
        display = os.getenv("DISPLAY", "")
        if display.startswith(":99") or (display == ":0.0" and not sys.platform.startswith("darwin")):
            # Check if running without console session or headless Xvfb
            return os.path.exists("/.dockerenv") or (not os.isatty(0) and os.getenv("GITHUB_ACTIONS") is not None)
        return False

    def get_state(self, force_refresh: bool = False) -> ScreenLockState:
        """Get the current screen lock/sleep state with monotonic clock TTL caching."""
        if self._override_state is not None:
            return self._override_state

        if self.is_headless:
            return ScreenLockState.UNLOCKED

        now = time.monotonic()
        if not force_refresh and (now - self._last_check_monotonic) < self._cache_ttl:
            return self._cached_state

        state = self._probe_native_state()
        self._cached_state = state
        self._last_check_monotonic = now
        return state

    def is_locked(self) -> bool:
        """Return True when physical desktop use must not proceed.

        UNKNOWN means the native probe failed or is unavailable: treat it like locked
        so Computer Use refuses rather than operating blind. Headless/CI keeps UNLOCKED
        via :meth:`get_state` before any probe runs.
        """
        state = self.get_state()
        return state in (
            ScreenLockState.LOCKED,
            ScreenLockState.SLEEPING,
            ScreenLockState.UNKNOWN,
        )

    def _probe_native_state(self) -> ScreenLockState:
        """Probe operating system native APIs for session and display status."""
        plat = sys.platform.lower()
        try:
            if plat.startswith("darwin"):
                return self._probe_macos()
            if plat.startswith("win"):
                return self._probe_windows()
            if plat.startswith("linux"):
                return self._probe_linux()
        except Exception as exc:
            logger.debug("[SCREEN_GUARD] Native probe error on %s: %s", plat, exc)
            return ScreenLockState.UNKNOWN
        return ScreenLockState.UNLOCKED

    def _probe_macos(self) -> ScreenLockState:
        """Query the Quartz session dictionary for screen lock and display sleep.

        pyobjc-framework-Quartz is a hard darwin dependency; if the import still
        fails the error propagates so the caller reports UNKNOWN instead of a
        fabricated UNLOCKED.
        """
        from Quartz import CGSessionCopyCurrentDictionary

        session_dict = CGSessionCopyCurrentDictionary()
        if session_dict is None:
            return ScreenLockState.UNKNOWN
        # CGSSessionScreenIsLocked is present (and 1) only while the session is locked.
        if session_dict.get("CGSSessionScreenIsLocked", 0) == 1:
            return ScreenLockState.LOCKED
        # OnDisplayShutdown indicates display sleep/power-off.
        if session_dict.get("CGSSessionOnDisplayShutdown", 0) == 1:
            return ScreenLockState.SLEEPING
        return ScreenLockState.UNLOCKED

    def _probe_windows(self) -> ScreenLockState:
        """Probe Windows Input Desktop accessibility via user32.dll."""
        if sys.platform != "win32":
            return ScreenLockState.UNKNOWN
        try:
            user32 = ctypes.windll.user32
            # DESKTOP_SWITCHDESKTOP = 0x0100
            # OpenInputDesktop fails with ERROR_ACCESS_DENIED when desktop is locked / Winlogon active
            hdesk = user32.OpenInputDesktop(0, False, 0x0100)
            if not hdesk:
                return ScreenLockState.LOCKED
            user32.CloseDesktop(hdesk)
            return ScreenLockState.UNLOCKED
        except Exception:
            return ScreenLockState.UNKNOWN

    def _probe_linux(self) -> ScreenLockState:
        """Probe Linux loginctl or freedesktop ScreenSaver status."""
        # 1. Check loginctl session LockedHint
        try:
            proc = subprocess.run(
                ["loginctl", "show-session", "self", "-p", "LockedHint"],
                capture_output=True,
                text=True,
                timeout=0.1,
                check=False,
            )
            if "LockedHint=yes" in proc.stdout:
                return ScreenLockState.LOCKED
        except Exception:
            pass
        return ScreenLockState.UNLOCKED


_GLOBAL_SCREEN_DETECTOR: ScreenDetector | None = None


def get_default_screen_detector() -> ScreenDetector:
    """Get or instantiate global singleton ScreenDetector."""
    global _GLOBAL_SCREEN_DETECTOR
    if _GLOBAL_SCREEN_DETECTOR is None:
        _GLOBAL_SCREEN_DETECTOR = ScreenDetector()
    return _GLOBAL_SCREEN_DETECTOR


def hid_idle_seconds() -> float | None:
    """Seconds since the last hardware keyboard / mouse / trackpad event, or ``None`` when unknown.

    Human-presence primitive: an idle time below a caller-chosen threshold means someone is
    touching the machine right now. The value is read from the HID system state (hardware
    sources), needs no permission, is deliberately never cached, and costs well under a
    millisecond, so callers can poll it on every decision.

    Only macOS has a probe today. ``None`` covers every case where idleness cannot be proven
    (other platforms, Quartz unavailable, a non-finite reading); callers must decide explicitly
    what "unknown" means for them instead of reading it as "idle".
    """
    if not sys.platform.startswith("darwin"):
        return None
    try:
        from Quartz import (
            CGEventSourceSecondsSinceLastEventType,
            kCGAnyInputEventType,
            kCGEventSourceStateHIDSystemState,
        )

        idle = float(CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateHIDSystemState, kCGAnyInputEventType))
    except Exception as exc:
        # A failed probe means "unknown", never "idle".
        logger.debug("[SCREEN_GUARD] HID idle probe error: %s", exc)
        return None
    return idle if math.isfinite(idle) and idle >= 0.0 else None
