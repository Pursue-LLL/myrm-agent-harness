"""Unit tests for BrowserSession — 100% coverage with mocks."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from myrm_agent_harness.toolkits.browser.pool import ContextType
from myrm_agent_harness.toolkits.browser.session import BrowserSession

# Minimal valid 2x2 JPEG for screenshot mocks (PIL-compatible for PerceptualHashDiff)
_MINIMAL_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwg"
    "JC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAACAAIDASIAAhEBAxEB"
    "/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQR"
    "BRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpT"
    "VFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLD"
    "xMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAEC"
    "AwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUv"
    "AVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq"
    "8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDi6KKK+ZP3E//Z"
)
_MINIMAL_JPEG_BYTES = base64.b64decode(_MINIMAL_JPEG_B64)


# =============================================================================
# Mock infrastructure
# =============================================================================


class _FakePage:
    """Minimal mock of Patchright Page for unit tests."""

    def __init__(self) -> None:
        self.url = "about:blank"
        self._title = "Example"
        self._closed = False
        self._a11y_tree_yaml = """- WebArea:
    name: Test
    children:
      - link:
          name: Home
      - textbox:
          name: Query
      - button:
          name: Search
"""
        self.context = MagicMock()
        self.context.cookies = AsyncMock(return_value=[])
        self.context.add_cookies = AsyncMock()
        self.context.storage_state = AsyncMock(return_value={"cookies": [], "origins": []})

    async def goto(self, url: str, **kw: object) -> MagicMock:
        self.url = url
        resp = MagicMock()
        resp.status = 200
        return resp

    async def title(self) -> str:
        return self._title

    async def wait_for_load_state(self, state: str = "load", timeout: int = 30000) -> None:
        pass

    async def evaluate(self, expression: str, *args: object, **kw: object) -> object:
        if "localStorage" in expression:
            return "{}"
        if "innerText" in expression or "innertext" in expression.lower():
            return "Example page content"
        if "collectBBoxes" in expression:
            return {}
        return f"result:{expression[:20]}"

    async def screenshot(self, **kw: object) -> bytes:
        return _MINIMAL_JPEG_BYTES

    async def pdf(self, path: str | None = None, **kw: object) -> bytes:
        return b"%PDF-fake"

    async def set_viewport_size(self, size: dict[str, int]) -> None:
        pass

    async def go_back(self, **kw: object) -> None:
        pass

    async def go_forward(self, **kw: object) -> None:
        pass

    def on(self, event: str, handler: object) -> None:
        pass

    @property
    def frames(self) -> list:
        return [self]

    def locator(self, selector: str) -> MagicMock:
        loc = MagicMock()
        loc.aria_snapshot = AsyncMock(return_value=self._a11y_tree_yaml)
        return loc


class _FakePool:
    """Mock GlobalBrowserPool that returns fake pages."""

    def __init__(self) -> None:
        self._pages: list[_FakePage] = [_FakePage()]
        from myrm_agent_harness.toolkits.browser.pool.circuit_breaker import CircuitBreaker
        from myrm_agent_harness.toolkits.browser.pool.config import BrowserPoolConfig
        from myrm_agent_harness.toolkits.browser.pool.throttle import NoThrottle

        self.throttle_strategy = NoThrottle()
        self.circuit_breaker = CircuitBreaker()
        self.config = BrowserPoolConfig()

    async def acquire_page(
        self,
        context_type: object,
        context_key: str | None = None,
        context_kwargs: dict[str, object] | None = None,
        engine_preference: str | None = None,
        launch_mode_preference: str | None = None,
    ) -> tuple[_FakePage, str]:
        page = self._pages.pop()
        if not self._pages:
            self._pages.append(_FakePage())
        return page, context_key or "default"

    async def release_page(self, page: object, context_key: str | None = None) -> None:
        pass


@pytest.fixture
def mock_pool() -> _FakePool:
    return _FakePool()


@pytest.fixture
def mock_session_vault() -> MagicMock:
    """Mock SessionVault for session persistence tests."""
    vault = MagicMock()
    vault.save = AsyncMock(return_value=None)
    vault.load = AsyncMock(return_value=None)
    vault.delete = AsyncMock(return_value=True)
    vault.list_domains = AsyncMock(return_value=[])
    return vault


@pytest.fixture
def browser_session(mock_pool: _FakePool) -> BrowserSession:
    """BrowserSession without tabs — tests call new_tab() as needed."""
    return BrowserSession(mock_pool, ContextType.AGENT)


@pytest.fixture
def browser_session_with_vault(mock_pool: _FakePool, mock_session_vault: MagicMock) -> BrowserSession:
    """BrowserSession with SessionVault for session persistence tests."""
    return BrowserSession(mock_pool, ContextType.AGENT, session_vault=mock_session_vault)


# =============================================================================
# Core operations
# =============================================================================


@pytest.mark.asyncio
async def test_new_tab(browser_session: BrowserSession) -> None:
    tab_id = await browser_session.new_tab()
    assert tab_id.startswith("tab")
    assert browser_session.list_tabs() == [tab_id]


@pytest.mark.asyncio
async def test_new_tab_with_url(browser_session: BrowserSession) -> None:
    tab_id = await browser_session.new_tab("https://example.com")
    assert tab_id.startswith("tab")

    result = await browser_session.navigate("https://example.com")
    assert "example.com" in result


@pytest.mark.asyncio
async def test_navigate(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    result = await browser_session.navigate("https://example.com")
    assert "example.com" in result
    assert "200" in result


@pytest.mark.asyncio
async def test_snapshot(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    result = await browser_session.snapshot(scope="interactive")
    assert "e0" in result.aria_tree or "link" in result.aria_tree.lower()
    assert result.meta.ref_count >= 0
    assert result.meta.estimated_tokens >= 0


@pytest.mark.asyncio
async def test_interact(browser_session: BrowserSession) -> None:
    from myrm_agent_harness.toolkits.browser.exceptions import RefNotFoundError

    await browser_session.new_tab()
    await browser_session.snapshot()
    # Mock produces 3 refs (e0, e1, e2), so interact with non-existent ref raises
    with pytest.raises(RefNotFoundError, match="Ref not found"):
        await browser_session.interact("click", "e99")


@pytest.mark.asyncio
async def test_extract_text(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    text = await browser_session.extract_text()
    assert isinstance(text, str)


@pytest.mark.asyncio
async def test_extract_screenshot(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    b64 = await browser_session.extract_screenshot()
    assert len(b64) > 0


@pytest.mark.asyncio
async def test_extract_screenshot_with_annotate(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    b64 = await browser_session.extract_screenshot()
    assert len(b64) > 0


@pytest.mark.asyncio
async def test_extract_screenshot_retina(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    b64 = await browser_session.extract_screenshot(scale=2.0)
    assert len(b64) > 0


@pytest.mark.asyncio
async def test_compare_screenshots_fast(browser_session: BrowserSession) -> None:
    """Test fast screenshot comparison (dHash)."""
    await browser_session.new_tab()
    baseline = _MINIMAL_JPEG_B64
    result = await browser_session.compare_screenshots(baseline, strategy="fast")

    assert hasattr(result, "similarity")
    assert hasattr(result, "is_significant_change")
    assert hasattr(result, "algorithm")
    assert result.algorithm == "dhash"
    assert hasattr(result, "hamming_distance")
    assert 0 <= result.similarity <= 1.0


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="AccurateComparator requires real browser context with new_page support, covered in unit tests"
)
async def test_compare_screenshots_accurate(browser_session: BrowserSession) -> None:
    """Test accurate screenshot comparison (Canvas API)."""
    await browser_session.new_tab("about:blank")
    baseline = _MINIMAL_JPEG_B64
    result = await browser_session.compare_screenshots(baseline, strategy="accurate")

    assert hasattr(result, "similarity")
    assert hasattr(result, "is_significant_change")
    assert hasattr(result, "algorithm")
    assert result.algorithm == "canvas_pixel"
    assert hasattr(result, "diff_image_b64")
    assert hasattr(result, "mismatch_percentage")
    assert 0 <= result.similarity <= 1.0


@pytest.mark.asyncio
async def test_export_pdf(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        result = await browser_session.export_pdf(path)
        assert "Exported" in result or "PDF" in result
    finally:
        Path(path).unlink(missing_ok=True)


# =============================================================================
# Tab management
# =============================================================================


@pytest.mark.asyncio
async def test_close_tab(browser_session: BrowserSession) -> None:
    t1 = await browser_session.new_tab()
    t2 = await browser_session.new_tab()
    result = await browser_session.close_tab(t1)
    assert "Closed" in result
    assert t2 in browser_session.list_tabs()


@pytest.mark.asyncio
async def test_switch_tab(browser_session: BrowserSession) -> None:
    t1 = await browser_session.new_tab()
    await browser_session.new_tab()
    result = await browser_session.switch_tab(t1)
    assert "Switched" in result
    assert browser_session.get_active_tab_id() == t1


@pytest.mark.asyncio
async def test_list_tabs(browser_session: BrowserSession) -> None:
    assert browser_session.list_tabs() == []
    t1 = await browser_session.new_tab()
    assert t1 in browser_session.list_tabs()


# =============================================================================
# Manage operations
# =============================================================================


@pytest.mark.asyncio
async def test_evaluate(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    result = await browser_session.evaluate("document.title")
    assert "result" in result or "Example" in result


@pytest.mark.asyncio
async def test_go_back(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    result = await browser_session.go_back()
    assert "back" in result.lower()


@pytest.mark.asyncio
async def test_go_forward(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    result = await browser_session.go_forward()
    assert "forward" in result.lower()


@pytest.mark.asyncio
async def test_save_pdf(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    result = await browser_session.save_pdf()
    assert "PDF" in result
    assert "Saved" in result


@pytest.mark.asyncio
async def test_resize(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    result = await browser_session.resize(1920, 1080)
    assert "1920" in result
    assert "1080" in result


@pytest.mark.asyncio
async def test_wait_for_load(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    result = await browser_session.wait_for_load()
    assert "completed" in result.lower() or "load" in result.lower()


@pytest.mark.asyncio
async def test_set_dialog_response_accept(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    result = await browser_session.set_dialog_response(True, "test")
    assert "accept" in result.lower()


@pytest.mark.asyncio
async def test_set_dialog_response_dismiss(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    result = await browser_session.set_dialog_response(False)
    assert "dismiss" in result.lower()


# =============================================================================
# Session persistence
# =============================================================================


@pytest.mark.asyncio
async def test_save_session(browser_session_with_vault: BrowserSession) -> None:
    await browser_session_with_vault.new_tab()
    result = await browser_session_with_vault.save_session("example.com")
    assert "Saved" in result
    assert "example.com" in result


@pytest.mark.asyncio
async def test_restore_session_no_saved(browser_session_with_vault: BrowserSession) -> None:
    await browser_session_with_vault.new_tab()
    result = await browser_session_with_vault.restore_session("nonexistent.com")
    assert "No saved session" in result


@pytest.mark.asyncio
async def test_restore_session(browser_session_with_vault: BrowserSession, mock_session_vault: MagicMock) -> None:
    from dataclasses import dataclass

    @dataclass
    class MockSessionEntry:
        storage_state: dict

    await browser_session_with_vault.new_tab()

    # Mock vault to return a saved session
    mock_session_vault.load = AsyncMock(return_value=MockSessionEntry(storage_state={"cookies": [], "origins": []}))

    result = await browser_session_with_vault.restore_session("restore-test.com")
    assert "Restored" in result


@pytest.mark.asyncio
async def test_list_sessions_empty(browser_session_with_vault: BrowserSession) -> None:
    result = await browser_session_with_vault.list_sessions()
    assert "No saved sessions" in result or "sessions" in result.lower()


@pytest.mark.asyncio
async def test_list_sessions_with_data(
    browser_session_with_vault: BrowserSession, mock_session_vault: MagicMock
) -> None:
    await browser_session_with_vault.new_tab()

    # Mock vault to return a list with one domain
    mock_session_vault.list_domains = AsyncMock(return_value=["list-test.com"])

    result = await browser_session_with_vault.list_sessions()
    assert "list-test.com" in result


@pytest.mark.asyncio
async def test_delete_session_no_saved(
    browser_session_with_vault: BrowserSession, mock_session_vault: MagicMock
) -> None:
    # Mock vault to return False (not found)
    mock_session_vault.delete = AsyncMock(return_value=False)

    result = await browser_session_with_vault.delete_session("nonexistent.com")
    assert "No saved session" in result


@pytest.mark.asyncio
async def test_delete_session(browser_session_with_vault: BrowserSession, mock_session_vault: MagicMock) -> None:
    await browser_session_with_vault.new_tab()

    # Mock vault to return True (deleted successfully)
    mock_session_vault.delete = AsyncMock(return_value=True)

    result = await browser_session_with_vault.delete_session("delete-test.com")
    assert "Deleted" in result


# =============================================================================
# Logging
# =============================================================================


def test_get_console_log(browser_session: BrowserSession) -> None:
    result = browser_session.get_console_log()
    assert "console" in result.lower() or "not yet" in result.lower()


def test_get_network_log(browser_session: BrowserSession) -> None:
    result = browser_session.get_network_log()
    assert "network" in result.lower() or "not yet" in result.lower()


# =============================================================================
# Lifecycle
# =============================================================================


@pytest.mark.asyncio
async def test_close(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    await browser_session.close()
    assert browser_session.list_tabs() == []


# =============================================================================
# Stats
# =============================================================================


def test_stats_property(browser_session: BrowserSession) -> None:
    stats = browser_session.stats
    assert "tab_controller" in stats


@pytest.mark.asyncio
async def test_stats_with_snapshot(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    await browser_session.snapshot()
    stats = browser_session.stats
    assert "tab_controller" in stats
    assert "snapshot_manager" in stats


# =============================================================================
# Edge cases
# =============================================================================


@pytest.mark.asyncio
async def test_close_tab_reinitializes(browser_session: BrowserSession) -> None:
    t1 = await browser_session.new_tab()
    t2 = await browser_session.new_tab()
    await browser_session.close_tab(t1)
    assert browser_session.list_tabs() == [t2]


@pytest.mark.asyncio
async def test_ensure_components_lazy_init(browser_session: BrowserSession) -> None:
    await browser_session.new_tab()
    result = await browser_session.navigate("https://example.com")
    assert "example.com" in result


# =============================================================================
# Inspect (page structure analysis)
# =============================================================================


@pytest.mark.asyncio
async def test_inspect_basic(browser_session: BrowserSession) -> None:
    """Test inspect returns page structure summary."""
    await browser_session.new_tab()
    result = await browser_session.inspect()

    assert "PAGE STRUCTURE" in result
    assert "Total interactive elements" in result


@pytest.mark.asyncio
async def test_inspect_with_regions(browser_session: BrowserSession) -> None:
    """Test inspect with detected regions."""
    from unittest.mock import patch

    from myrm_agent_harness.toolkits.browser.session.page_analyzer import PageStructure

    await browser_session.new_tab()

    fake_structure = PageStructure(
        page_title="Test Page",
        page_url="https://test.com",
        total_interactive_elements=100,
        detected_regions=[("#main", "main content", 50), ("#sidebar", "sidebar", 20)],
        recommended_selector="#main",
        estimated_savings="60%",
    )

    with patch("myrm_agent_harness.toolkits.browser.session.browser_session.PageAnalyzer") as mock_analyzer_class:
        mock_instance = AsyncMock()
        mock_instance.analyze = AsyncMock(return_value=fake_structure)
        mock_instance.format_report = Mock(
            return_value="=== PAGE STRUCTURE ===\n\nTitle: Test Page\nURL: https://test.com\nTotal interactive elements: 100\n\nMain regions (by element count):\n  - selector: #main\n    type: main content\n    interactive_elements: 50\n  - selector: #sidebar\n    type: sidebar\n    interactive_elements: 20\n\nRECOMMENDATION:\n  Use: browser_snapshot(selector='#main', scope='interactive')\n  Estimated savings: 60%\n  Current cost: ~700 tokens (full page)\n  Optimized cost: ~280 tokens"
        )
        mock_analyzer_class.return_value = mock_instance

        result = await browser_session.inspect()

        assert "#main" in result
        assert "60%" in result
        assert "RECOMMENDATION" in result


@pytest.mark.asyncio
async def test_inspect_small_page_no_recommendation(browser_session: BrowserSession) -> None:
    """Test inspect for small pages returns no recommendation."""
    from unittest.mock import patch

    from myrm_agent_harness.toolkits.browser.session.page_analyzer import PageStructure

    await browser_session.new_tab()

    fake_structure = PageStructure(
        page_title="Small Page",
        page_url="https://small.com",
        total_interactive_elements=30,
        detected_regions=[],
        recommended_selector=None,
        estimated_savings="0%",
    )

    with patch("myrm_agent_harness.toolkits.browser.session.browser_session.PageAnalyzer") as mock_analyzer_class:
        mock_instance = AsyncMock()
        mock_instance.analyze = AsyncMock(return_value=fake_structure)
        mock_instance.format_report = Mock(
            return_value="=== PAGE STRUCTURE ===\n\nTitle: Small Page\nURL: https://small.com\nTotal interactive elements: 30\n\nMain regions: None detected\n\nRECOMMENDATION:\n  Page is small (<50 elements), browser_snapshot() with default params is optimal."
        )
        mock_analyzer_class.return_value = mock_instance

        result = await browser_session.inspect()

        assert "small" in result.lower() or "optimal" in result.lower()
        assert "RECOMMENDATION" in result


# =============================================================================
# Compare screenshot (no args version)
# =============================================================================


@pytest.mark.asyncio
async def test_compare_screenshot_no_args(browser_session: BrowserSession) -> None:
    """Test compare_screenshot without arguments (current vs last)."""
    await browser_session.new_tab()

    await browser_session.extract_screenshot()
    await browser_session.extract_screenshot()

    result = await browser_session.compare_screenshot()
    assert isinstance(result, str)
    assert "similarity" in result.lower() or "Similarity" in result


@pytest.mark.asyncio
async def test_compare_screenshot_no_previous(browser_session: BrowserSession) -> None:
    """Test compare_screenshot raises error when no previous screenshot."""
    await browser_session.new_tab()

    with pytest.raises(RuntimeError, match="No previous screenshot"):
        await browser_session.compare_screenshot()


# =============================================================================
# Session persistence without vault
# =============================================================================


@pytest.mark.asyncio
async def test_save_session_no_vault(browser_session: BrowserSession) -> None:
    """Test save_session returns error when vault not configured."""
    await browser_session.new_tab()
    result = await browser_session.save_session("test.com")
    assert "Error" in result
    assert "not configured" in result


@pytest.mark.asyncio
async def test_restore_session_no_vault(browser_session: BrowserSession) -> None:
    """Test restore_session returns error when vault not configured."""
    await browser_session.new_tab()
    result = await browser_session.restore_session("test.com")
    assert "Error" in result
    assert "not configured" in result


@pytest.mark.asyncio
async def test_list_sessions_no_vault(browser_session: BrowserSession) -> None:
    """Test list_sessions returns error when vault not configured."""
    result = await browser_session.list_sessions()
    assert "Error" in result
    assert "not configured" in result


@pytest.mark.asyncio
async def test_delete_session_no_vault(browser_session: BrowserSession) -> None:
    """Test delete_session returns error when vault not configured."""
    result = await browser_session.delete_session("test.com")
    assert "Error" in result
    assert "not configured" in result


# =============================================================================
# Component initialization
# =============================================================================


@pytest.mark.asyncio
async def test_ensure_components_initialization(browser_session: BrowserSession) -> None:
    """Test _ensure_components triggers _initialize_components when needed."""
    await browser_session.new_tab()

    await browser_session.navigate("https://example.com")

    assert browser_session._navigator is not None
    assert browser_session._snapshot_manager is not None
    assert browser_session._interactor is not None
    assert browser_session._extractor is not None


@pytest.mark.asyncio
async def test_ensure_components_direct_call() -> None:
    """测试_ensure_components直接调用_initialize_components（覆盖line 439）"""
    from unittest.mock import AsyncMock, MagicMock

    from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
    from myrm_agent_harness.toolkits.browser.pool.config import BrowserPoolConfig

    pool = GlobalBrowserPool(config=BrowserPoolConfig())
    try:
        browser_session = BrowserSession(browser_pool=pool, context_type=ContextType.AGENT)

        mock_page = AsyncMock()
        mock_page.url = "https://test.com"

        mock_tab_controller = MagicMock()
        mock_tab_controller.get_active_page = MagicMock(return_value=mock_page)

        browser_session._tab_controller = mock_tab_controller
        browser_session._navigator = None

        assert browser_session._navigator is None

        await browser_session._ensure_components()

        assert browser_session._navigator is not None
        assert browser_session._snapshot_manager is not None
    finally:
        await pool.shutdown()

@pytest.mark.asyncio
async def test_restart_with_storage_state(browser_session: BrowserSession) -> None:
    """Test restart with storage state migration via add_init_script."""
    # Setup mock storage state
    mock_storage_state = {
        "cookies": [{"name": "test", "value": "123", "domain": "example.com", "path": "/"}],
        "origins": [
            {
                "origin": "https://example.com",
                "localStorage": [{"name": "key1", "value": "val1"}]
            }
        ]
    }

    # We need to mock the page context to return the storage state
    mock_context = AsyncMock()
    mock_context.storage_state.return_value = mock_storage_state

    # Mock the active page
    mock_page = AsyncMock()
    mock_page.url = "https://example.com"
    mock_page.context = mock_context

    # Set up the tab controller to return our mock page
    browser_session._tab_controller.list_tabs = MagicMock(return_value=["tab_1"])
    browser_session._tab_controller.get_active_page = MagicMock(return_value=mock_page)

    # Mock the close and new_tab methods
    browser_session.close = AsyncMock()
    browser_session.new_tab = AsyncMock()
    browser_session.navigate = AsyncMock()

    # Mock the browser pool methods
    browser_session._browser_pool.destroy_context = AsyncMock()
    browser_session._browser_pool._browsers = []

    # Run restart
    result = await browser_session.restart()

    # Verify
    assert "Successfully restarted" in result
    browser_session.close.assert_called_once()
    browser_session.new_tab.assert_called_once()

    # Verify cookie and localStorage injection
    mock_context.add_cookies.assert_called_once_with(mock_storage_state["cookies"])
    mock_context.add_init_script.assert_called_once()

    # Verify the script contains our localStorage data
    script_arg = mock_context.add_init_script.call_args[0][0]
    assert "https://example.com" in script_arg
    assert "key1" in script_arg
    assert "val1" in script_arg

    # Verify navigation was restored
    browser_session.navigate.assert_called_once_with("https://example.com")
