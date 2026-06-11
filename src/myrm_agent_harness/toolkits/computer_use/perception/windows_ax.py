"""Windows UI Automation snapshot and invoke."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from myrm_agent_harness.toolkits.computer_use.types import ActionResult
from myrm_agent_harness.toolkits.element_ref.errors import AXPermissionRequiredError, AXTreeEmptyError
from myrm_agent_harness.toolkits.element_ref.types import BBox, ElementRef, SnapshotMeta, SnapshotScope

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


def _collect_controls(control: object, refs: dict[str, ElementRef], counter: list[int]) -> None:
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
                pattern = child.GetValuePattern()  # type: ignore[attr-defined]
                value = pattern.Value if pattern else ""
            except Exception:
                pass
            try:
                rect = child.BoundingRectangle  # type: ignore[attr-defined]
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
                    actions=("click", "fill") if control_type == "EditControl" else ("click",),
                    value=value,
                )
                counter[0] += 1
        _collect_controls(child, refs, counter)


def capture_ax_snapshot(scope: SnapshotScope, window_title: str | None = None) -> WindowsAxSnapshot:
    del scope, window_title
    try:
        import uiautomation as auto
    except ImportError as exc:
        raise AXTreeEmptyError("uiautomation not installed") from exc

    control = auto.GetForegroundControl()
    if control is None:
        raise AXTreeEmptyError("no foreground window")

    app_name = control.Name or ""
    window_title_value = app_name
    refs: dict[str, ElementRef] = {}
    _collect_controls(control, refs, [0])
    if not refs:
        raise AXTreeEmptyError(app_name or "foreground window")

    meta = SnapshotMeta(
        ref_count=len(refs),
        app_name=app_name,
        window_title=window_title_value,
        scope="foreground",
        truncated=len(refs) >= _MAX_ELEMENTS,
    )
    return WindowsAxSnapshot(meta=meta, refs=refs)


def invoke_ax_element(backend_key: str, action: str, text: str = "") -> ActionResult:
    try:
        import uiautomation as auto
    except ImportError:
        return ActionResult(success=False, error="uiautomation not installed on Windows")

    index = int(backend_key)
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
    interactive = [
        node
        for node in flat
        if getattr(node, "ControlTypeName", "") in _INTERACTIVE_TYPES
        and getattr(node, "BoundingRectangle", None) is not None
    ]
    if index >= len(interactive):
        return ActionResult(success=False, error=f"Stale element index {index}")

    target = interactive[index]
    normalized = action.lower()
    try:
        if normalized in {"fill", "type"}:
            target.SendKeys(text)  # type: ignore[attr-defined]
        elif normalized in {"click", "press", "hover", "focus", "dblclick", "double_click"}:
            target.Click()  # type: ignore[attr-defined]
        else:
            return ActionResult(success=False, error=f"Unsupported action: {action}")
    except Exception as exc:
        return ActionResult(success=False, error=str(exc))
    return ActionResult(success=True, output=f"UIA {normalized} succeeded")


_COM_AUTOMATABLE_APPS: frozenset[str] = frozenset({
    "Microsoft Excel", "Microsoft Word", "Microsoft PowerPoint",
    "Microsoft Outlook", "Microsoft Access", "Microsoft Visio",
    "File Explorer", "Windows Terminal", "Command Prompt", "PowerShell",
    "Notepad", "WordPad", "Calculator",
    "Adobe Photoshop", "Adobe Illustrator", "Adobe Acrobat", "Adobe InDesign",
    "AutoCAD", "WPS", "WPS Office", "Firefox", "Arc",
    "Obsidian", "Discord", "Visual Studio Code", "Cursor", "Total Commander",
})


def _native_api_hint(app_name: str) -> str:
    """Return a routing hint if the app supports COM/PowerShell automation."""
    for known in _COM_AUTOMATABLE_APPS:
        if known.lower() in app_name.lower():
            return (
                f" This app ('{app_name}') supports COM/PowerShell automation. "
                "For data retrieval or bulk actions, bash_tool with PowerShell is faster and more reliable than GUI interaction."
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

    base_rec = "Call desktop_snapshot_tool(scope='foreground') before desktop_interact_tool."
    native_hint = _native_api_hint(snapshot.meta.app_name)
    return {
        "app_name": snapshot.meta.app_name,
        "window_title": snapshot.meta.window_title,
        "interactive_estimate": snapshot.meta.ref_count,
        "needs_permission": False,
        "recommendation": base_rec + native_hint,
    }
