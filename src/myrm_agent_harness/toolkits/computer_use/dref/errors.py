"""Typed errors for semantic desktop element references."""

from __future__ import annotations


class ElementRefError(Exception):
    """Base error for element reference operations."""


class DRefStaleError(ElementRefError):
    """Raised when a @dref no longer matches the current UI tree."""

    def __init__(self, ref_id: str, message: str | None = None) -> None:
        self.ref_id = ref_id
        detail = message or (
            f"Element ref '{ref_id}' is stale or invalid. "
            "Call desktop_snapshot_tool again before desktop_interact_tool."
        )
        super().__init__(detail)


class AXPermissionRequiredError(ElementRefError):
    """Raised when OS accessibility permissions are missing."""

    def __init__(self, platform: str) -> None:
        super().__init__(
            f"Accessibility permission required on {platform}. "
            "Grant access in System Settings, then retry desktop_snapshot_tool. "
            "Use desktop_vision_tool as explicit visual fallback if needed."
        )


class AXTreeEmptyError(ElementRefError):
    """Raised when no interactive AX nodes are available."""

    def __init__(self, reason: str = "") -> None:
        suffix = f" ({reason})" if reason else ""
        super().__init__(f"Accessibility tree is empty{suffix}. Use desktop_vision_tool for canvas/custom-rendered UI.")
