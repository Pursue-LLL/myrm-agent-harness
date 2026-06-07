"""Tests for automatic domain-based tab routing.

Tests cover:
1. TabController.find_tab_by_origin()
2. TabController.list_tabs_with_info()
3. BrowserSession.new_tab() origin-based reuse logic
4. manage.py new_tab/list_tabs action output
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType
from myrm_agent_harness.toolkits.browser.session.tab_controller import TabController, TabHandle


class FakePage:
    """Minimal fake Page for testing URL-based logic."""

    def __init__(self, url: str = "about:blank"):
        self._url = url
        self.bring_to_front = AsyncMock()

    @property
    def url(self) -> str:
        return self._url


def _make_tab_handle(tab_id: str, url: str) -> TabHandle:
    """Create a TabHandle with a fake page at the given URL."""
    page = FakePage(url)
    return TabHandle(page=page, tab_id=tab_id, context_key="ctx0")


class TestFindTabByOrigin:
    """Tests for TabController.find_tab_by_origin()."""

    def _create_controller_with_tabs(self, tabs: dict[str, str]) -> TabController:
        """Create a TabController pre-populated with tabs {tab_id: url}."""
        pool = MagicMock()
        ctrl = TabController(pool, ContextType.AGENT)
        for tab_id, url in tabs.items():
            handle = _make_tab_handle(tab_id, url)
            ctrl._tabs[tab_id] = handle
            ctrl._active_tab_id = tab_id
        return ctrl

    def test_finds_matching_origin(self):
        ctrl = self._create_controller_with_tabs({
            "tab0": "https://www.google.com/search?q=test",
            "tab1": "https://github.com/user/repo",
        })

        result = ctrl.find_tab_by_origin("https://www.google.com")
        assert result is not None
        assert result.tab_id == "tab0"

    def test_returns_none_when_no_match(self):
        ctrl = self._create_controller_with_tabs({
            "tab0": "https://www.google.com/search",
        })

        result = ctrl.find_tab_by_origin("https://github.com")
        assert result is None

    def test_skips_blank_tabs(self):
        ctrl = self._create_controller_with_tabs({
            "tab0": "about:blank",
            "tab1": "https://example.com/page",
        })

        result = ctrl.find_tab_by_origin("https://example.com")
        assert result is not None
        assert result.tab_id == "tab1"

    def test_skips_empty_url_tabs(self):
        ctrl = self._create_controller_with_tabs({
            "tab0": "",
            "tab1": "https://github.com/repo",
        })

        result = ctrl.find_tab_by_origin("https://github.com")
        assert result is not None
        assert result.tab_id == "tab1"

    def test_all_blank_tabs_returns_none(self):
        ctrl = self._create_controller_with_tabs({
            "tab0": "about:blank",
            "tab1": "",
        })

        result = ctrl.find_tab_by_origin("https://example.com")
        assert result is None

    def test_different_port_is_different_origin(self):
        ctrl = self._create_controller_with_tabs({
            "tab0": "http://localhost:3000/page",
        })

        result = ctrl.find_tab_by_origin("http://localhost:8080")
        assert result is None

    def test_same_port_matches(self):
        ctrl = self._create_controller_with_tabs({
            "tab0": "http://localhost:3000/api/data",
        })

        result = ctrl.find_tab_by_origin("http://localhost:3000")
        assert result is not None
        assert result.tab_id == "tab0"

    def test_http_vs_https_is_different_origin(self):
        ctrl = self._create_controller_with_tabs({
            "tab0": "http://example.com/page",
        })

        result = ctrl.find_tab_by_origin("https://example.com")
        assert result is None

    def test_handles_page_url_exception_gracefully(self):
        """If page.url raises, the tab should be skipped."""
        pool = MagicMock()
        ctrl = TabController(pool, ContextType.AGENT)

        broken_page = MagicMock()
        type(broken_page).url = property(lambda self: (_ for _ in ()).throw(RuntimeError("page closed")))
        handle = TabHandle(page=broken_page, tab_id="tab0", context_key="ctx0")
        ctrl._tabs["tab0"] = handle

        good_handle = _make_tab_handle("tab1", "https://example.com/path")
        ctrl._tabs["tab1"] = good_handle

        result = ctrl.find_tab_by_origin("https://example.com")
        assert result is not None
        assert result.tab_id == "tab1"

    def test_returns_first_match_when_multiple_tabs_share_origin(self):
        ctrl = self._create_controller_with_tabs({
            "tab0": "https://github.com/userA/repo1",
            "tab1": "https://github.com/userB/repo2",
        })

        result = ctrl.find_tab_by_origin("https://github.com")
        assert result is not None
        assert result.tab_id == "tab0"


class TestListTabsWithInfo:
    """Tests for TabController.list_tabs_with_info()."""

    def test_empty_tabs(self):
        pool = MagicMock()
        ctrl = TabController(pool, ContextType.AGENT)

        result = ctrl.list_tabs_with_info()
        assert result == []

    def test_basic_info(self):
        pool = MagicMock()
        ctrl = TabController(pool, ContextType.AGENT)
        ctrl._tabs["tab0"] = _make_tab_handle("tab0", "https://www.google.com/search")
        ctrl._tabs["tab1"] = _make_tab_handle("tab1", "https://github.com/user")
        ctrl._active_tab_id = "tab0"

        result = ctrl.list_tabs_with_info()
        assert len(result) == 2

        tab0_info = next(i for i in result if i["tab_id"] == "tab0")
        assert tab0_info["domain"] == "www.google.com"
        assert tab0_info["active"] is True

        tab1_info = next(i for i in result if i["tab_id"] == "tab1")
        assert tab1_info["domain"] == "github.com"
        assert tab1_info["active"] is False

    def test_blank_tab_shows_blank(self):
        pool = MagicMock()
        ctrl = TabController(pool, ContextType.AGENT)
        ctrl._tabs["tab0"] = _make_tab_handle("tab0", "about:blank")
        ctrl._active_tab_id = "tab0"

        result = ctrl.list_tabs_with_info()
        assert result[0]["domain"] == "(blank)"

    def test_broken_page_shows_unavailable(self):
        pool = MagicMock()
        ctrl = TabController(pool, ContextType.AGENT)

        broken_page = MagicMock()
        type(broken_page).url = property(lambda self: (_ for _ in ()).throw(RuntimeError("dead")))
        ctrl._tabs["tab0"] = TabHandle(page=broken_page, tab_id="tab0", context_key="ctx0")
        ctrl._active_tab_id = "tab0"

        result = ctrl.list_tabs_with_info()
        assert result[0]["domain"] == "(unavailable)"


class TestBrowserSessionNewTabReuse:
    """Tests for BrowserSession.new_tab() origin-based reuse logic."""

    @pytest.fixture
    def mock_session(self):
        """Create a BrowserSession with mocked components."""
        from myrm_agent_harness.toolkits.browser.session import BrowserSession

        pool = MagicMock()
        pool.get_or_create_context = AsyncMock()
        session = BrowserSession(browser_pool=pool, context_type=ContextType.AGENT)

        mock_tab_ctrl = MagicMock()
        mock_tab_ctrl.list_tabs = Mock(return_value=["tab0"])
        mock_tab_ctrl.get_active_page = Mock(return_value=FakePage("https://google.com/search"))
        mock_tab_ctrl.get_active_tab_id = Mock(return_value="tab0")
        mock_tab_ctrl.get_snapshot_url = Mock(return_value=None)
        mock_tab_ctrl.switch_tab = AsyncMock()
        mock_tab_ctrl.create_tab = AsyncMock(return_value="tab1")
        session._tab_controller = mock_tab_ctrl

        session._initialize_components = AsyncMock()
        session.navigate = AsyncMock(return_value="Navigated")

        return session

    @pytest.mark.asyncio
    async def test_reuses_existing_tab_for_same_origin(self, mock_session):
        existing_handle = _make_tab_handle("tab0", "https://google.com/search")
        mock_session._tab_controller.find_tab_by_origin = Mock(return_value=existing_handle)

        result = await mock_session.new_tab("https://google.com/maps")

        assert result == "tab0"
        mock_session._tab_controller.switch_tab.assert_awaited_once_with("tab0")
        mock_session._initialize_components.assert_awaited()
        mock_session.navigate.assert_awaited_once_with("https://google.com/maps")
        mock_session._tab_controller.create_tab.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_creates_new_tab_when_no_match(self, mock_session):
        mock_session._tab_controller.find_tab_by_origin = Mock(return_value=None)

        result = await mock_session.new_tab("https://github.com/user")

        assert result == "tab1"
        mock_session._tab_controller.create_tab.assert_awaited_once()
        mock_session._initialize_components.assert_awaited()
        mock_session.navigate.assert_awaited_once_with("https://github.com/user")

    @pytest.mark.asyncio
    async def test_creates_new_tab_when_url_is_none(self, mock_session):
        mock_session._tab_controller.find_tab_by_origin = Mock(return_value=None)

        result = await mock_session.new_tab(None)

        assert result == "tab1"
        mock_session._tab_controller.create_tab.assert_awaited_once()
        mock_session.navigate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_creates_new_tab_when_url_is_empty(self, mock_session):
        result = await mock_session.new_tab("")

        assert result == "tab1"
        mock_session._tab_controller.create_tab.assert_awaited_once()


class TestManageToolTabActions:
    """Tests for manage.py new_tab and list_tabs action outputs."""

    @pytest.mark.asyncio
    async def test_new_tab_reports_reuse(self):
        """When a tab is reused, the action returns a reuse message."""
        from myrm_agent_harness.toolkits.browser.tools.manage import create_manage_tool

        session = MagicMock()
        session.list_tabs = Mock(return_value=["tab0"])
        session.new_tab = AsyncMock(return_value="tab0")
        session.list_tabs_with_info = Mock(return_value=[
            {"tab_id": "tab0", "domain": "google.com", "active": True},
        ])

        tool_fn = create_manage_tool(session)
        result = await tool_fn.ainvoke({"action": "new_tab", "value": "https://google.com/maps"})

        assert "Reused existing tab0" in result
        assert "google.com" in result
        assert "same origin" in result

    @pytest.mark.asyncio
    async def test_new_tab_reports_creation(self):
        """When a new tab is created, the action returns creation message."""
        from myrm_agent_harness.toolkits.browser.tools.manage import create_manage_tool

        session = MagicMock()
        session.list_tabs = Mock(return_value=["tab0"])
        session.new_tab = AsyncMock(return_value="tab1")

        tool_fn = create_manage_tool(session)
        result = await tool_fn.ainvoke({"action": "new_tab", "value": "https://github.com"})

        assert "New tab created: tab1" in result

    @pytest.mark.asyncio
    async def test_list_tabs_shows_domain_info(self):
        """list_tabs action shows domain and active state for each tab."""
        from myrm_agent_harness.toolkits.browser.tools.manage import create_manage_tool

        session = MagicMock()
        session.list_tabs_with_info = Mock(return_value=[
            {"tab_id": "tab0", "domain": "google.com", "active": True},
            {"tab_id": "tab1", "domain": "github.com", "active": False},
        ])

        tool_fn = create_manage_tool(session)
        result = await tool_fn.ainvoke({"action": "list_tabs", "value": ""})

        assert "tab0: google.com [active]" in result
        assert "tab1: github.com" in result
        assert "[active]" not in result.split("tab1")[1]

    @pytest.mark.asyncio
    async def test_list_tabs_empty(self):
        """list_tabs returns 'No open tabs' when empty."""
        from myrm_agent_harness.toolkits.browser.tools.manage import create_manage_tool

        session = MagicMock()
        session.list_tabs_with_info = Mock(return_value=[])

        tool_fn = create_manage_tool(session)
        result = await tool_fn.ainvoke({"action": "list_tabs", "value": ""})

        assert result == "No open tabs"
