"""Unit and regression tests for iPhone Mirroring state probe and safety gates.

Validates:
1. IPhoneMirrorState parsing and probe_iphone_mirror_state diagnostic handling.
2. Window bounds extraction and non-macOS graceful fallback.
3. Safety rules blocking automated clicking of iPhone Mirroring connect/unlock dialogs.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.computer_use.desktop_session import DesktopSession
from myrm_agent_harness.toolkits.computer_use.dref.types import (
    BBox,
    ElementRef,
    SnapshotMeta,
)
from myrm_agent_harness.toolkits.computer_use.iphone_mirror import (
    IPHONE_MIRROR_BUNDLE_ID,
    is_iphone_mirror_app,
    is_iphone_mirror_bundle,
    is_iphone_mirror_connect_window,
    is_iphone_mirror_supported,
    probe_iphone_mirror_state,
)
from myrm_agent_harness.toolkits.computer_use.safety import (
    is_iphone_mirror_blocked_action,
)
from myrm_agent_harness.toolkits.computer_use.types import (
    ActionResult,
    IPhoneMirrorProbeResult,
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


def test_is_iphone_mirror_app_matcher() -> None:
    """Shared matcher: bundle-id authoritative, localized app name fallback."""
    assert is_iphone_mirror_app("iPhone Mirroring") is True
    assert is_iphone_mirror_app("iPhone 镜像") is True
    assert is_iphone_mirror_app("Finder", app_id="com.apple.ScreenContinuity") is True
    assert is_iphone_mirror_app("Finder", app_id="com.apple.finder") is False
    assert is_iphone_mirror_app("") is False


def test_is_iphone_mirror_connect_window() -> None:
    """Connect/unlock keyword detection matches EN and ZH prompts."""
    assert is_iphone_mirror_connect_window("Click Connect to Start") is True
    assert is_iphone_mirror_connect_window("Enter Passcode") is True
    assert is_iphone_mirror_connect_window("连接 iPhone") is True
    assert is_iphone_mirror_connect_window("iPhone (Pursue's iPhone)") is False


def test_probe_iphone_mirror_state_no_window() -> None:
    mock_sub = MagicMock()
    mock_sub.stdout = "NO_WINDOW"
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
        assert "no active visible window" in res.detail


def test_probe_iphone_mirror_state_ready_without_bounds() -> None:
    mock_sub = MagicMock()
    mock_sub.stdout = "WINDOW|iPhone|"
    with (
        patch(
            "myrm_agent_harness.toolkits.computer_use.iphone_mirror.is_iphone_mirror_supported",
            return_value=True,
        ),
        patch("subprocess.run", return_value=mock_sub),
    ):
        res = probe_iphone_mirror_state()
        assert res.state == IPhoneMirrorState.READY
        assert res.window_bounds is None


def test_probe_iphone_mirror_state_malformed_bounds() -> None:
    mock_sub = MagicMock()
    mock_sub.stdout = "WINDOW|iPhone|garbage,not,numbers"
    with (
        patch(
            "myrm_agent_harness.toolkits.computer_use.iphone_mirror.is_iphone_mirror_supported",
            return_value=True,
        ),
        patch("subprocess.run", return_value=mock_sub),
    ):
        res = probe_iphone_mirror_state()
        assert res.state == IPhoneMirrorState.READY
        assert res.window_bounds is None


def test_probe_iphone_mirror_state_unknown_output() -> None:
    mock_sub = MagicMock()
    mock_sub.stdout = "SOMETHING_ELSE"
    with (
        patch(
            "myrm_agent_harness.toolkits.computer_use.iphone_mirror.is_iphone_mirror_supported",
            return_value=True,
        ),
        patch("subprocess.run", return_value=mock_sub),
    ):
        res = probe_iphone_mirror_state()
        assert res.state == IPhoneMirrorState.READY
        assert res.detail == "iPhone Mirroring detected."


def test_probe_iphone_mirror_state_osascript_failure() -> None:
    with (
        patch(
            "myrm_agent_harness.toolkits.computer_use.iphone_mirror.is_iphone_mirror_supported",
            return_value=True,
        ),
        patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=3.0)),
    ):
        res = probe_iphone_mirror_state()
        assert res.state == IPhoneMirrorState.NOT_RUNNING
        assert "Probe failed" in res.detail
        assert "permissions" in res.remedy_hint.lower()


def test_is_iphone_mirror_supported_darwin_paths() -> None:
    with (
        patch.object(sys, "platform", "darwin"),
        patch("platform.mac_ver", return_value=("15.2", ("", "", ""), "")),
    ):
        assert is_iphone_mirror_supported() is True
    with (
        patch.object(sys, "platform", "darwin"),
        patch("platform.mac_ver", return_value=("14.6", ("", "", ""), "")),
    ):
        assert is_iphone_mirror_supported() is False
    with (
        patch.object(sys, "platform", "darwin"),
        patch("platform.mac_ver", return_value=("", ("", "", ""), "")),
    ):
        assert is_iphone_mirror_supported() is False
    with (
        patch.object(sys, "platform", "darwin"),
        patch("platform.mac_ver", side_effect=OSError("broken")),
    ):
        assert is_iphone_mirror_supported() is False


def _make_interact_session() -> DesktopSession:
    """Build a DesktopSession whose interact path reaches the mirror gate."""
    backend = MagicMock()
    config = MagicMock()
    config.screenshot_delay = 0.0
    session = DesktopSession(backend=backend, config=config)
    session._last_snapshot_time = time.time()
    session._refs = MagicMock()
    session._refs.meta = SnapshotMeta(
        ref_count=1,
        app_name="iPhone Mirroring",
        window_title="Click Connect to Start",
        scope="foreground",
        app_id="com.apple.ScreenContinuity",
    )
    session._refs.get.return_value = ElementRef(
        ref_id="d1",
        role="AXButton",
        name="Connect",
        bbox=BBox(10, 10, 100, 40),
        backend_key="k",
    )
    return session


@pytest.mark.asyncio
async def test_desktop_interact_blocks_mirror_connect_click() -> None:
    """Element named 'Connect' inside the mirror app is hard-denied before invoke."""
    session = _make_interact_session()
    with patch(
        "myrm_agent_harness.toolkits.computer_use.desktop_session.invoke_element"
    ) as mock_invoke:
        result = await session.desktop_interact(ref="d1", action="click")
    assert result.startswith("Safety:")
    assert "must NOT automatically click connect" in result
    mock_invoke.assert_not_called()


@pytest.mark.asyncio
async def test_desktop_interact_allows_mirror_normal_click() -> None:
    """Normal in-mirror content clicks proceed to AX invoke."""
    session = _make_interact_session()
    session._refs.meta = replace(
        session._refs.meta, window_title="iPhone (Pursue's iPhone)"
    )
    with patch(
        "myrm_agent_harness.toolkits.computer_use.desktop_session.invoke_element"
    ) as mock_invoke:
        mock_invoke.return_value = ActionResult(success=True)
        with patch.object(session, "desktop_snapshot", new=AsyncMock(return_value="view")):
            result = await session.desktop_interact(ref="d1", action="click")
    assert "succeeded" in result
    mock_invoke.assert_called_once()


@pytest.mark.asyncio
async def test_desktop_vision_blocked_when_connect_prompt_active() -> None:
    """Vision coordinate actions are denied while the connect prompt is frontmost."""
    probe_result = IPhoneMirrorProbeResult(
        state=IPhoneMirrorState.BLOCKED_CONNECT_PROMPT,
        is_supported=True,
        detail="iPhone Mirroring requires user action",
        remedy_hint="User must confirm",
    )
    with (
        patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.inspect_backend",
            return_value={
                "app_name": "iPhone Mirroring",
                "window_title": "Connect",
                "app_id": "com.apple.ScreenContinuity",
            },
        ),
        patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.probe_iphone_mirror_state",
            return_value=probe_result,
        ),
        patch.object(DesktopSession, "click_at", new_callable=AsyncMock) as mock_click,
    ):
        session = DesktopSession(backend=MagicMock(), config=MagicMock())
        result = await session.desktop_vision_action(action="left_click", coordinate=[10, 10])
    assert result.startswith("Safety:")
    assert "User must confirm" in result
    mock_click.assert_not_called()


@pytest.mark.asyncio
async def test_desktop_snapshot_appends_mirror_gate_banner() -> None:
    """Snapshot against the mirror app during a connect prompt appends gate info."""
    probe_result = IPhoneMirrorProbeResult(
        state=IPhoneMirrorState.BLOCKED_CONNECT_PROMPT,
        is_supported=True,
        detail="iPhone Mirroring requires user action: Connect",
        remedy_hint="[REMEDY_HINT: unlock on device]",
    )
    meta = SnapshotMeta(
        ref_count=1,
        app_name="iPhone Mirroring",
        window_title="Click Connect to Start",
        scope="foreground",
        app_id="com.apple.ScreenContinuity",
    )
    refs = {
        "d1": ElementRef(
            ref_id="d1",
            role="AXButton",
            name="Connect",
            bbox=BBox(0, 0, 10, 10),
            backend_key="k",
        )
    }
    with (
        patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.capture_snapshot",
            return_value=(meta, refs),
        ),
        patch(
            "myrm_agent_harness.toolkits.computer_use.desktop_session.probe_iphone_mirror_state",
            return_value=probe_result,
        ),
    ):
        session = DesktopSession(backend=MagicMock(), config=MagicMock())
        session._emit_view_update = AsyncMock()
        result = await session.desktop_snapshot()
    assert "[IPHONE_MIRROR_GATE]" in result
    assert "REMEDY_HINT" in result
