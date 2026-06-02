"""Unit tests for session state management."""

from unittest.mock import AsyncMock, Mock

import pytest

from myrm_agent_harness.toolkits.browser.checkpoint.session_state import (
    _build_localstorage_script,
    apply_storage_state,
    get_browser_state,
    restore_browser_state,
)


class TestGetBrowserState:
    """Test get_browser_state function."""

    @pytest.mark.asyncio
    async def test_extract_current_url_no_vault(self):
        """Test extracting current URL without SessionVault."""
        # Mock BrowserSession with active tab
        session = Mock()
        session.list_tabs.return_value = ["tab-1"]

        mock_page = Mock()
        mock_page.url = "https://example.com/test"

        tab_controller = Mock()
        tab_controller.get_active_page.return_value = mock_page
        session._tab_controller = tab_controller

        result = await get_browser_state(session, session_vault=None)

        assert result["current_url"] == "https://example.com/test"
        assert "session_domain" not in result
        assert "session_hash" not in result

    @pytest.mark.asyncio
    async def test_extract_with_vault_uses_cached_hash(self):
        """Test extracting state with SessionVault uses cached hash."""
        session = Mock()
        session.list_tabs.return_value = ["tab-1"]

        mock_page = Mock()
        mock_page.url = "https://example.com/page"

        tab_controller = Mock()
        tab_controller.get_active_page.return_value = mock_page
        session._tab_controller = tab_controller

        session.get_session_hash = Mock(return_value="cached-hash-abc")

        vault = Mock()

        result = await get_browser_state(session, session_vault=vault)

        assert result["current_url"] == "https://example.com/page"
        assert result["session_domain"] == "example.com"
        assert result["session_hash"] == "cached-hash-abc"
        session.get_session_hash.assert_called_once_with("example.com")

    @pytest.mark.asyncio
    async def test_no_tabs_returns_empty(self):
        """Test that empty tab list returns empty state."""
        session = Mock()
        session.list_tabs.return_value = []

        result = await get_browser_state(session, session_vault=None)

        assert result == {}

    @pytest.mark.asyncio
    async def test_get_page_exception_handled(self):
        """Test that exceptions in get_active_page are handled gracefully."""
        session = Mock()
        session.list_tabs.return_value = ["tab-1"]

        tab_controller = Mock()
        tab_controller.get_active_page.side_effect = RuntimeError("Tab closed")
        session._tab_controller = tab_controller

        result = await get_browser_state(session, session_vault=None)

        assert result == {}


class TestRestoreBrowserState:
    """Test restore_browser_state function."""

    @pytest.mark.asyncio
    async def test_restore_with_vault_and_url(self):
        """Test restoring state with SessionVault and URL navigation."""
        session = Mock()
        session.new_tab = AsyncMock()
        session.snapshot = AsyncMock()

        mock_context = Mock()
        mock_context.add_cookies = AsyncMock()
        mock_context.add_init_script = AsyncMock()
        session._context = mock_context

        vault = Mock()
        mock_entry = Mock(storage_state={"cookies": [{"name": "token", "value": "abc"}]})
        vault.load = AsyncMock(return_value=mock_entry)

        metadata = {
            "session_domain": "example.com",
            "current_url": "https://example.com/restored",
        }

        result = await restore_browser_state(session, metadata, vault)

        assert result is True
        vault.load.assert_called_once_with("example.com")
        mock_context.add_cookies.assert_called_once()
        session.new_tab.assert_called_once_with("https://example.com/restored")
        session.snapshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_no_vault(self):
        """Test restoring without SessionVault (URL only)."""
        session = Mock()
        session.new_tab = AsyncMock()
        session.snapshot = AsyncMock()

        metadata = {"current_url": "https://example.com/page"}

        result = await restore_browser_state(session, metadata, session_vault=None)

        assert result is True
        session.new_tab.assert_called_once_with("https://example.com/page")
        session.snapshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_vault_not_found(self):
        """Test restoring when vault entry doesn't exist."""
        session = Mock()
        session.new_tab = AsyncMock()
        session.snapshot = AsyncMock()

        vault = Mock()
        vault.load = AsyncMock(return_value=None)

        metadata = {
            "session_domain": "example.com",
            "current_url": "https://example.com/page",
        }

        result = await restore_browser_state(session, metadata, vault)

        assert result is True
        vault.load.assert_called_once_with("example.com")
        session.new_tab.assert_called_once()

    @pytest.mark.asyncio
    async def test_restore_exception_returns_false(self):
        """Test that exceptions during restore return False."""
        session = Mock()
        session.new_tab = AsyncMock(side_effect=RuntimeError("Navigation failed"))
        session.snapshot = AsyncMock()

        metadata = {"current_url": "https://example.com/page"}

        result = await restore_browser_state(session, metadata, session_vault=None)

        assert result is False


class TestApplyStorageState:
    """Test apply_storage_state function."""

    @pytest.mark.asyncio
    async def test_apply_cookies_and_localstorage(self):
        """Test applying both cookies and localStorage."""
        session = Mock()
        mock_context = Mock()
        mock_context.add_cookies = AsyncMock()
        mock_context.add_init_script = AsyncMock()
        session._context = mock_context

        storage_state = {
            "cookies": [
                {"name": "session_id", "value": "xyz123", "domain": "example.com"},
            ],
            "origins": [
                {
                    "origin": "https://example.com",
                    "localStorage": [
                        {"name": "user_pref", "value": "dark"},
                        {"name": "token", "value": "abc"},
                    ],
                }
            ],
        }

        await apply_storage_state(session, storage_state)

        mock_context.add_cookies.assert_called_once_with(storage_state["cookies"])
        assert mock_context.add_init_script.call_count == 1

    @pytest.mark.asyncio
    async def test_apply_cookies_only(self):
        """Test applying cookies only (no localStorage)."""
        session = Mock()
        mock_context = Mock()
        mock_context.add_cookies = AsyncMock()
        mock_context.add_init_script = AsyncMock()
        session._context = mock_context

        storage_state = {
            "cookies": [{"name": "token", "value": "xyz"}],
        }

        await apply_storage_state(session, storage_state, apply_localstorage=False)

        mock_context.add_cookies.assert_called_once()
        mock_context.add_init_script.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_localstorage_only(self):
        """Test applying localStorage only (no cookies)."""
        session = Mock()
        mock_context = Mock()
        mock_context.add_cookies = AsyncMock()
        mock_context.add_init_script = AsyncMock()
        session._context = mock_context

        storage_state = {
            "origins": [
                {
                    "origin": "https://test.com",
                    "localStorage": [{"name": "key1", "value": "val1"}],
                }
            ],
        }

        await apply_storage_state(session, storage_state, apply_cookies=False)

        mock_context.add_cookies.assert_not_called()
        mock_context.add_init_script.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_context_raises_error(self):
        """Test that missing context raises RuntimeError."""
        session = Mock()
        session._context = None

        storage_state = {"cookies": []}

        with pytest.raises(RuntimeError, match="BrowserContext not available"):
            await apply_storage_state(session, storage_state)

    @pytest.mark.asyncio
    async def test_skip_origins_without_origin_field(self):
        """Test that origins without 'origin' field are skipped."""
        session = Mock()
        mock_context = Mock()
        mock_context.add_cookies = AsyncMock()
        mock_context.add_init_script = AsyncMock()
        session._context = mock_context

        storage_state = {
            "origins": [
                {"localStorage": [{"name": "key", "value": "val"}]},  # No origin
            ],
        }

        await apply_storage_state(session, storage_state)

        mock_context.add_init_script.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_origins_without_localstorage(self):
        """Test that origins without localStorage are skipped."""
        session = Mock()
        mock_context = Mock()
        mock_context.add_cookies = AsyncMock()
        mock_context.add_init_script = AsyncMock()
        session._context = mock_context

        storage_state = {
            "origins": [{"origin": "https://test.com"}],  # No localStorage
        }

        await apply_storage_state(session, storage_state)

        mock_context.add_init_script.assert_not_called()

    @pytest.mark.asyncio
    async def test_localstorage_exception_logged(self):
        """Test that exceptions in add_init_script are logged."""
        session = Mock()
        mock_context = Mock()
        mock_context.add_cookies = AsyncMock()
        mock_context.add_init_script = AsyncMock(side_effect=RuntimeError("Script failed"))
        session._context = mock_context

        storage_state = {
            "origins": [
                {
                    "origin": "https://test.com",
                    "localStorage": [{"name": "key", "value": "val"}],
                }
            ],
        }

        # Should not raise (exception is logged)
        await apply_storage_state(session, storage_state, apply_cookies=False)

        mock_context.add_init_script.assert_called_once()


class TestBuildLocalstorageScript:
    """Test _build_localstorage_script helper."""

    def test_build_single_item(self):
        """Test building script for single item."""
        items = [{"name": "key1", "value": "value1"}]

        script = _build_localstorage_script(items)

        assert script == 'localStorage.setItem("key1", "value1");'

    def test_build_multiple_items(self):
        """Test building script for multiple items."""
        items = [
            {"name": "key1", "value": "val1"},
            {"name": "key2", "value": "val2"},
        ]

        script = _build_localstorage_script(items)

        expected = 'localStorage.setItem("key1", "val1");\nlocalStorage.setItem("key2", "val2");'
        assert script == expected

    def test_escape_special_characters(self):
        """Test escaping quotes and backslashes."""
        items = [{"name": 'key"with"quotes', "value": "val\\with\\backslash"}]

        script = _build_localstorage_script(items)

        assert 'key\\"with\\"quotes' in script
        assert "val\\\\with\\\\backslash" in script

    def test_skip_items_without_name(self):
        """Test that items without name are skipped."""
        items = [
            {"name": "key1", "value": "val1"},
            {"value": "val2"},  # No name
        ]

        script = _build_localstorage_script(items)

        assert script == 'localStorage.setItem("key1", "val1");'
