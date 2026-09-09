"""Unit and regression tests for iPhone Mirroring state probe and safety gates.

Validates:
1. IPhoneMirrorState parsing and probe_iphone_mirror_state diagnostic handling.
2. Window bounds extraction and non-macOS graceful fallback.
3. Safety rules blocking automated clicking of iPhone Mirroring connect/unlock dialogs.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from myrm_agent_harness.toolkits.computer_use.iphone_mirror import (
    IPHONE_MIRROR_BUNDLE_ID,
    is_iphone_mirror_bundle,
    is_iphone_mirror_supported,
    probe_iphone_mirror_state,
)
from myrm_agent_harness.toolkits.computer_use.safety import (
    is_iphone_mirror_blocked_action,
)
from myrm_agent_harness.toolkits.computer_use.types import (
    IPhoneMirrorState,
)


def test_is_iphone_mirror_bundle() -> None:
    assert is_iphone_mirror_bundle("com.apple.ScreenContinuity") is True
    assert is_iphone_mirror_bundle("COM.APPLE.SCREENCONTINUITY") is True
    assert is_iphone_mirror_bundle("com.apple.finder") is False


def test_is_iphone_mirror_supported_non_darwin() -> None:
    with patch.object(sys, "platform", "linux"):
        assert is_iphone_mirror_supported() is False


def test_probe_iphone_mirror_state_not_supported() -> None:
    with patch(
        "myrm_agent_harness.toolkits.computer_use.iphone_mirror.is_iphone_mirror_supported",
        return_value=False,
    ):
        res = probe_iphone_mirror_state()
        assert res.state == IPhoneMirrorState.NOT_SUPPORTED
        assert res.is_supported is False
        assert "requires macOS Sequoia" in res.detail


def test_probe_iphone_mirror_state_not_running() -> None:
    mock_sub = MagicMock()
    mock_sub.stdout = "NOT_RUNNING"
    with (
        patch(
            "myrm_agent_harness.toolkits.computer_use.iphone_mirror.is_iphone_mirror_supported",
            return_value=True,
        ),
        patch("subprocess.run", return_value=mock_sub),
    ):
        res = probe_iphone_mirror_state()
        assert res.state == IPhoneMirrorState.NOT_RUNNING
        assert res.is_supported is True
        assert "not running" in res.detail.lower()


def test_probe_iphone_mirror_state_blocked_connect() -> None:
    mock_sub = MagicMock()
    mock_sub.stdout = "WINDOW|iPhone Locked - Click Connect to start|100,200,400,800"
    with (
        patch(
            "myrm_agent_harness.toolkits.computer_use.iphone_mirror.is_iphone_mirror_supported",
            return_value=True,
        ),
        patch("subprocess.run", return_value=mock_sub),
    ):
        res = probe_iphone_mirror_state()
        assert res.state == IPhoneMirrorState.BLOCKED_CONNECT_PROMPT
        assert res.window_bounds == (100, 200, 400, 800)
        assert "REMEDY_HINT" in res.remedy_hint


def test_probe_iphone_mirror_state_ready() -> None:
    mock_sub = MagicMock()
    mock_sub.stdout = "WINDOW|iPhone (Pursue's iPhone)|150,250,420,880"
    with (
        patch(
            "myrm_agent_harness.toolkits.computer_use.iphone_mirror.is_iphone_mirror_supported",
            return_value=True,
        ),
        patch("subprocess.run", return_value=mock_sub),
    ):
        res = probe_iphone_mirror_state()
        assert res.state == IPhoneMirrorState.READY
        assert res.window_bounds == (150, 250, 420, 880)
        assert "active" in res.detail.lower()


def test_is_iphone_mirror_blocked_action() -> None:
    # 1. Block connect click when window is in connect prompt state
    blocked = is_iphone_mirror_blocked_action(
        app_name="iPhone Mirroring",
        window_title="Click Connect to Start",
        app_id="com.apple.ScreenContinuity",
        action_text="Click Connect",
    )
    assert blocked is not None
    assert "must NOT automatically click connect" in blocked

    # 2. Allow normal clicks when title is normal app
    safe = is_iphone_mirror_blocked_action(
        app_name="iPhone Mirroring",
        window_title="WeChat",
        app_id="com.apple.ScreenContinuity",
        action_text="tap message",
    )
    assert safe is None

    # 3. Non-iPhone app is never blocked by this rule
    non_phone = is_iphone_mirror_blocked_action(
        app_name="Finder",
        window_title="Connect to Server",
        app_id="com.apple.finder",
        action_text="Connect",
    )
    assert non_phone is None
