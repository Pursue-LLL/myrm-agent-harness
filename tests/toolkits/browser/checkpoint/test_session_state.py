"""Unit tests for session state management."""

from unittest.mock import AsyncMock, Mock

import pytest

from myrm_agent_harness.toolkits.browser.checkpoint.session_state import (
    _build_localstorage_script,
    apply_storage_state,
    get_browser_state,
    normalize_cookies,
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

        mock_context.add_cookies.assert_called_once()
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

    def test_without_origin_produces_iife(self):
        """Test building script without origin guard."""
        items = [{"name": "key1", "value": "value1"}]

        script = _build_localstorage_script(items)

        assert script.startswith("(() => {")
        assert "JSON.parse(" in script
        assert "localStorage.setItem" in script
        assert "window.location.origin" not in script

    def test_with_origin_produces_guarded_iife(self):
        """Test building script with origin guard."""
        items = [{"name": "key1", "value": "val1"}]

        script = _build_localstorage_script(items, origin="https://example.com")

        assert "window.location.origin === " in script
        assert '"https://example.com"' in script
        assert "JSON.parse(" in script
        assert "localStorage.setItem" in script

    def test_special_characters_safely_serialised(self):
        """Test that special characters are safely serialised via JSON."""
        items = [{"name": 'key"with"quotes', "value": "val\\with\\backslash"}]

        script = _build_localstorage_script(items, origin="https://evil.com'; alert(1);//")

        assert "alert(1)" not in script or "JSON.parse" in script
        assert "localStorage.setItem" in script

    def test_empty_items_produces_valid_js(self):
        """Test that empty items list produces valid JS."""
        script = _build_localstorage_script([], origin="https://example.com")

        assert "JSON.parse(" in script
        assert script.startswith("(() => {")


class TestNormalizeCookies:
    """Test normalize_cookies function."""

    def test_removes_expires_zero(self):
        """Session cookies with expires=0 should have expires removed."""
        cookies = [{"name": "sid", "value": "abc", "expires": 0}]
        result = normalize_cookies(cookies)

        assert "expires" not in result[0]
        assert result[0]["name"] == "sid"

    def test_removes_expires_negative(self):
        """Session cookies with expires=-1 should have expires removed."""
        cookies = [{"name": "sid", "value": "abc", "expires": -1}]
        result = normalize_cookies(cookies)

        assert "expires" not in result[0]

    def test_removes_expires_negative_float(self):
        """Session cookies with expires=-1.0 should have expires removed."""
        cookies = [{"name": "sid", "value": "abc", "expires": -1.0}]
        result = normalize_cookies(cookies)

        assert "expires" not in result[0]

    def test_preserves_valid_expires(self):
        """Persistent cookies with valid expires should be preserved."""
        cookies = [{"name": "sid", "value": "abc", "expires": 1722700000}]
        result = normalize_cookies(cookies)

        assert result[0]["expires"] == 1722700000

    def test_normalises_samesite_lowercase(self):
        """sameSite should be normalized to Title Case."""
        cookies = [
            {"name": "a", "value": "1", "sameSite": "none"},
            {"name": "b", "value": "2", "sameSite": "lax"},
            {"name": "c", "value": "3", "sameSite": "strict"},
        ]
        result = normalize_cookies(cookies)

        assert result[0]["sameSite"] == "None"
        assert result[1]["sameSite"] == "Lax"
        assert result[2]["sameSite"] == "Strict"

    def test_preserves_already_correct_samesite(self):
        """Already correct sameSite should be preserved."""
        cookies = [{"name": "a", "value": "1", "sameSite": "Lax"}]
        result = normalize_cookies(cookies)

        assert result[0]["sameSite"] == "Lax"

    def test_does_not_modify_original(self):
        """normalize_cookies should not modify the original list."""
        original = [{"name": "sid", "value": "abc", "expires": 0, "sameSite": "none"}]
        normalize_cookies(original)

        assert original[0]["expires"] == 0
        assert original[0]["sameSite"] == "none"

    def test_empty_list(self):
        """Empty list should return empty list."""
        assert normalize_cookies([]) == []

    def test_cookie_without_expires_or_samesite(self):
        """Cookies without expires or sameSite should pass through unchanged."""
        cookies = [{"name": "sid", "value": "abc", "domain": ".example.com"}]
        result = normalize_cookies(cookies)

        assert result[0] == {"name": "sid", "value": "abc", "domain": ".example.com"}
