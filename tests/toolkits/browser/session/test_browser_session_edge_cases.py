"""Edge case tests for BrowserSession.

Tests error handling, observability integration, and boundary conditions.
"""

from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType
from myrm_agent_harness.toolkits.browser.session import BrowserSession


@pytest.fixture
def mock_browser_pool():
    """Create mock browser pool."""
    pool = MagicMock()
    pool.get_or_create_context = AsyncMock()
    return pool


@pytest.fixture
def mock_observability():
    """Create mock observability."""
    obs = MagicMock()
    obs.get_context_kwargs = Mock(return_value={"record_video": True})
    obs.notify_progress = AsyncMock()
    obs.mark_task_status = Mock()
    return obs


class TestBrowserSessionEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_init_with_observability(self, mock_browser_pool, mock_observability):
        """Test initialization with observability."""
        session = BrowserSession(
            browser_pool=mock_browser_pool, context_type=ContextType.AGENT, observability=mock_observability
        )

        mock_observability.get_context_kwargs.assert_called_once()
        assert session._observability == mock_observability

    @pytest.mark.asyncio
    async def test_get_ref_info_no_interactor(self, mock_browser_pool):
        """Test get_ref_info when interactor is None."""
        session = BrowserSession(browser_pool=mock_browser_pool, context_type=ContextType.AGENT)

        result = session.get_ref_info("ref123")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_refs_no_interactor(self, mock_browser_pool):
        """Test get_all_refs when interactor is None."""
        session = BrowserSession(browser_pool=mock_browser_pool, context_type=ContextType.AGENT)

        result = session.get_all_refs()

        assert isinstance(result, MappingProxyType)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_save_session_invalid_domain(self, mock_browser_pool):
        """Test save_session with invalid domain name."""
        mock_vault = MagicMock()
        session = BrowserSession(
            browser_pool=mock_browser_pool, context_type=ContextType.AGENT, session_vault=mock_vault
        )

        result = await session.save_session("../invalid")

        assert "Error: Invalid domain name" in result
        assert "../invalid" in result

    @pytest.mark.asyncio
    async def test_restore_session_invalid_domain(self, mock_browser_pool):
        """Test restore_session with invalid domain name."""
        mock_vault = MagicMock()
        session = BrowserSession(
            browser_pool=mock_browser_pool, context_type=ContextType.AGENT, session_vault=mock_vault
        )

        result = await session.restore_session("/etc/passwd")

        assert "Error: Invalid domain name" in result
        assert "/etc/passwd" in result

    @pytest.mark.asyncio
    async def test_notify_progress_with_observability(self, mock_browser_pool, mock_observability):
        """Test notify_progress calls observability."""
        session = BrowserSession(
            browser_pool=mock_browser_pool, context_type=ContextType.AGENT, observability=mock_observability
        )

        await session.notify_progress("Step 1/3: Loading page")

        mock_observability.notify_progress.assert_called_once_with("Step 1/3: Loading page")

    @pytest.mark.asyncio
    async def test_notify_progress_no_observability(self, mock_browser_pool):
        """Test notify_progress without observability."""
        session = BrowserSession(browser_pool=mock_browser_pool, context_type=ContextType.AGENT)

        await session.notify_progress("Step 1/3: Loading page")

    @pytest.mark.asyncio
    async def test_get_final_screenshot_no_tabs(self, mock_browser_pool):
        """Test get_final_screenshot raises error when no tabs."""
        session = BrowserSession(browser_pool=mock_browser_pool, context_type=ContextType.AGENT)

        session._tab_controller = MagicMock()
        session._tab_controller.list_tabs = Mock(return_value=[])

        with pytest.raises(RuntimeError, match="Cannot capture screenshot: no active tabs"):
            await session.get_final_screenshot()

    @pytest.mark.asyncio
    async def test_get_final_screenshot_success(self, mock_browser_pool):
        """Test get_final_screenshot returns screenshot bytes."""
        session = BrowserSession(browser_pool=mock_browser_pool, context_type=ContextType.AGENT)

        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock(return_value=b"screenshot_data")

        session._tab_controller = MagicMock()
        session._tab_controller.list_tabs = Mock(return_value=[{"id": 1}])
        session._tab_controller.get_active_page = Mock(return_value=mock_page)

        result = await session.get_final_screenshot()

        assert result == b"screenshot_data"
        # 忽略 mask 参数，因为它可能是动态生成的 locator
        mock_page.screenshot.assert_called_once()
        call_kwargs = mock_page.screenshot.call_args.kwargs
        assert call_kwargs.get("type") == "png"
        assert call_kwargs.get("full_page") is False

    def test_mark_task_success_with_observability(self, mock_browser_pool, mock_observability):
        """Test mark_task_success calls observability."""
        session = BrowserSession(
            browser_pool=mock_browser_pool, context_type=ContextType.AGENT, observability=mock_observability
        )

        session.mark_task_success()

        mock_observability.mark_task_status.assert_called_once_with(success=True)

    def test_mark_task_success_no_observability(self, mock_browser_pool):
        """Test mark_task_success without observability."""
        session = BrowserSession(browser_pool=mock_browser_pool, context_type=ContextType.AGENT)

        session.mark_task_success()

    def test_mark_task_failure_with_observability(self, mock_browser_pool, mock_observability):
        """Test mark_task_failure calls observability."""
        session = BrowserSession(
            browser_pool=mock_browser_pool, context_type=ContextType.AGENT, observability=mock_observability
        )

        session.mark_task_failure()

        mock_observability.mark_task_status.assert_called_once_with(success=False)

    def test_mark_task_failure_no_observability(self, mock_browser_pool):
        """Test mark_task_failure without observability."""
        session = BrowserSession(browser_pool=mock_browser_pool, context_type=ContextType.AGENT)

        session.mark_task_failure()
