"""Tests for the desktop permission error contract.

An ungranted Accessibility permission is recoverable within the same turn: the failure must read
as retryable and must tell the agent not to end the turn, so a first-run permission prompt does
not discard the user's original request.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.computer_use.dref.errors import AXPermissionRequiredError


def test_message_is_explicitly_retryable() -> None:
    """The agent must know the condition can be resolved by calling the tool again."""
    message = str(AXPermissionRequiredError("macOS"))

    assert "call this tool again" in message
    assert "retryable" in message


def test_message_forbids_ending_the_turn() -> None:
    """Without this the agent reports failure and the user has to restate the whole request."""
    message = str(AXPermissionRequiredError("macOS"))

    assert "do NOT end the turn" in message
    assert "start over" in message


def test_message_includes_settings_deeplink_when_known() -> None:
    """A concrete Settings URL is actionable; a vague 'System Settings' is not."""
    message = str(AXPermissionRequiredError("macOS", "x-apple.systempreferences:Privacy_Accessibility"))

    assert "x-apple.systempreferences:Privacy_Accessibility" in message
    assert "System Settings" in message


def test_message_falls_back_when_no_deeplink() -> None:
    """Platforms without a deep link must still produce an actionable retry instruction."""
    message = str(AXPermissionRequiredError("Linux"))

    assert "System Settings" in message
    assert "call this tool again" in message
    # The retry contract must not depend on the deep link being available.
    assert "do NOT end the turn" in message
