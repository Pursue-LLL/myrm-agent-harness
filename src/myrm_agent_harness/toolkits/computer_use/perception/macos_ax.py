"""macOS accessibility tree capture and invoke via AppleScript.

[INPUT]
- types::ActionResult (POS: action result container)
- dref.errors::AXPermissionRequiredError, AXTreeEmptyError (POS: AX error types)
- dref.types::ElementRef, SnapshotMeta, SnapshotScope, BBox, INTERACTIVE_AX_ROLES (POS: @dref types)
- perception.overlay_roles::normalize_desktop_role (POS: cross-platform role normalization)

[OUTPUT]
- capture_ax_snapshot: AX tree capture with targeted app support and foreground fallback
- invoke_ax_element: AX element invocation with targeted app support
- inspect_foreground: frontmost app metadata and native API routing hints
- refs_for_view_update: DRef list for WebUI desktop inspector overlay

[POS]
macOS AX backend. Captures accessibility trees and invokes elements via AppleScript.
Supports targeted capture by app name (bypasses frontmost) with auto-fallback.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from myrm_agent_harness.toolkits.computer_use.dref.errors import (
    AXPermissionRequiredError,
    AXTreeEmptyError,
)
from myrm_agent_harness.toolkits.computer_use.dref.types import (
    INTERACTIVE_AX_ROLES,
    BBox,
    ElementRef,
    SnapshotMeta,
    SnapshotScope,
)
from myrm_agent_harness.toolkits.computer_use.perception.overlay_roles import (
    normalize_desktop_role,
)
from myrm_agent_harness.toolkits.computer_use.types import ActionResult

logger = logging.getLogger(__name__)

_MAX_ELEMENTS = 500

# System Events reports AX-prefixed and human-readable role strings depending on macOS version.
_SNAPSHOT_ROLE_FILTER: tuple[str, ...] = tuple(
    sorted(
        set(INTERACTIVE_AX_ROLES)
        | {
            "button",
            "checkbox",
            "combo box",
            "pop up button",
            "radio button",
            "slider",
            "tab group",
            "text field",
            "text area",
            "static text",
            "menu item",
            "link",
        },
        key=str.lower,
    )
)

_SNAPSHOT_ALWAYS_EMIT_ROLES: tuple[str, ...] = tuple(
    sorted(
        {
            "AXButton",
            "AXCheckBox",
            "AXTextField",
            "AXTextArea",
            "AXPopUpButton",
            "AXRadioButton",
            "Button",
            "CheckBox",
            "EditControl",
            "RadioButtonControl",
            "button",
            "checkbox",
            "text field",
            "text area",
            "pop up button",
            "radio button",
        },
        key=str.lower,
    )
)


def _applescript_string_list(values: tuple[str, ...]) -> str:
    return ", ".join(f'"{value}"' for value in values)


_TARGET_APP_BUNDLE_IDS: dict[str, str] = {
    "TextEdit": "com.apple.TextEdit",
}


def _build_app_selector(target_app: str | None) -> str:
    if not target_app:
        return "set targetApp to first application process whose frontmost is true"
    bundle_id = _TARGET_APP_BUNDLE_IDS.get(target_app)
    if bundle_id:
        return f'set targetApp to first application process whose bundle identifier is "{bundle_id}"'
    escaped = target_app.replace('"', '\\"')
    # Exact name first; contains fallback so short names like "Excel" match "Microsoft Excel".
    # AppleScript's `whose A or B` does not guarantee exact-priority, so use try/on error.
    return (
        "try\n"
        f'    set targetApp to first application process whose name is "{escaped}"\n'
        "on error\n"
        f'    set targetApp to first application process whose name contains "{escaped}"\n'
        "end try"
    )


def _build_ax_snapshot_script(*, target_app: str | None = None) -> str:
    role_filter = _applescript_string_list(_SNAPSHOT_ROLE_FILTER)
    always_emit_roles = _applescript_string_list(_SNAPSHOT_ALWAYS_EMIT_ROLES)
    app_selector = _build_app_selector(target_app)
    return f"""
on serializeElement(idx, elemRole, elemName, elemValue, posX, posY, sizeW, sizeH)
    set safeName to my escapeText(elemName)
    set safeValue to my escapeText(elemValue)
    return idx & "|||" & elemRole & "|||" & safeName & "|||" & safeValue & "|||" & posX & "|||" & posY & "|||" & sizeW & "|||" & sizeH
end serializeElement

on escapeText(t)
    if t is missing value then return ""
    set s to t as string
    set bs to ASCII character 92
    set s to my replaceText(s, bs, bs & bs)
    set s to my replaceText(s, "|||", "/")
    return s
end escapeText

on replaceText(sourceText, oldText, newText)
    set AppleScript's text item delimiters to oldText
    set parts to text items of sourceText
    set AppleScript's text item delimiters to newText
    set resultText to parts as string
    set AppleScript's text item delimiters to ""
    return resultText
end replaceText

tell application "System Events"
    {app_selector}
    set appName to name of targetApp
    set bundleId to ""
    try
        set bundleId to bundle identifier of targetApp
    end try
    set appPid to unix id of targetApp
    set winTitle to ""
    try
        set winTitle to name of window 1 of targetApp
    end try

    set outputLines to {{}}
    set end of outputLines to appName & "|||META|||" & winTitle & "|||" & bundleId & "|||" & appPid

    set uiElements to {{}}
    try
        set uiElements to entire contents of window 1 of targetApp
    on error errMsg
        if errMsg contains "assistive access" or errMsg contains "辅助访问" then
            set end of outputLines to "AX_PERMISSION_ERROR|||" & errMsg
            set AppleScript's text item delimiters to linefeed
            return outputLines as string
        end if
    end try
    try
        set maxElements to count of uiElements
        if maxElements > {_MAX_ELEMENTS} then set maxElements to {_MAX_ELEMENTS}
        repeat with i from 1 to maxElements
            set elem to item i of uiElements
            try
                set elemRole to role of elem
                if elemRole is in {{{role_filter}}} then
                    set elemName to ""
                    set elemValue to ""
                    try
                        set elemName to name of elem
                    end try
                    try
                        set elemValue to value of elem
                    end try
                    if elemName is missing value then set elemName to ""
                    if elemValue is missing value then set elemValue to ""
                    if elemName is not "" or elemValue is not "" or elemRole is in {{{always_emit_roles}}} then
                        set elemPos to position of elem
                        set elemSize to size of elem
                        set end of outputLines to my serializeElement(i, elemRole, elemName, elemValue, item 1 of elemPos, item 2 of elemPos, item 1 of elemSize, item 2 of elemSize)
                    end if
                end if
            end try
        end repeat
    end try

    set AppleScript's text item delimiters to linefeed
    return outputLines as string
end tell
"""


_AX_SNAPSHOT_SCRIPT = _build_ax_snapshot_script()

_AX_FOREGROUND_META_SCRIPT = """
tell application "System Events"
    set frontApp to first application process whose frontmost is true
    set appName to name of frontApp
    set bundleId to ""
    try
        set bundleId to bundle identifier of frontApp
    end try
    set winTitle to ""
    try
        set winTitle to name of window 1 of frontApp
    end try
    return appName & "|||" & winTitle & "|||" & bundleId
end tell
"""


def _read_foreground_meta() -> tuple[str, str, str]:
    try:
        result = subprocess.run(
            ["osascript", "-e", _AX_FOREGROUND_META_SCRIPT],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return "", "", ""
    if result.returncode != 0:
        return "", "", ""
    parts = result.stdout.strip().split("|||")
    app_name = parts[0] if parts else ""
    window_title = parts[1] if len(parts) > 1 else ""
    app_id = parts[2] if len(parts) > 2 else ""
    return app_name, window_title, app_id


@dataclass(frozen=True)
class MacAxSnapshot:
    meta: SnapshotMeta
    refs: dict[str, ElementRef]


def _resolve_target_app(scope: SnapshotScope, app_name: str | None) -> str | None:
    """Extract target app name from scope. Returns None for foreground mode."""
    if scope == "target" and app_name:
        return app_name
    return None


def _run_ax_snapshot(script: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        raise AXTreeEmptyError("macOS AX snapshot timed out") from exc


def _parse_ax_output(
    result: subprocess.CompletedProcess[str],
    effective_scope: SnapshotScope,
) -> MacAxSnapshot:
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "不允许辅助访问" in stderr or "not allowed assistive" in stderr.lower():
            raise AXPermissionRequiredError("macOS")
        raise AXTreeEmptyError(stderr or "AppleScript AX snapshot failed")

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise AXTreeEmptyError("no AX output")

    # The AppleScript snapshot script surfaces an AX permission denial as a
    # dedicated marker line (the `entire contents` call is guarded by try/on
    # error inside osascript, so it would otherwise be misreported as an empty
    # tree instead of a missing permission).
    if lines[0].startswith("AX_PERMISSION_ERROR|||"):
        raise AXPermissionRequiredError("macOS")

    meta_line = lines[0].split("|||")
    # Format: appName|||META|||winTitle|||bundleId|||appPid
    app_name = meta_line[0] if meta_line else ""
    window_name = meta_line[2] if len(meta_line) > 2 else ""
    app_id = meta_line[3] if len(meta_line) > 3 else ""
    pid_str = meta_line[4] if len(meta_line) > 4 else ""
    pid = int(pid_str) if pid_str.isdigit() else 0

    refs: dict[str, ElementRef] = {}
    ref_index = 0
    truncated = len(lines) - 1 >= _MAX_ELEMENTS
    for line in lines[1:]:
        parts = line.split("|||")
        if len(parts) < 8:
            continue
        backend_index, role, name, value, x_s, y_s, w_s, h_s = parts[:8]
        if role not in INTERACTIVE_AX_ROLES and role not in set(_SNAPSHOT_ROLE_FILTER):
            continue
        try:
            bbox = BBox(
                int(float(x_s)), int(float(y_s)), int(float(w_s)), int(float(h_s))
            )
        except ValueError:
            continue
        if bbox.width <= 0 or bbox.height <= 0:
            continue
        ref_id = f"d{ref_index}"
        actions = (
            ("click", "fill") if role in {"AXTextField", "AXTextArea"} else ("click",)
        )
        refs[ref_id] = ElementRef(
            ref_id=ref_id,
            role=role,
            name=name or value,
            bbox=bbox,
            backend_key=backend_index,
            actions=actions,
            value=value,
        )
        ref_index += 1

    if not refs:
        raise AXTreeEmptyError(app_name or "frontmost app")

    meta = SnapshotMeta(
        ref_count=len(refs),
        app_name=app_name,
        window_title=window_name,
        scope=effective_scope,
        app_id=app_id,
        pid=pid,
        truncated=truncated,
    )
    return MacAxSnapshot(meta=meta, refs=refs)


def capture_ax_snapshot(
    scope: SnapshotScope, app_name: str | None = None
) -> MacAxSnapshot:
    target_app = _resolve_target_app(scope, app_name)

    if target_app is not None:
        targeted_script = _build_ax_snapshot_script(target_app=target_app)
        try:
            result = _run_ax_snapshot(targeted_script)
            return _parse_ax_output(result, effective_scope=scope)
        except AXTreeEmptyError:
            logger.info(
                "Targeted AX snapshot for '%s' failed, falling back to foreground",
                target_app,
            )

    result = _run_ax_snapshot(_AX_SNAPSHOT_SCRIPT)
    return _parse_ax_output(result, effective_scope="foreground")


def _build_ax_invoke_script(target_app: str | None = None) -> str:
    app_selector = _build_app_selector(target_app)
    return f"""
on escapeText(t)
    if t is missing value then return ""
    set s to t as string
    set bs to ASCII character 92
    set dq to ASCII character 34
    set s to my replaceText(s, bs, bs & bs)
    set s to my replaceText(s, dq, bs & dq)
    return s
end escapeText

on replaceText(sourceText, oldText, newText)
    set AppleScript's text item delimiters to oldText
    set parts to text items of sourceText
    set AppleScript's text item delimiters to newText
    set resultText to parts as string
    set AppleScript's text item delimiters to ""
    return resultText
end replaceText

on run argv
    set actionName to item 1 of argv
    set elemIndex to item 2 of argv as integer
    set inputText to item 3 of argv

    tell application "System Events"
        {app_selector}
        set uiElements to entire contents of window 1 of targetApp
        set elem to item elemIndex of uiElements
        if actionName is "fill" then
            set value of elem to inputText
            return "OK"
        end if
        if actionName is "set_value" then
            set value of elem to inputText
            return "OK"
        end if
        if actionName is "click" then
            try
                perform action "AXPress" of elem
                return "OK"
            on error
                click elem
                return "OK"
            end try
        end if
        if actionName is "press" then
            perform action "AXPress" of elem
            return "OK"
        end if
        return "UNSUPPORTED"
    end tell
end run
"""


_AX_INVOKE_SCRIPT = _build_ax_invoke_script()


def invoke_ax_element(
    backend_key: str,
    action: str,
    text: str = "",
    app_name: str | None = None,
) -> ActionResult:
    normalized_action = action.lower()
    if normalized_action in {"dblclick", "double_click"}:
        normalized_action = "click"
    if normalized_action not in {
        "click",
        "fill",
        "set_value",
        "press",
        "focus",
        "hover",
    }:
        return ActionResult(success=False, error=f"Unsupported AX action: {action}")

    ax_action = (
        "fill" if normalized_action in {"fill", "type", "set_value"} else "click"
    )
    invoke_script = (
        _build_ax_invoke_script(target_app=app_name) if app_name else _AX_INVOKE_SCRIPT
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", invoke_script, ax_action, backend_key, text],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return ActionResult(success=False, error="AX invoke timed out")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "不允许辅助访问" in stderr or "not allowed assistive" in stderr.lower():
            return ActionResult(
                success=False, error="Accessibility permission required on macOS"
            )
        return ActionResult(success=False, error=stderr or "AX invoke failed")

    if result.stdout.strip() != "OK":
        return ActionResult(
            success=False, error=result.stdout.strip() or "AX invoke failed"
        )
    return ActionResult(success=True, output=f"AX {ax_action} succeeded")


_SCRIPTABLE_APPS: frozenset[str] = frozenset(
    {
        "Finder",
        "Mail",
        "Safari",
        "Notes",
        "Reminders",
        "Calendar",
        "Messages",
        "Preview",
        "Music",
        "TV",
        "Podcasts",
        "Photos",
        "Keynote",
        "Pages",
        "Numbers",
        "TextEdit",
        "Terminal",
        "Script Editor",
        "System Settings",
        "System Preferences",
        "Automator",
        "Shortcuts",
        "Microsoft Excel",
        "Microsoft Word",
        "Microsoft PowerPoint",
        "Microsoft Outlook",
        "Google Chrome",
        "Slack",
        "Spotify",
        "iTerm2",
        "iTerm",
        "Adobe Photoshop",
        "Adobe Illustrator",
        "Adobe Acrobat",
        "Adobe InDesign",
        "Sketch",
        "Final Cut Pro",
        "Logic Pro",
        "GarageBand",
        "Xcode",
        "WPS Office",
        "Firefox",
        "Arc",
        "Obsidian",
        "Discord",
        "Visual Studio Code",
        "Cursor",
        "OmniGraffle",
        "DEVONthink",
        "Affinity Designer",
    }
)


_SNAPSHOT_RECOMMENDATION_BASE = (
    "Call desktop_snapshot_tool(scope='foreground') before desktop_interact_tool. "
    "To act on a background app, use desktop_snapshot_tool(scope='target', app_name='<app name>')."
)


def _native_api_hint(app_name: str) -> str:
    """Return a routing hint if the app supports AppleScript automation."""
    if app_name in _SCRIPTABLE_APPS:
        return (
            f" This app ('{app_name}') supports native AppleScript automation. "
            "For data retrieval or bulk actions, bash_code_execute_tool with osascript is faster and more reliable than GUI interaction."
        )
    return ""


def inspect_foreground() -> dict[str, str | int | bool]:
    try:
        snapshot = capture_ax_snapshot("foreground")
    except AXPermissionRequiredError:
        return {
            "app_name": "",
            "window_title": "",
            "app_id": "",
            "interactive_estimate": 0,
            "needs_permission": True,
            "recommendation": "Grant macOS Accessibility permission, then call desktop_snapshot_tool.",
        }
    except AXTreeEmptyError as exc:
        app_name, window_title, app_id = _read_foreground_meta()
        base_rec = _SNAPSHOT_RECOMMENDATION_BASE
        if app_name:
            native_hint = _native_api_hint(app_name)
            return {
                "app_name": app_name,
                "window_title": window_title,
                "app_id": app_id,
                "interactive_estimate": 0,
                "needs_permission": False,
                "recommendation": f"{base_rec} AX tree had no interactive nodes ({exc}).{native_hint} Use desktop_vision_tool for canvas/custom-rendered UI.",
            }
        return {
            "app_name": "",
            "window_title": "",
            "app_id": "",
            "interactive_estimate": 0,
            "needs_permission": False,
            "recommendation": f"AX tree unavailable ({exc}). Use desktop_vision_tool fallback.",
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


def refs_for_view_update(
    refs: dict[str, ElementRef],
    *,
    viewport_width: int,
    viewport_height: int,
    som_index_map: dict[str, int] | None = None,
) -> dict[str, dict[str, object]]:
    payload: dict[str, dict[str, object]] = {}
    for ref_id, element in refs.items():
        nth: int | None = None
        if som_index_map is not None:
            nth = som_index_map.get(ref_id)
        payload[ref_id] = {
            "role": normalize_desktop_role(element.role),
            "name": element.name,
            "nth": nth,
            "bbox": {
                "x": element.bbox.x,
                "y": element.bbox.y,
                "width": element.bbox.width,
                "height": element.bbox.height,
                "centerX": element.bbox.center_x,
                "centerY": element.bbox.center_y,
                "viewport_width": viewport_width,
                "viewport_height": viewport_height,
            },
            "position": None,
        }
    return payload
