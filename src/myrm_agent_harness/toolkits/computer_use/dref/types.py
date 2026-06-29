"""Element reference types for desktop semantic control (@dref)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NamedTuple

SnapshotScope = Literal["foreground", "window_title", "full_screen"]

INTERACTIVE_AX_ROLES: frozenset[str] = frozenset(
    {
        "AXButton",
        "AXCheckBox",
        "AXComboBox",
        "AXDisclosureTriangle",
        "AXLink",
        "AXMenuItem",
        "AXPopUpButton",
        "AXRadioButton",
        "AXSlider",
        "AXTabGroup",
        "AXTextField",
        "AXTextArea",
        "Button",
        "CheckBox",
        "ComboBox",
        "EditControl",
        "HyperlinkControl",
        "ListItemControl",
        "MenuItemControl",
        "RadioButtonControl",
        "TabItemControl",
    }
)


class BBox(NamedTuple):
    """Screen-space bounding box in logical pixels."""

    x: int
    y: int
    width: int
    height: int

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2


@dataclass(frozen=True)
class ElementRef:
    """Metadata for a desktop @dref entry."""

    ref_id: str
    role: str
    name: str
    bbox: BBox
    backend_key: str
    actions: tuple[str, ...] = ("click",)
    value: str = ""


@dataclass(frozen=True)
class SnapshotMeta:
    """Metadata for a desktop snapshot."""

    ref_count: int
    app_name: str
    window_title: str
    scope: SnapshotScope
    truncated: bool = False
    needs_permission: bool = False
    token_estimate: int = 0
