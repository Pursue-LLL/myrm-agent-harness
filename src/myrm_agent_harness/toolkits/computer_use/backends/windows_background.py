"""Windows overlay helpers — title-based overlay detection for capture / pointer guard.

[INPUT]
- None (ctypes user32 only)

[OUTPUT]
- _lowest_overlay_hwnd: z-order lowest visible top-level window whose title matches
- _capture_screen_excluding_titles: optional mss fallback when no matching overlay

[POS]
Background-operation primitives for the Windows backend. Privacy curtain windows on
Windows 10 2004+ use WDA_EXCLUDEFROMCAPTURE (desktop); mss still captures the desktop
underneath. Pointer guard uses title match because the curtain receives clicks.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

logger = logging.getLogger(__name__)


def _user32() -> ctypes.WinDLL:
    return ctypes.windll.user32  # type: ignore[attr-defined]


def _window_title(hwnd: int) -> str:
    user32 = _user32()
    GetWindowTextLengthW = user32.GetWindowTextLengthW
    GetWindowTextW = user32.GetWindowTextW
    length = GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _collect_visible_titled_windows() -> list[tuple[int, str]]:
    """Front-to-back z-order of visible top-level windows with non-empty titles."""
    ordered: list[tuple[int, str]] = []
    user32 = _user32()
    IsWindowVisible = user32.IsWindowVisible

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum_proc(hwnd: int, _lparam: int) -> bool:
        if not IsWindowVisible(hwnd):
            return True
        title = _window_title(hwnd)
        if title:
            ordered.append((hwnd, title))
        return True

    user32.EnumWindows(_enum_proc, 0)
    return ordered


def _lowest_overlay_hwnd(titles: frozenset[str]) -> int | None:
    """Lowest z-order hwnd whose title is in *titles* (anchor for guard semantics)."""
    if not titles:
        return None
    match: int | None = None
    for hwnd, title in reversed(_collect_visible_titled_windows()):
        if title in titles:
            match = hwnd
            break
    return match


def _capture_screen_excluding_titles(titles: frozenset[str]) -> bytes | None:
    """Full-screen capture when overlay titles are registered.

    On Windows the privacy curtain is excluded from DXGI/GDI capture via
    SetWindowDisplayAffinity; mss therefore returns the real desktop. When no matching
    overlay is on screen, returns None so the caller uses the normal path unchanged.
    """
    if _lowest_overlay_hwnd(titles) is None:
        return None

    import mss
    import mss.tools

    with mss.mss() as sct:
        monitor = sct.monitors[1]
        img = sct.grab(monitor)
        return mss.tools.to_png(img.rgb, img.size)
