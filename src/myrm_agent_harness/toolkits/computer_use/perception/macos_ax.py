"""macOS accessibility tree capture and invoke via AppleScript."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from myrm_agent_harness.toolkits.computer_use.types import ActionResult
from myrm_agent_harness.toolkits.computer_use.dref.errors import AXPermissionRequiredError, AXTreeEmptyError
from myrm_agent_harness.toolkits.computer_use.dref.types import (
    INTERACTIVE_AX_ROLES,
    BBox,
    ElementRef,
    SnapshotMeta,
    SnapshotScope,
)

logger = logging.getLogger(__name__)

_MAX_ELEMENTS = 500

_AX_SNAPSHOT_SCRIPT = (
    """
on serializeElement(idx, elemRole, elemName, elemValue, posX, posY, sizeW, sizeH)
    set safeName to my escapeText(elemName)
    set safeValue to my escapeText(elemValue)
    return idx & "|||" & elemRole & "|||" & safeName & "|||" & safeValue & "|||" & posX & "|||" & posY & "|||" & sizeW & "|||" & sizeH
end serializeElement

on escapeText(t)
    if t is missing value then return ""
    set s to t as string
    set s to my replaceText(s, "\\", "\\\\")
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
    set frontApp to first application process whose frontmost is true
    set appName to name of frontApp
    set winTitle to ""
    try
        set winTitle to name of window 1 of frontApp
    end try

    set lines to {}
    set end of lines to appName & "|||META|||" & winTitle

    try
        set uiElements to entire contents of window 1 of frontApp
        set maxElements to count of uiElements
        if maxElements > """
    + str(_MAX_ELEMENTS)
    + """ then set maxElements to """
    + str(_MAX_ELEMENTS)
    + """
        repeat with i from 1 to maxElements
            set elem to item i of uiElements
            try
                set elemRole to role of elem
                if elemRole is in {"AXButton", "AXCheckBox", "AXComboBox", "AXLink", "AXMenuItem", "AXPopUpButton", "AXRadioButton", "AXSlider", "AXTabGroup", "AXTextField", "AXTextArea", "AXStaticText"} then
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
                    if elemName is not "" or elemValue is not "" or elemRole is in {"AXButton", "AXCheckBox", "AXTextField", "AXTextArea", "AXPopUpButton", "AXRadioButton"} then
                        set elemPos to position of elem
                        set elemSize to size of elem
                        set end of lines to my serializeElement(i, elemRole, elemName, elemValue, item 1 of elemPos, item 2 of elemPos, item 1 of elemSize, item 2 of elemSize)
                    end if
                end if
            end try
        end repeat
    end try

    set AppleScript's text item delimiters to linefeed
    return lines as string
end tell
"""
)


@dataclass(frozen=True)
class MacAxSnapshot:
    meta: SnapshotMeta
    refs: dict[str, ElementRef]


def capture_ax_snapshot(scope: SnapshotScope, window_title: str | None = None) -> MacAxSnapshot:
    del scope, window_title  # foreground-only for v1; scope reserved for follow-up
    try:
        result = subprocess.run(
            ["osascript", "-e", _AX_SNAPSHOT_SCRIPT],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired as exc:
        raise AXTreeEmptyError("macOS AX snapshot timed out") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "不允许辅助访问" in stderr or "not allowed assistive" in stderr.lower():
            raise AXPermissionRequiredError("macOS")
        raise AXTreeEmptyError(stderr or "AppleScript AX snapshot failed")

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise AXTreeEmptyError("no AX output")

    meta_line = lines[0].split("|||")
    app_name = meta_line[0] if meta_line else ""
    window_name = meta_line[2] if len(meta_line) > 2 else ""

    refs: dict[str, ElementRef] = {}
    ref_index = 0
    truncated = len(lines) - 1 >= _MAX_ELEMENTS
    for line in lines[1:]:
        parts = line.split("|||")
        if len(parts) < 8:
            continue
        backend_index, role, name, value, x_s, y_s, w_s, h_s = parts[:8]
        if role not in INTERACTIVE_AX_ROLES and role not in {
            "AXButton",
            "AXCheckBox",
            "AXComboBox",
            "AXLink",
            "AXMenuItem",
            "AXPopUpButton",
            "AXRadioButton",
            "AXSlider",
            "AXTabGroup",
            "AXTextField",
            "AXTextArea",
            "AXStaticText",
        }:
            continue
        try:
            bbox = BBox(int(float(x_s)), int(float(y_s)), int(float(w_s)), int(float(h_s)))
        except ValueError:
            continue
        if bbox.width <= 0 or bbox.height <= 0:
            continue
        ref_id = f"d{ref_index}"
        actions = ("click", "fill") if role in {"AXTextField", "AXTextArea"} else ("click",)
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
        scope="foreground",
        truncated=truncated,
    )
    return MacAxSnapshot(meta=meta, refs=refs)


_AX_INVOKE_SCRIPT = """
on escapeText(t)
    if t is missing value then return ""
    set s to t as string
    set s to my replaceText(s, "\\", "\\\\")
    set s to my replaceText(s, "\"", "\\\"")
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
        set frontApp to first application process whose frontmost is true
        set uiElements to entire contents of window 1 of frontApp
        set elem to item elemIndex of uiElements
        if actionName is "fill" then
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


def invoke_ax_element(backend_key: str, action: str, text: str = "") -> ActionResult:
    normalized_action = action.lower()
    if normalized_action in {"dblclick", "double_click"}:
        normalized_action = "click"
    if normalized_action not in {"click", "fill", "press", "focus", "hover"}:
        return ActionResult(success=False, error=f"Unsupported AX action: {action}")

    ax_action = "fill" if normalized_action in {"fill", "type"} else "click"
    try:
        result = subprocess.run(
            ["osascript", "-e", _AX_INVOKE_SCRIPT, ax_action, backend_key, text],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return ActionResult(success=False, error="AX invoke timed out")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "不允许辅助访问" in stderr or "not allowed assistive" in stderr.lower():
            return ActionResult(success=False, error="Accessibility permission required on macOS")
        return ActionResult(success=False, error=stderr or "AX invoke failed")

    if result.stdout.strip() != "OK":
        return ActionResult(success=False, error=result.stdout.strip() or "AX invoke failed")
    return ActionResult(success=True, output=f"AX {ax_action} succeeded")


_SCRIPTABLE_APPS: frozenset[str] = frozenset({
    "Finder", "Mail", "Safari", "Notes", "Reminders", "Calendar", "Messages",
    "Preview", "Music", "TV", "Podcasts", "Photos", "Keynote", "Pages",
    "Numbers", "TextEdit", "Terminal", "Script Editor", "System Settings",
    "System Preferences", "Automator", "Shortcuts", "Microsoft Excel",
    "Microsoft Word", "Microsoft PowerPoint", "Microsoft Outlook",
    "Google Chrome", "Slack", "Spotify", "iTerm2", "iTerm",
    "Adobe Photoshop", "Adobe Illustrator", "Adobe Acrobat", "Adobe InDesign",
    "Sketch", "Final Cut Pro", "Logic Pro", "GarageBand", "Xcode",
    "WPS Office", "Firefox", "Arc", "Obsidian", "Discord",
    "Visual Studio Code", "Cursor", "OmniGraffle", "DEVONthink", "Affinity Designer",
})


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
            "interactive_estimate": 0,
            "needs_permission": True,
            "recommendation": "Grant macOS Accessibility permission, then call desktop_snapshot_tool.",
        }
    except AXTreeEmptyError as exc:
        return {
            "app_name": "",
            "window_title": "",
            "interactive_estimate": 0,
            "needs_permission": False,
            "recommendation": f"AX tree unavailable ({exc}). Use desktop_vision_tool fallback.",
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


_AX_ROLE_TO_OVERLAY_ROLE: dict[str, str] = {
    "AXButton": "button",
    "Button": "button",
    "ButtonControl": "button",
    "AXTextField": "textbox",
    "AXTextArea": "textbox",
    "EditControl": "textbox",
    "AXCheckBox": "checkbox",
    "CheckBox": "checkbox",
    "CheckBoxControl": "checkbox",
    "AXLink": "link",
    "HyperlinkControl": "link",
    "AXComboBox": "combobox",
    "ComboBox": "combobox",
    "ComboBoxControl": "combobox",
    "AXMenuItem": "menuitem",
    "MenuItemControl": "menuitem",
    "AXRadioButton": "radio",
    "RadioButtonControl": "radio",
    "AXSlider": "slider",
    "AXPopUpButton": "combobox",
    "AXTabGroup": "tab",
    "TabItemControl": "tab",
    "ListItemControl": "option",
}


def normalize_desktop_role(role: str) -> str:
    mapped = _AX_ROLE_TO_OVERLAY_ROLE.get(role)
    if mapped:
        return mapped
    return "clickable"


def refs_for_view_update(
    refs: dict[str, ElementRef],
    *,
    viewport_width: int,
    viewport_height: int,
) -> dict[str, dict[str, object]]:
    payload: dict[str, dict[str, object]] = {}
    for ref_id, element in refs.items():
        payload[ref_id] = {
            "role": normalize_desktop_role(element.role),
            "name": element.name,
            "nth": None,
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
