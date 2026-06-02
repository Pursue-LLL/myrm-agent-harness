"""Unit tests for browser checkpoint context integration."""

from unittest.mock import Mock, patch

import pytest

from myrm_agent_harness.toolkits.browser.checkpoint.context_integration import (
    BrowserCheckpointHelper,
    create_browser_context_updater,
)


class TestBrowserCheckpointHelper:
    """Test BrowserCheckpointHelper."""

    @pytest.fixture
    def mock_session(self):
        """Create mock BrowserSession."""
        return Mock()

    def test_initialization(self, mock_session):
        """Test helper initialization."""
        helper = BrowserCheckpointHelper(mock_session, session_vault=None)

        assert helper._session is mock_session
        assert helper._vault is None
        assert helper._counters == {
            "snapshots": 0,
            "interactions": 0,
            "navigations": 0,
        }

    def test_increment_counter(self, mock_session):
        """Test counter incrementation."""
        helper = BrowserCheckpointHelper(mock_session)

        helper.increment_counter("snapshots")
        helper.increment_counter("snapshots")
        helper.increment_counter("interactions")

        assert helper._counters["snapshots"] == 2
        assert helper._counters["interactions"] == 1
        assert helper._counters["navigations"] == 0

    def test_increment_unknown_counter(self, mock_session):
        """Test that unknown counter names are ignored."""
        helper = BrowserCheckpointHelper(mock_session)

        helper.increment_counter("unknown")

        assert "unknown" not in helper._counters

    def test_get_initial_context(self, mock_session):
        """Test getting initial context."""
        helper = BrowserCheckpointHelper(mock_session)
        helper._counters["snapshots"] = 5

        context = helper.get_initial_context()

        assert context == {
            "browser_checkpoint": {
                "enabled": True,
                "counters": {
                    "snapshots": 5,
                    "interactions": 0,
                    "navigations": 0,
                },
            }
        }

    @pytest.mark.asyncio
    async def test_get_browser_metadata(self, mock_session):
        """Test getting browser metadata."""
        helper = BrowserCheckpointHelper(mock_session)
        helper._counters["interactions"] = 10

        mock_state = {
            "current_url": "https://test.com",
            "session_domain": "test.com",
        }

        with patch(
            "myrm_agent_harness.toolkits.browser.checkpoint.session_state.get_browser_state",
            return_value=mock_state,
        ) as mock_get:
            metadata = await helper.get_browser_metadata()

        assert metadata["current_url"] == "https://test.com"
        assert metadata["session_domain"] == "test.com"
        assert metadata["task_counters"]["interactions"] == 10
        mock_get.assert_called_once_with(mock_session, helper._vault)

    @pytest.mark.asyncio
    async def test_update_context_creates_browser_checkpoint(self, mock_session):
        """Test updating context creates browser_checkpoint if missing."""
        helper = BrowserCheckpointHelper(mock_session)

        mock_state = {"current_url": "https://test.com"}

        with patch(
            "myrm_agent_harness.toolkits.browser.checkpoint.session_state.get_browser_state",
            return_value=mock_state,
        ):
            context: dict = {}
            await helper.update_context(context)

        assert "browser_checkpoint" in context
        assert context["browser_checkpoint"]["current_url"] == "https://test.com"

    @pytest.mark.asyncio
    async def test_update_context_merges_with_existing(self, mock_session):
        """Test updating context merges with existing browser_checkpoint."""
        helper = BrowserCheckpointHelper(mock_session)

        mock_state = {"current_url": "https://new.com"}

        with patch(
            "myrm_agent_harness.toolkits.browser.checkpoint.session_state.get_browser_state",
            return_value=mock_state,
        ):
            context = {"browser_checkpoint": {"enabled": True, "old_key": "value"}}
            await helper.update_context(context)

        assert context["browser_checkpoint"]["enabled"] is True
        assert context["browser_checkpoint"]["old_key"] == "value"
        assert context["browser_checkpoint"]["current_url"] == "https://new.com"


class TestCreateBrowserContextUpdater:
    """Test create_browser_context_updater factory."""

    @pytest.mark.asyncio
    async def test_factory_creates_callable(self):
        """Test that factory creates async callable."""
        mock_session = Mock()
        mock_vault = Mock()

        updater = create_browser_context_updater(mock_session, mock_vault)

        assert callable(updater)

    @pytest.mark.asyncio
    async def test_updater_updates_context(self):
        """Test that returned updater correctly updates context."""
        mock_session = Mock()
        mock_state = {
            "current_url": "https://example.com",
            "session_domain": "example.com",
        }

        with patch(
            "myrm_agent_harness.toolkits.browser.checkpoint.session_state.get_browser_state",
            return_value=mock_state,
        ):
            updater = create_browser_context_updater(mock_session, session_vault=None)
            context: dict = {}
            await updater(context)

        assert "browser_checkpoint" in context
        assert context["browser_checkpoint"]["current_url"] == "https://example.com"
