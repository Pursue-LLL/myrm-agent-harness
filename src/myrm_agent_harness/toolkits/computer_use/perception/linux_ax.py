"""Linux AT-SPI snapshot with graceful fallback."""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass

from myrm_agent_harness.toolkits.computer_use.types import ActionResult
from myrm_agent_harness.toolkits.computer_use.dref.errors import AXTreeEmptyError
from myrm_agent_harness.toolkits.computer_use.dref.types import BBox, ElementRef, SnapshotMeta, SnapshotScope

logger = logging.getLogger(__name__)

_MAX_ELEMENTS = 500

_INTERACTIVE_ROLES: frozenset[str] = frozenset({
    "push button", "check box", "text", "entry",
    "menu item", "radio button", "combo box", "link",
})


@dataclass(frozen=True)
class LinuxAxSnapshot:
    meta: SnapshotMeta
    refs: dict[str, ElementRef]


def _try_pyatspi_snapshot() -> LinuxAxSnapshot | None:
    try:
        import pyatspi  # type: ignore[import-untyped]
    except ImportError:
        return None

    desktop = pyatspi.Registry.getDesktop(0)
    if desktop.childCount == 0:
        return None

    refs: dict[str, ElementRef] = {}
    app_name = ""
    window_title = ""
    counter = 0

    def walk(node: object) -> None:
        nonlocal counter, app_name, window_title
        if counter >= _MAX_ELEMENTS:
            return
        try:
            role_name = node.getRoleName()  # type: ignore[attr-defined]
            name = node.name or ""  # type: ignore[attr-defined]
            node.getState()  # type: ignore[attr-defined]
        except Exception:
            return

        if role_name in {"frame", "window"} and not window_title:
            window_title = name
        if role_name in {"application"} and not app_name:
            app_name = name

        if role_name in _INTERACTIVE_ROLES:
            try:
                component = node.queryComponent()  # type: ignore[attr-defined]
                extents = component.getExtents(0)  # type: ignore[attr-defined]
            except Exception:
                extents = None
            if extents and extents.width > 0 and extents.height > 0:
                ref_id = f"d{counter}"
                refs[ref_id] = ElementRef(
                    ref_id=ref_id,
                    role=role_name,
                    name=name,
                    bbox=BBox(extents.x, extents.y, extents.width, extents.height),
                    backend_key=str(counter),
                    actions=("click", "fill") if role_name in {"text", "entry"} else ("click",),
                )
                counter += 1

        try:
            for idx in range(node.childCount):  # type: ignore[attr-defined]
                walk(node.getChildAtIndex(idx))  # type: ignore[attr-defined]
        except Exception:
            return

    for idx in range(desktop.childCount):
        walk(desktop.getChildAtIndex(idx))

    if not refs:
        return None

    meta = SnapshotMeta(
        ref_count=len(refs),
        app_name=app_name,
        window_title=window_title,
        scope="foreground",
        truncated=counter >= _MAX_ELEMENTS,
    )
    return LinuxAxSnapshot(meta=meta, refs=refs)


def capture_ax_snapshot(scope: SnapshotScope, window_title: str | None = None) -> LinuxAxSnapshot:
    del scope, window_title
    pyatspi_snapshot = _try_pyatspi_snapshot()
    if pyatspi_snapshot is not None:
        return pyatspi_snapshot

    if shutil.which("xdotool") is None:
        raise AXTreeEmptyError("pyatspi unavailable and xdotool missing")

    try:
        proc = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise AXTreeEmptyError("Linux AX snapshot failed") from exc

    title = proc.stdout.strip() if proc.returncode == 0 else ""
    if not title:
        raise AXTreeEmptyError("no active window title")

    raise AXTreeEmptyError("AT-SPI tree unavailable in this environment. Install pyatspi or use desktop_vision_tool.")


def invoke_ax_element(backend_key: str, action: str, text: str = "") -> ActionResult:
    """Invoke an AT-SPI element by flat-index (mirrors Windows UIA pattern)."""
    try:
        index = int(backend_key)
    except (ValueError, TypeError):
        return ActionResult(success=False, error=f"Invalid backend_key: {backend_key}")
    if index < 0 or index >= _MAX_ELEMENTS:
        return ActionResult(success=False, error=f"Index {index} out of range [0, {_MAX_ELEMENTS})")

    try:
        import pyatspi  # type: ignore[import-untyped]
    except ImportError:
        return ActionResult(success=False, error="pyatspi not available; use desktop_vision_tool fallback")

    desktop = pyatspi.Registry.getDesktop(0)
    if desktop.childCount == 0:
        return ActionResult(success=False, error="AT-SPI desktop has no applications")

    interactive: list[object] = []

    def _collect(node: object) -> None:
        if len(interactive) > index:
            return
        try:
            role_name = node.getRoleName()  # type: ignore[attr-defined]
            node.getState()  # type: ignore[attr-defined]
        except Exception:
            return
        if role_name in _INTERACTIVE_ROLES:
            try:
                component = node.queryComponent()  # type: ignore[attr-defined]
                extents = component.getExtents(0)  # type: ignore[attr-defined]
            except Exception:
                extents = None
            if extents and extents.width > 0 and extents.height > 0:
                interactive.append(node)
        try:
            for i in range(node.childCount):  # type: ignore[attr-defined]
                _collect(node.getChildAtIndex(i))  # type: ignore[attr-defined]
        except Exception:
            return

    for i in range(desktop.childCount):
        _collect(desktop.getChildAtIndex(i))

    if index >= len(interactive):
        return ActionResult(success=False, error=f"Stale element index {index}")

    target = interactive[index]
    normalized = action.lower()
    try:
        if normalized in {"fill", "type"}:
            try:
                editable = target.queryEditableText()  # type: ignore[attr-defined]
                editable.setTextContents(text)  # type: ignore[attr-defined]
            except Exception:
                action_if = target.queryAction()  # type: ignore[attr-defined]
                if action_if.getNActions() > 0:  # type: ignore[attr-defined]
                    action_if.doAction(0)  # type: ignore[attr-defined]
                subprocess.run(["xdotool", "type", "--clearmodifiers", text], timeout=5, check=False)
        elif normalized in {"click", "press", "hover", "focus", "dblclick", "double_click"}:
            try:
                action_if = target.queryAction()  # type: ignore[attr-defined]
                if action_if.getNActions() > 0:  # type: ignore[attr-defined]
                    action_if.doAction(0)  # type: ignore[attr-defined]
                else:
                    target.queryComponent().grabFocus()  # type: ignore[attr-defined]
            except Exception:
                target.queryComponent().grabFocus()  # type: ignore[attr-defined]
        else:
            return ActionResult(success=False, error=f"Unsupported action: {action}")
    except Exception as exc:
        return ActionResult(success=False, error=str(exc))
    return ActionResult(success=True, output=f"AT-SPI {normalized} succeeded")


_DBUS_AUTOMATABLE_APPS: frozenset[str] = frozenset({
    "nautilus", "Files", "Thunderbird", "LibreOffice",
    "gedit", "GNOME Terminal", "Rhythmbox", "Totem",
    "Evince", "Eye of GNOME",
    "Firefox", "GIMP", "Inkscape", "VLC", "Kate", "Konsole",
    "WPS Office", "Okular", "Dolphin", "KCalc",
})


def _native_api_hint(app_name: str) -> str:
    """Return a routing hint if the app supports D-Bus/CLI automation."""
    for known in _DBUS_AUTOMATABLE_APPS:
        if known.lower() in app_name.lower():
            return (
                f" This app ('{app_name}') supports D-Bus or CLI automation. "
                "For data retrieval or bulk actions, bash_tool with dbus-send/gdbus or CLI flags is faster than GUI interaction."
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
            "recommendation": str(exc),
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
