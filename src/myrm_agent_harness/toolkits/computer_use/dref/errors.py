"""Typed errors for semantic desktop element references.

[INPUT]
- (none)

[OUTPUT]
- ElementRefError, DRefStaleError, AXPermissionRequiredError, AXTreeEmptyError

[POS]
Typed error hierarchy for @dref desktop element reference operations.
"""

from __future__ import annotations

# Accessibility permission guidance lives with the error that needs it, so raisers (which already
# import this module) do not have to reach into the platform backend for a Settings URL.
ACCESSIBILITY_SETTINGS_DEEPLINK = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
)


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
    """Raised when OS accessibility permissions are missing.

    An ungranted permission is recoverable: the user can grant it while the turn is still open.
    The message therefore states that the call is retryable and explicitly tells the agent not to
    end the turn, so a first-run permission prompt does not discard the user's original request.
    """

    def __init__(self, platform: str, settings_deeplink: str = "") -> None:
        grant_hint = (
            f"Grant access via {settings_deeplink} (or System Settings), "
            if settings_deeplink
            else "Grant access in System Settings, "
        )
        super().__init__(
            f"Accessibility permission required on {platform}. "
            f"{grant_hint}then call this tool again. "
            "This is a retryable condition, not a failure: do NOT end the turn or ask the user to "
            "start over. Wait for them to grant access, then retry the same call. "
            "Use desktop_vision_tool as explicit visual fallback if needed."
        )


class AXTreeEmptyError(ElementRefError):
    """Raised when no interactive AX nodes are available."""

    def __init__(self, reason: str = "") -> None:
        suffix = f" ({reason})" if reason else ""
        super().__init__(f"Accessibility tree is empty{suffix}. Use desktop_vision_tool for canvas/custom-rendered UI.")
