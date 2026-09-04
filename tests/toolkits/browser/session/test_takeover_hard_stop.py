"""Unit tests for user-initiated browser takeover hard-stop and resume policy."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession


@pytest.fixture
def mock_session() -> BrowserSession:
    """Create a BrowserSession with mocked internals for takeover tests."""
    session = object.__new__(BrowserSession)
    session._user_takeover_event = asyncio.Event()
    session._user_takeover_event.set()
    session._user_takeover_active = False
    session.snapshot = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_takeover_initial_state_unblocked(mock_session: BrowserSession) -> None:
    """Verify session starts with user takeover unblocked."""
    assert mock_session.user_takeover_active is False
    assert mock_session._user_takeover_event.is_set() is True
    # Should not raise or block
    await mock_session._ensure_not_user_takeover(timeout=0.1)


@pytest.mark.asyncio
async def test_takeover_pause_blocks_actions(mock_session: BrowserSession) -> None:
    """Verify pause_for_takeover clears the event and blocks awaiting actions."""
    await mock_session.pause_for_takeover()

    assert mock_session.user_takeover_active is True
    assert mock_session._user_takeover_event.is_set() is False

    # Awaiting ensure_not_user_takeover should block and time out if not resumed
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(mock_session._user_takeover_event.wait(), timeout=0.05)


@pytest.mark.asyncio
async def test_takeover_resume_unblocks_and_refreshes_snapshot(
    mock_session: BrowserSession,
) -> None:
    """Verify resume_from_takeover unblocks awaiting actions and refreshes snapshot."""
    await mock_session.pause_for_takeover()

    resumed_event = asyncio.Event()

    async def background_action() -> None:
        await mock_session._ensure_not_user_takeover(timeout=1.0)
        resumed_event.set()

    task = asyncio.create_task(background_action())
    await asyncio.sleep(0.02)
    assert resumed_event.is_set() is False

    # Resume from user takeover
    await mock_session.resume_from_takeover()

    await asyncio.wait_for(resumed_event.wait(), timeout=0.5)
    assert resumed_event.is_set() is True
    assert mock_session.user_takeover_active is False
    assert mock_session._user_takeover_event.is_set() is True
    mock_session.snapshot.assert_awaited_once_with(force=True)
    await task


@pytest.mark.asyncio
async def test_takeover_timeout_auto_unblocks(mock_session: BrowserSession) -> None:
    """Verify that exceeding the takeover timeout automatically unblocks the session."""
    await mock_session.pause_for_takeover()
    assert mock_session._user_takeover_event.is_set() is False

    # Wait with short timeout — should auto-recover
    await mock_session._ensure_not_user_takeover(timeout=0.05)

    assert mock_session.user_takeover_active is False
    assert mock_session._user_takeover_event.is_set() is True
