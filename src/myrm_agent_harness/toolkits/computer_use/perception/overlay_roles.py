"""Cross-platform desktop overlay role normalization.

Maps raw AX/UIA/AT-SPI role strings to a stable overlay vocabulary shared by
SOM labeling, SSE view updates, and the WebUI ElementOverlay.

[INPUT]
- dref.types::ElementRef, INTERACTIVE_AX_ROLES (POS: @dref element metadata)

[OUTPUT]
- normalize_desktop_role(): AX role → overlay role string
- is_interactive_for_overlay(): whether an element receives SOM [N] labels

[POS]
Platform-neutral role SSOT for desktop Inspector and SOM overlays.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.computer_use.dref.types import INTERACTIVE_AX_ROLES, ElementRef

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

INTERACTIVE_OVERLAY_ROLES: frozenset[str] = frozenset(
    {
        "button",
        "link",
        "textbox",
        "checkbox",
        "radio",
        "combobox",
        "menuitem",
        "tab",
        "switch",
        "slider",
        "spinbutton",
        "searchbox",
        "option",
        "listbox",
        "clickable",
        "focusable",
    }
)

_GENERIC_OVERLAY_FALLBACK_ROLES: frozenset[str] = frozenset({"clickable", "focusable"})


def normalize_desktop_role(role: str) -> str:
    mapped = _AX_ROLE_TO_OVERLAY_ROLE.get(role)
    if mapped:
        return mapped
    return "clickable"


def is_interactive_for_overlay(element: ElementRef) -> bool:
    if element.role in INTERACTIVE_AX_ROLES:
        return True
    normalized = normalize_desktop_role(element.role)
    return normalized in INTERACTIVE_OVERLAY_ROLES and normalized not in _GENERIC_OVERLAY_FALLBACK_ROLES
