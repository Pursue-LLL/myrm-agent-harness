"""Unit tests for BrowserSession user-initiated takeover hard stop and resume policy."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession


@pytest.fixture
def mock_session() -> BrowserSession:
    """Create a minimal BrowserSession with mocked internal components."""
    with patch("myrm_agent_harness.toolkits.browser.session.browser_session.TabController"), \
         patch("myrm_agent_harness.toolkits.browser.session.browser_session.Navigator"), \
         patch("myrm_agent_harness.toolkits.browser.session.browser_session.SnapshotManager"), \
         patch("myrm_agent_harness.toolkits.browser.session.browser_session.Interactor") as mock_interactor_cls:
        mock_pool = MagicMock()
        mock_ctx_type = MagicMock()
        session = BrowserSession(browser_pool=mock_pool, context_type=mock_ctx_type)
        session._tab_controller = MagicMock()
        mock_page = MagicMock()
        mock_page.locator.return_value = MagicMock()
        session._tab_controller.get_active_page.return_value = mock_page
        session._interactor = MagicMock()
        session._interactor.interact = AsyncMock(return_value="interaction_done")
        session._snapshot_manager = MagicMock()
        session.snapshot = AsyncMock(return_value=MagicMock())
        session._publish_inspector_view = AsyncMock()
        session._ensure_components = AsyncMock()
        return session


@pytest.mark.asyncio
async def test_session_takeover_initial_state(mock_session: BrowserSession) -> None:
    assert mock_session.user_takeover_active is False
    assert mock_session._user_takeover_event.is_set() is True


@pytest.mark.asyncio
async def test_session_pause_and_resume_flow(mock_session: BrowserSession) -> None:
    # 1. Pause
    await mock_session.pause_for_takeover()
    assert mock_session.user_takeover_active is True
    assert mock_session._user_takeover_event.is_set() is False

    # 2. Resume
    await mock_session.resume_from_takeover()
    assert mock_session.user_takeover_active is False
    assert mock_session._user_takeover_event.is_set() is True
    # Verify snapshot refresh was triggered
    mock_session.snapshot.assert_awaited_once_with(force=True)


@pytest.mark.asyncio
async def test_interact_blocks_during_takeover_until_resumed(mock_session: BrowserSession) -> None:
    await mock_session.pause_for_takeover()

    interact_task = asyncio.create_task(mock_session.interact(action="click", ref="ref_123"))

    # Give event loop a cycle; task should be pending
    await asyncio.sleep(0.05)
    assert not interact_task.done()
    mock_session._interactor.interact.assert_not_called()

    # User finishes takeover and resumes
    await mock_session.resume_from_takeover()
    result = await asyncio.wait_for(interact_task, timeout=2.0)

    assert result == "interaction_done"
    mock_session._interactor.interact.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_not_user_takeover_timeout_unblocks(mock_session: BrowserSession) -> None:
    await mock_session.pause_for_takeover()
    assert mock_session._user_takeover_event.is_set() is False

    # With very small timeout (0.1s), it should auto-unblock and log warning
    await mock_session._ensure_not_user_takeover(timeout=0.1)
    assert mock_session.user_takeover_active is False
    assert mock_session._user_takeover_event.is_set() is True
