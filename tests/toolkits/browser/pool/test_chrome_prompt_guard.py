from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.browser.pool.chrome_prompt_guard import (
    _poll_and_approve,
    _try_approve_dialog_applescript,
    approve_chrome_remote_debugging_prompt,
    is_accessibility_trusted,
    watch_chrome_remote_debugging_prompt,
)


@pytest.mark.asyncio
async def test_watch_prompt_short_circuits_immediately_on_exit():
    """Verify that exiting the context manager cancels the background polling task."""
    with patch("sys.platform", "darwin"):
        with patch(
            "myrm_agent_harness.toolkits.browser.pool.chrome_prompt_guard._try_approve_dialog_applescript",
            return_value="none",
        ):
            async with watch_chrome_remote_debugging_prompt(timeout=2.0, interval=0.05):
                await asyncio.sleep(0.01)

    # Context exited without hanging or lingering errors


@pytest.mark.asyncio
async def test_watch_prompt_bypasses_on_non_darwin():
    """Verify non-macOS platforms immediately pass through without polling."""
    with patch("sys.platform", "linux"):
        with patch(
            "myrm_agent_harness.toolkits.browser.pool.chrome_prompt_guard._poll_and_approve"
        ) as mock_poll:
            async with watch_chrome_remote_debugging_prompt(timeout=2.0):
                pass
            mock_poll.assert_not_called()


@pytest.mark.asyncio
async def test_poll_and_approve_stops_on_clicked_dialog():
    """Verify polling breaks early when a button click is reported."""
    stop_event = asyncio.Event()

    with patch(
        "myrm_agent_harness.toolkits.browser.pool.chrome_prompt_guard.approve_chrome_remote_debugging_prompt",
        side_effect=[False, True],
    ) as mock_approve:
        await _poll_and_approve(stop_event, timeout=2.0, interval=0.01)
        assert mock_approve.call_count == 2


def test_approve_chrome_remote_debugging_prompt_darwin():
    """Verify approve_chrome_remote_debugging_prompt parses clicked status."""
    with patch("platform.system", return_value="Darwin"):
        with patch(
            "myrm_agent_harness.toolkits.browser.pool.chrome_prompt_guard._try_approve_dialog_applescript",
            return_value="clicked:允许",
        ):
            assert approve_chrome_remote_debugging_prompt() is True

        with patch(
            "myrm_agent_harness.toolkits.browser.pool.chrome_prompt_guard._try_approve_dialog_applescript",
            return_value="none",
        ):
            assert approve_chrome_remote_debugging_prompt() is False


def test_approve_chrome_remote_debugging_prompt_non_darwin():
    """Verify approve_chrome_remote_debugging_prompt returns False on non-Darwin."""
    with patch("platform.system", return_value="Linux"):
        assert approve_chrome_remote_debugging_prompt() is False


def test_try_approve_dialog_suppresses_os_errors():
    """Verify AppleScript subprocess execution errors are safely captured."""
    with patch("subprocess.run", side_effect=OSError("osascript not found")):
        status = _try_approve_dialog_applescript()
        assert status.startswith("error:")


def test_is_accessibility_trusted():
    """Verify is_accessibility_trusted returns True on non-Darwin and handles exceptions."""
    with patch("platform.system", return_value="Linux"):
        assert is_accessibility_trusted() is True

    with patch("platform.system", return_value="Darwin"):
        with patch("ctypes.cdll.LoadLibrary", side_effect=Exception("mock ctypes failure")):
            assert is_accessibility_trusted() is False
