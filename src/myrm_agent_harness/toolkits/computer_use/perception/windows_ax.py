"""Windows UI Automation snapshot and invoke.

[INPUT]
- dref.types::SnapshotScope, SnapshotMeta, ElementRef, BBox (POS: @dref accessibility element model)
- dref.errors::AXPermissionRequiredError, AXTreeEmptyError (POS: accessibility error hierarchy)
- types::ActionResult (POS: platform action execution result container)

[OUTPUT]
- WindowsAxSnapshot: Windows accessibility snapshot container with metadata and refs
- capture_ax_snapshot: Windows UI Automation tree capture with targeted window resolution and auto-restore
- invoke_ax_element: Element action execution via UIA pattern invocation or SendKeys
- inspect_foreground: Frontmost window inspection with COM/PowerShell native routing hints

[POS]
Windows platform accessibility perception and element invocation via UI Automation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import cast

from myrm_agent_harness.toolkits.computer_use.dref.errors import (
    AXPermissionRequiredError,
    AXTreeEmptyError,
)
from myrm_agent_harness.toolkits.computer_use.dref.types import (
    BBox,
    ElementRef,
    SnapshotMeta,
    SnapshotScope,
)
from myrm_agent_harness.toolkits.computer_use.types import ActionResult

logger = logging.getLogger(__name__)

_MAX_ELEMENTS = 500
_INTERACTIVE_TYPES = {
    "ButtonControl",
    "CheckBoxControl",
    "ComboBoxControl",
    "EditControl",
    "HyperlinkControl",
    "ListItemControl",
    "MenuItemControl",
    "RadioButtonControl",
    "TabItemControl",
    "TextControl",
}


@dataclass(frozen=True)
class WindowsAxSnapshot:
    meta: SnapshotMeta
    refs: dict[str, ElementRef]


def _collect_controls(
    control: object, refs: dict[str, ElementRef], counter: list[int]
) -> None:
    if counter[0] >= _MAX_ELEMENTS:
        return
    try:
        children = control.GetChildren()  # type: ignore[attr-defined]
    except Exception:
        return

    for child in children:
        if counter[0] >= _MAX_ELEMENTS:
            return
        control_type = getattr(child, "ControlTypeName", "")
        if control_type in _INTERACTIVE_TYPES:
            name = getattr(child, "Name", "") or ""
            value = ""
            try:
                pattern = child.GetValuePattern()
                value = pattern.Value if pattern else ""
            except Exception:
                pass
            try:
                rect = child.BoundingRectangle
            except Exception:
                rect = None
            if rect and rect.width() > 0 and rect.height() > 0:
                ref_id = f"d{counter[0]}"
                refs[ref_id] = ElementRef(
                    ref_id=ref_id,
                    role=control_type,
                    name=name or value,
                    bbox=BBox(rect.left, rect.top, rect.width(), rect.height()),
                    backend_key=str(counter[0]),
                    actions=(
                        ("click", "fill")
                        if control_type == "EditControl"
                        else ("click",)
                    ),
                    value=value,
                )
                counter[0] += 1
        _collect_controls(child, refs, counter)


def _resolve_windows_app_id(control: object) -> str:
    try:
        import uiautomation as auto  # type: ignore[import-not-found]

        pid = int(getattr(control, "ProcessId", 0) or 0)
        if pid <= 0:
            return ""
        process_name = auto.GetProcessNameByPid(pid)
        if process_name:
            return f"win:{process_name.strip().lower()}"
    except Exception:
        return ""
    return ""


def _locate_window(app_name: str) -> object | None:
    """Locate the top-level window of a target app.

    Match priority: exact window title → exact process name → title substring.
    Exact title first keeps follow-up invokes (which pass the captured window
    title) on the same window even when a similar title exists in another app.
    Shared by capture and invoke so backend_key indices stay consistent.
    """
    try:
        import uiautomation as auto
    except ImportError:
        return None

    target_lower = app_name.strip().lower()
    if not target_lower:
        return None

    root = auto.GetRootControl()
    if root is None:
        return None

    try:
        windows = root.GetChildren()
    except Exception:
        return None

    def _title(window: object) -> str:
        return (getattr(window, "Name", "") or "").strip()

    def _process_name(window: object) -> str:
        try:
            pid = int(getattr(window, "ProcessId", 0) or 0)
            if pid <= 0:
                return ""
            name = auto.GetProcessNameByPid(pid)
            return (name or "").strip().lower().removesuffix(".exe")
        except Exception:
            return ""

    for window in windows:
        try:
            if _title(window).lower() == target_lower:
                return cast(object, window)
        except Exception:
            continue
    for window in windows:
        if _process_name(window) == target_lower:
            return cast(object, window)
    for window in windows:
        try:
            title = _title(window)
            if title and target_lower in title.lower():
                return cast(object, window)
        except Exception:
            continue
    return None


def _ensure_window_active_for_target(control: object) -> None:
    """Ensure target window is restored from minimized/suspended state for AX operations.

    Restores minimized windows to normal/maximized visual state and allows brief rendering
    settle time so UWP/XAML and Win32 UI elements are fully instantiated before tree traversal.
    """
    try:
        import time

        import uiautomation as auto

        is_minimized = False
        try:
            pattern = control.GetWindowPattern()  # type: ignore[attr-defined]
            if (
                pattern
                and getattr(pattern, "WindowVisualState", None)
                == auto.WindowVisualState.Minimized
            ):
                is_minimized = True
                pattern.SetWindowVisualState(auto.WindowVisualState.Normal)
        except Exception:
            pass

        if not is_minimized:
            try:
                rect = getattr(control, "BoundingRectangle", None)
                if rect and (
                    rect.width() <= 0
                    or rect.height() <= 0
                    or rect.left < -10000
                    or rect.top < -10000
                ):
                    is_minimized = True
                    try:
                        pattern = control.GetWindowPattern()  # type: ignore[attr-defined]
                        if pattern:
                            pattern.SetWindowVisualState(auto.WindowVisualState.Normal)
                    except Exception:
                        pass
            except Exception:
                pass

        if is_minimized:
            time.sleep(0.05)
    except Exception:
        pass


def capture_ax_snapshot(
    scope: SnapshotScope, app_name: str | None = None
) -> WindowsAxSnapshot:
    try:
        import uiautomation as auto
    except ImportError as exc:
        raise AXTreeEmptyError("uiautomation not installed") from exc

    if scope == "target":
        if not app_name:
            raise AXTreeEmptyError("target scope requires app_name")
        control = _locate_window(app_name)
        if control is None:
            raise AXTreeEmptyError(f"target window not found for app '{app_name}'")
        _ensure_window_active_for_target(control)
    else:
        control = auto.GetForegroundControl()
        if control is None:
            raise AXTreeEmptyError("no foreground window")

    window_name = getattr(control, "Name", "") or ""
    app_id = _resolve_windows_app_id(control)
    refs: dict[str, ElementRef] = {}
    _collect_controls(control, refs, [0])
    if not refs:
        raise AXTreeEmptyError(window_name or "foreground window")

    meta = SnapshotMeta(
        ref_count=len(refs),
        app_name=window_name,
        window_title=window_name,
        scope=scope,
        app_id=app_id,
        truncated=len(refs) >= _MAX_ELEMENTS,
    )
    return WindowsAxSnapshot(meta=meta, refs=refs)


def invoke_ax_element(
    backend_key: str,
    action: str,
    text: str = "",
    app_name: str | None = None,
) -> ActionResult:
    try:
        import uiautomation as auto
    except ImportError:
        return ActionResult(
            success=False, error="uiautomation not installed on Windows"
        )

    index = int(backend_key)
    if app_name:
        control = _locate_window(app_name)
        if control is None:
            return ActionResult(
                success=False, error=f"target window not found for app '{app_name}'"
            )
        _ensure_window_active_for_target(control)
    else:
        control = auto.GetForegroundControl()
        if control is None:
            return ActionResult(success=False, error="No foreground window")

    flat: list[object] = []

    def _flatten(node: object) -> None:
        flat.append(node)
        try:
            for child in node.GetChildren():  # type: ignore[attr-defined]
                _flatten(child)
        except Exception:
            return

    _flatten(control)
    interactive: list[object] = []
    for node in flat:
        if getattr(node, "ControlTypeName", "") not in _INTERACTIVE_TYPES:
            continue
        try:
            rect = node.BoundingRectangle  # type: ignore[attr-defined]
        except Exception:
            continue
        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            continue
        interactive.append(node)
    if index >= len(interactive):
        return ActionResult(success=False, error=f"Stale element index {index}")

    target = interactive[index]
    normalized = action.lower()
    try:
        if normalized in {"fill", "type", "set_value"}:
            target.SendKeys(text)  # type: ignore[attr-defined]
        elif normalized in {
            "click",
            "press",
            "hover",
            "focus",
            "dblclick",
            "double_click",
        }:
            target.Click()  # type: ignore[attr-defined]
        else:
            return ActionResult(success=False, error=f"Unsupported action: {action}")
    except Exception as exc:
        return ActionResult(success=False, error=str(exc))
    return ActionResult(success=True, output=f"UIA {normalized} succeeded")


_COM_AUTOMATABLE_APPS: frozenset[str] = frozenset(
    {
        "Microsoft Excel",
        "Microsoft Word",
        "Microsoft PowerPoint",
        "Microsoft Outlook",
        "Microsoft Access",
        "Microsoft Visio",
        "File Explorer",
        "Windows Terminal",
        "Command Prompt",
        "PowerShell",
        "Notepad",
        "WordPad",
        "Calculator",
        "Adobe Photoshop",
        "Adobe Illustrator",
        "Adobe Acrobat",
        "Adobe InDesign",
        "AutoCAD",
        "WPS",
        "WPS Office",
        "Firefox",
        "Arc",
        "Obsidian",
        "Discord",
        "Visual Studio Code",
        "Cursor",
        "Total Commander",
    }
)

_SNAPSHOT_RECOMMENDATION_BASE = (
    "Call desktop_snapshot_tool(scope='foreground') before desktop_interact_tool. "
    "To act on a background app, use desktop_snapshot_tool(scope='target', app_name='<app name>')."
)


def _native_api_hint(app_name: str) -> str:
    """Return a routing hint if the app supports COM/PowerShell automation."""
    for known in _COM_AUTOMATABLE_APPS:
        if known.lower() in app_name.lower():
            return (
                f" This app ('{app_name}') supports COM/PowerShell automation. "
                "For data retrieval or bulk actions, bash_code_execute_tool with PowerShell is faster and more reliable than GUI interaction."
            )
    return ""


def inspect_foreground() -> dict[str, str | int | bool]:
    try:
        snapshot = capture_ax_snapshot("foreground")
    except AXTreeEmptyError as exc:
        return {
            "app_name": "",
            "window_title": "",
            "interactive_estimate": 0,
            "needs_permission": False,
            "recommendation": f"UIA tree unavailable ({exc}). Use desktop_vision_tool fallback.",
        }
    except AXPermissionRequiredError:
        return {
            "app_name": "",
            "window_title": "",
            "interactive_estimate": 0,
            "needs_permission": True,
            "recommendation": "Grant accessibility permissions, then call desktop_snapshot_tool.",
        }

    base_rec = _SNAPSHOT_RECOMMENDATION_BASE
    native_hint = _native_api_hint(snapshot.meta.app_name)
    return {
        "app_name": snapshot.meta.app_name,
        "window_title": snapshot.meta.window_title,
        "app_id": snapshot.meta.app_id,
        "interactive_estimate": snapshot.meta.ref_count,
        "needs_permission": False,
        "recommendation": base_rec + native_hint,
    }
