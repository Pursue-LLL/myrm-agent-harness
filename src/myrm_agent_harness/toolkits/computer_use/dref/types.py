"""Element reference types for desktop semantic control (@dref).

[INPUT]
- (none)

[OUTPUT]
- SnapshotScope, INTERACTIVE_AX_ROLES, BBox, ElementRef, SnapshotMeta

[POS]
Core @dref value types for semantic desktop control in computer_use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NamedTuple

SnapshotScope = Literal["foreground", "target"]

# Platform roles that denote a secure input. Their value must NEVER be read into an event
# stream: macOS surfaces a password field as an ordinary text field through AppleScript, so
# the role is the only reliable signal that the content is a secret. Windows exposes the same
# distinction as ``IsPassword`` on the UIA element; both surface through this role contract.
SECURE_OVERLAY_ROLE = "secure_text_field"

_SECURE_ROLE_ALIASES: frozenset[str] = frozenset(
    {
        "AXSecureTextField",
        "SecureTextField",
        "PasswordBox",
        "password",
        "passwordbox",
        "secure_text_field",
    }
)


def is_secure_role(role: str | None) -> bool:
    """Whether an element role denotes a password/secure field that must not be recorded."""
    if not role:
        return False
    return role in _SECURE_ROLE_ALIASES or role.lower() in _SECURE_ROLE_ALIASES


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
        "AXSecureTextField",
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
    app_id: str = ""
    pid: int = 0
    truncated: bool = False
    needs_permission: bool = False
    token_estimate: int = 0
