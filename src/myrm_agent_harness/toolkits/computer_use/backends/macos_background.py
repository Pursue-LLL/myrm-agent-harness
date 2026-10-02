"""macOS background operation helpers — window targeting, focus guard, event-posting permission.

[INPUT]
- backends.macos_input::set_input_target (POS: PID-targeted delivery switch)
- dref.errors::FocusChangedError (POS: focus-leak abort error)

[OUTPUT]
- resolve_app_pid, _capture_window_png, guard_foreground
- _check_post_event_access, _request_post_event_access, _set_enhanced_ui
- _capture_screen_excluding_titles (POS: overlay-excluded fullscreen capture)

[POS]
Background-operation primitives for the macOS backend. Imported by
backends.macos (screenshot/permissions), perception.macos_ax (EnhancedUI)
and execution.healer (routed input + guard).
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)


class _WindowTarget(NamedTuple):
    """Resolved background window: pid + CGWindowID + bounds."""

    pid: int
    window_id: int
    bounds: tuple[int, int, int, int]


def _resolve_target_window(app_name: str, window_index: int = 0) -> _WindowTarget | None:
    """Resolve an on-screen window of ``app_name`` without activating it.

    Returns None when the app has no on-screen window (e.g. minimized):
    callers must fail loudly instead of falling back to fullscreen, so the
    model never mistakes a wrong screenshot for the target.
    """
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
        kCGWindowListOptionOnScreenOnly,
    )

    try:
        windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    except Exception:
        return None
    needle = app_name.lower()
    matches = [w for w in windows if needle in str(w.get("kCGWindowOwnerName", "")).lower()]
    if window_index >= len(matches):
        return None
    chosen = matches[window_index]
    bounds = chosen.get("kCGWindowBounds", {})
    try:
        return _WindowTarget(
            pid=int(chosen.get("kCGWindowOwnerPID", 0)),
            window_id=int(chosen.get("kCGWindowNumber", 0)),
            bounds=(
                int(bounds.get("X", 0)),
                int(bounds.get("Y", 0)),
                int(bounds.get("Width", 0)),
                int(bounds.get("Height", 0)),
            ),
        )
    except (TypeError, ValueError):
        return None


async def _capture_window_png(window_id: int) -> bytes:
    """Capture one window via ``screencapture -l`` (never activates it)."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        proc = await asyncio.create_subprocess_exec(
            "screencapture",
            "-x",
            "-C",
            "-l",
            str(window_id),
            str(tmp_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"window capture failed: {stderr.decode().strip()}")
        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


def _lowest_overlay_window_id(titles: frozenset[str]) -> int | None:
    """z 序最低的 title 匹配窗（below-window 锚点：其上置顶遮罩被整组排除）。"""
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
        kCGWindowListOptionOnScreenOnly,
    )

    try:
        windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    except Exception:
        return None
    # 窗口列表按 z 序 front→back；reversed 的首个匹配 = 最低遮罩窗。
    for window in reversed(windows):
        if str(window.get("kCGWindowName", "")) in titles:
            try:
                return int(window.get("kCGWindowNumber", 0))
            except (TypeError, ValueError):
                return None
    return None


def _capture_screen_excluding_titles(titles: frozenset[str]) -> bytes | None:
    """全屏截图但排除 title 匹配的置顶遮罩窗（隐私帷幕等场景的通用能力）。

    Quartz in-process 通道：锚点取 z 序最低匹配窗，kCGWindowListOptionOnScreenBelowWindow
    截其下全部屏幕内容（真实桌面），锚点之上的整组置顶遮罩被排除。CGRectNull 覆盖全部
    显示器 union，Retina 像素密度与 ``screencapture -x -C`` parity。
    返回 None = 无匹配遮罩或通道失败（调用方降级走原 screencapture 路径；
    遮罩本身不含敏感内容，降级截图只是遮罩黑屏而非泄露）。
    """
    from Quartz import (
        CGRectNull,
        CGWindowListCreateImage,
        kCGWindowImageDefault,
        kCGWindowListOptionOnScreenBelowWindow,
    )

    anchor = _lowest_overlay_window_id(titles)
    if not anchor:
        return None

    try:
        image = CGWindowListCreateImage(
            CGRectNull,
            kCGWindowListOptionOnScreenBelowWindow,
            anchor,
            kCGWindowImageDefault,
        )
    except Exception as error:
        logger.warning("Overlay-excluded capture channel failed: %s", error)
        return None
    if image is None:
        logger.warning("Overlay-excluded capture returned no image; anchor window vanished")
        return None

    try:
        from AppKit import NSBitmapImageFileTypePNG, NSBitmapImageRep  # type: ignore[import-untyped]

        rep = NSBitmapImageRep.alloc().initWithCGImage_(image)
        png = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
        if png is None:
            logger.warning("Overlay-excluded capture PNG serialization returned nothing")
            return None
        return bytes(png)
    except Exception as error:
        logger.warning("Overlay-excluded capture PNG serialization failed: %s", error)
        return None


def resolve_app_pid(app_name: str, window_index: int = 0) -> int | None:
    """Public pid lookup for perception/tools: None when not on-screen."""
    target = _resolve_target_window(app_name, window_index)
    return target.pid if target else None


def _frontmost_pid_nsworkspace() -> int | None:
    """Fast path: read frontmost pid in-process (no subprocess spawn)."""
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        pid = int(app.processIdentifier())
        return pid if pid > 0 else None
    except Exception:
        return None


def _frontmost_pid() -> int | None:
    """Unix pid of the frontmost process, without changing focus."""
    pid = _frontmost_pid_nsworkspace()
    if pid is not None:
        return pid
    try:
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get unix id of first application process whose frontmost is true',
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


@contextmanager
def guard_foreground() -> Iterator[None]:
    """Abort background work that disturbed the foreground app.

    Records the frontmost pid on entry; on exit, a change means the action
    leaked to the wrong app and FocusChangedError is raised.
    """
    from myrm_agent_harness.toolkits.computer_use.dref.errors import (
        FocusChangedError,
    )

    before = _frontmost_pid()
    yield
    after = _frontmost_pid()
    if before is not None and after is not None and before != after:
        raise FocusChangedError(expected=str(before), actual=str(after))


def _check_post_event_access() -> bool | None:
    """Probe CGPostEvent TCC grant; None when the API is unavailable."""
    import ctypes
    import ctypes.util

    cg_path = ctypes.util.find_library("CoreGraphics")
    if not cg_path:
        return None
    try:
        cg = ctypes.cdll.LoadLibrary(cg_path)
        cg.CGPreflightPostEventAccess.restype = ctypes.c_bool
        return bool(cg.CGPreflightPostEventAccess())
    except (OSError, AttributeError):
        return None


def _request_post_event_access() -> bool:
    """Ask macOS to prompt for event-posting access. Returns the grant."""
    import ctypes
    import ctypes.util

    cg_path = ctypes.util.find_library("CoreGraphics")
    if not cg_path:
        return False
    try:
        cg = ctypes.cdll.LoadLibrary(cg_path)
        cg.CGRequestPostEventAccess.restype = ctypes.c_bool
        return bool(cg.CGRequestPostEventAccess())
    except (OSError, AttributeError):
        return False


_post_event_prompted = False


def ensure_post_event_access() -> bool:
    """Probe the event-posting grant; prompt once via system dialog on denial.

    Returns True when background delivery is allowed. A denial is NOT cached:
    a later grant takes effect on the next call without a restart.
    """
    global _post_event_prompted
    if _check_post_event_access():
        return True
    if _post_event_prompted:
        return False
    _post_event_prompted = True
    return _request_post_event_access()


_ENHANCED_UI_SNIPPET = (
    "import ctypes,ctypes.util,sys;"
    "ax=ctypes.cdll.LoadLibrary(ctypes.util.find_library('ApplicationServices'));"
    "cf=ctypes.cdll.LoadLibrary(ctypes.util.find_library('CoreFoundation'));"
    "ax.AXUIElementCreateApplication.argtypes=[ctypes.c_int32];"
    "ax.AXUIElementCreateApplication.restype=ctypes.c_void_p;"
    "ref=ax.AXUIElementCreateApplication(int(sys.argv[1]));"
    "ax.AXUIElementSetAttributeValue.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_void_p];"
    "ax.AXUIElementSetAttributeValue.restype=ctypes.c_int32;"
    "flag=ctypes.c_void_p.in_dll(cf,'kCFBooleanTrue' if sys.argv[2]=='1' else 'kCFBooleanFalse');"
    "sys.exit(0 if ax.AXUIElementSetAttributeValue(ref,b'AXEnhancedUserInterface',flag)==0 else 1)"
)

_enhanced_ui_usable: bool | None = None


def _set_enhanced_ui(pid: int, enabled: bool = True) -> bool:
    """Enable AXEnhancedUserInterface so Electron apps expose full AX trees.

    Fail-soft: returns False when the app refuses; capture continues.
    The attribute write runs in a throwaway subprocess because a denied
    write kills the calling process outright (uncatchable SIGTRAP), which
    try/except cannot contain. Success is cached; denial re-probes so a
    later grant takes effect without a restart.
    """
    import ctypes
    import ctypes.util

    global _enhanced_ui_usable
    if pid <= 0:
        return False
    if _enhanced_ui_usable is True:
        return True
    if not ctypes.util.find_library("ApplicationServices") or not ctypes.util.find_library("CoreFoundation"):
        return False
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                _ENHANCED_UI_SNIPPET,
                str(pid),
                "1" if enabled else "0",
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    _enhanced_ui_usable = result.returncode == 0
    return _enhanced_ui_usable
