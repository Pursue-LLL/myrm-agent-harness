"""Comprehensive tests for LangChain browser tools (100% coverage)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.tools import _mark_untrusted, create_browser_tools


@pytest.fixture
def mock_session() -> Any:
    """Mock BrowserSession for tools testing."""
    session = MagicMock()

    session.navigate = AsyncMock(return_value="Navigated to Example Page (https://example.com, status=200)")
    session.inspect = AsyncMock(return_value="Total refs: 25\nRegions: main, form\nRecommended: #main")
    session.snapshot = AsyncMock(return_value=('- button "Click" [ref=e0]', {"ref_count": 1}))
    session.interact = AsyncMock(return_value="Clicked element e0")
    session.extract_text = AsyncMock(return_value="Page text content")
    session.extract_screenshot = AsyncMock(return_value="data:image/jpeg;base64,abc123")

    comparison_result = MagicMock()
    comparison_result.to_llm_message = MagicMock(return_value="Similarity: 95%")
    session.compare_screenshots = AsyncMock(return_value=comparison_result)
    session.close = AsyncMock()
    session.evaluate = AsyncMock(return_value="42")
    session.new_tab = AsyncMock(return_value="tab1")
    session.switch_tab = AsyncMock(return_value="Switched to tab1")
    session.list_tabs = MagicMock(return_value=["tab0", "tab1"])
    session.close_tab = AsyncMock(return_value="Closed tab1")
    session.go_back = AsyncMock(return_value="Navigated back")
    session.go_forward = AsyncMock(return_value="Navigated forward")
    session.save_pdf = AsyncMock(return_value="Saved PDF to /tmp/page.pdf")
    session.resize = AsyncMock(return_value="Resized to 1920x1080")
    session.wait_for_load = AsyncMock(return_value="Page loaded")
    session.get_console_log = MagicMock(return_value="Console: log message")
    session.get_network_log = MagicMock(return_value="Network: GET /api")
    session.set_dialog_response = AsyncMock(return_value="Dialog configured: accept")
    session.save_session = AsyncMock(return_value="Saved session for example.com")
    session.restore_session = AsyncMock(return_value="Restored session for example.com")
    session.list_sessions = AsyncMock(return_value="Sessions: example.com, github.com")
    session.delete_session = AsyncMock(return_value="Deleted session for example.com")

    return session


# =============================================================================
# Helper functions
# =============================================================================


def test_mark_untrusted() -> None:
    """Test _mark_untrusted wraps content with 4-layer security boundary."""
    content = "untrusted content"
    result = _mark_untrusted(content)

    assert "SECURITY NOTICE" in result
    assert "UNTRUSTED" in result
    assert "untrusted content" in result
    assert "<<<UNTRUSTED_DATA" in result
    assert "<<<END_UNTRUSTED_DATA" in result


# =============================================================================
# create_browser_tools
# =============================================================================


def test_create_browser_tools(mock_session: Any) -> None:
    """Test create_browser_tools returns 6 tools."""
    tools = create_browser_tools(mock_session)

    assert len(tools) == 6
    tool_names = {tool.name for tool in tools}
    assert tool_names == {
        "browser_navigate_tool",
        "browser_inspect_tool",
        "browser_snapshot_tool",
        "browser_interact_tool",
        "browser_extract_tool",
        "browser_manage_tool",
    }


# =============================================================================
# browser_navigate
# =============================================================================


@pytest.mark.asyncio
async def test_browser_navigate_basic(mock_session: Any) -> None:
    """Test browser_navigate basic functionality."""
    tools = create_browser_tools(mock_session)
    navigate_tool = next(t for t in tools if t.name == "browser_navigate_tool")

    result = await navigate_tool.ainvoke({"url": "https://example.com"})

    assert "Navigated" in result
    mock_session.navigate.assert_called_once_with("https://example.com")


# =============================================================================
# browser_inspect
# =============================================================================


@pytest.mark.asyncio
async def test_browser_inspect_basic(mock_session: Any) -> None:
    """Test browser_inspect returns page structure."""
    tools = create_browser_tools(mock_session)
    inspect_tool = next(t for t in tools if t.name == "browser_inspect_tool")

    result = await inspect_tool.ainvoke({})

    assert "Total refs" in result
    mock_session.inspect.assert_called_once()


# =============================================================================
# browser_snapshot
# =============================================================================


@pytest.mark.asyncio
async def test_browser_snapshot_default_params(mock_session: Any) -> None:
    """Test browser_snapshot with default params."""
    tools = create_browser_tools(mock_session)
    snapshot_tool = next(t for t in tools if t.name == "browser_snapshot_tool")

    result = await snapshot_tool.ainvoke({})

    assert "button" in result
    call_args = mock_session.snapshot.call_args
    assert call_args.kwargs["scope"] == "content"
    assert call_args.kwargs["diff"] is True
    assert call_args.kwargs["compact"] is False


@pytest.mark.asyncio
async def test_browser_snapshot_returns_string_only(mock_session: Any) -> None:
    """Test browser_snapshot when session returns string only (not tuple)."""
    mock_session.snapshot = AsyncMock(return_value='- button "Click" [ref=e0]')
    tools = create_browser_tools(mock_session)
    snapshot_tool = next(t for t in tools if t.name == "browser_snapshot_tool")

    result = await snapshot_tool.ainvoke({})

    assert "button" in result
    assert "UNTRUSTED_DATA" in result


@pytest.mark.asyncio
async def test_browser_snapshot_custom_params(mock_session: Any) -> None:
    """Test browser_snapshot with custom params."""
    tools = create_browser_tools(mock_session)
    snapshot_tool = next(t for t in tools if t.name == "browser_snapshot_tool")

    result = await snapshot_tool.ainvoke(
        {
            "scope": "interactive",
            "diff": False,
            "compact": True,
            "selector": "#main",
            "max_tokens": 500,
        }
    )

    assert "button" in result
    call_args = mock_session.snapshot.call_args
    assert call_args.kwargs["scope"] == "interactive"
    assert call_args.kwargs["diff"] is False
    assert call_args.kwargs["compact"] is True
    assert call_args.kwargs["selector"] == "#main"
    assert call_args.kwargs["max_tokens"] == 500


# =============================================================================
# browser_interact
# =============================================================================


@pytest.mark.asyncio
async def test_browser_interact_click(mock_session: Any) -> None:
    """Test browser_interact click action."""
    tools = create_browser_tools(mock_session)
    interact_tool = next(t for t in tools if t.name == "browser_interact_tool")

    result = await interact_tool.ainvoke({"action": "click", "ref": "e0"})

    assert "Clicked" in result
    mock_session.interact.assert_called_once_with("click", "e0", "")


@pytest.mark.asyncio
async def test_browser_interact_with_text(mock_session: Any) -> None:
    """Test browser_interact with text parameter."""
    tools = create_browser_tools(mock_session)
    interact_tool = next(t for t in tools if t.name == "browser_interact_tool")

    await interact_tool.ainvoke({"action": "type", "ref": "e1", "text": "Hello"})

    mock_session.interact.assert_called_once_with("type", "e1", "Hello")


# =============================================================================
# browser_extract
# =============================================================================


@pytest.mark.asyncio
async def test_browser_extract_text_default(mock_session: Any) -> None:
    """Test browser_extract text mode (default)."""
    tools = create_browser_tools(mock_session)
    extract_tool = next(t for t in tools if t.name == "browser_extract_tool")

    result = await extract_tool.ainvoke({})

    assert "UNTRUSTED_DATA" in result
    assert "Page text content" in result
    mock_session.extract_text.assert_called_once()


@pytest.mark.asyncio
async def test_browser_extract_text_explicit(mock_session: Any) -> None:
    """Test browser_extract text mode (explicit)."""
    tools = create_browser_tools(mock_session)
    extract_tool = next(t for t in tools if t.name == "browser_extract_tool")

    result = await extract_tool.ainvoke({"mode": "text"})

    assert "UNTRUSTED_DATA" in result
    assert "Page text content" in result
    mock_session.extract_text.assert_called_once()


@pytest.mark.asyncio
async def test_browser_extract_screenshot_default(mock_session: Any) -> None:
    """Test browser_extract screenshot mode."""
    tools = create_browser_tools(mock_session)
    extract_tool = next(t for t in tools if t.name == "browser_extract_tool")

    result = await extract_tool.ainvoke({"mode": "screenshot"})

    assert "data:image/jpeg" in result
    mock_session.extract_screenshot.assert_called_once_with(scale=1.0)


@pytest.mark.asyncio
async def test_browser_extract_screenshot_annotated(mock_session: Any) -> None:
    """Test browser_extract screenshot with annotation."""
    tools = create_browser_tools(mock_session)
    extract_tool = next(t for t in tools if t.name == "browser_extract_tool")

    await extract_tool.ainvoke({"mode": "screenshot", "annotate": True})

    mock_session.extract_screenshot.assert_called_once_with(scale=1.0)


@pytest.mark.asyncio
async def test_browser_extract_screenshot_retina(mock_session: Any) -> None:
    """Test browser_extract screenshot with 2x scale."""
    tools = create_browser_tools(mock_session)
    extract_tool = next(t for t in tools if t.name == "browser_extract_tool")

    await extract_tool.ainvoke({"mode": "screenshot", "scale": 2.0})

    mock_session.extract_screenshot.assert_called_once_with(scale=2.0)


@pytest.mark.asyncio
async def test_browser_extract_diff_fast_no_baseline(mock_session: Any) -> None:
    """Test browser_extract diff_fast without baseline returns error."""
    tools = create_browser_tools(mock_session)
    extract_tool = next(t for t in tools if t.name == "browser_extract_tool")

    result = await extract_tool.ainvoke({"mode": "diff_fast"})

    assert "Error" in result
    assert "baseline" in result
    mock_session.compare_screenshots.assert_not_called()


@pytest.mark.asyncio
async def test_browser_extract_diff_fast_with_baseline(mock_session: Any) -> None:
    """Test browser_extract diff_fast with baseline."""
    tools = create_browser_tools(mock_session)
    extract_tool = next(t for t in tools if t.name == "browser_extract_tool")

    result = await extract_tool.ainvoke({"mode": "diff_fast", "baseline": "base64data"})

    assert "similarity" in result.lower() or "different" in result.lower()
    mock_session.compare_screenshots.assert_called_once_with("base64data", strategy="fast", similarity_threshold=0.9)


@pytest.mark.asyncio
async def test_browser_extract_diff_accurate_no_baseline(mock_session: Any) -> None:
    """Test browser_extract diff_accurate without baseline returns error."""
    tools = create_browser_tools(mock_session)
    extract_tool = next(t for t in tools if t.name == "browser_extract_tool")

    result = await extract_tool.ainvoke({"mode": "diff_accurate"})

    assert "Error" in result
    assert "baseline" in result
    mock_session.compare_screenshots.assert_not_called()


@pytest.mark.asyncio
async def test_browser_extract_diff_accurate_with_baseline(mock_session: Any) -> None:
    """Test browser_extract diff_accurate with baseline."""
    tools = create_browser_tools(mock_session)
    extract_tool = next(t for t in tools if t.name == "browser_extract_tool")

    await extract_tool.ainvoke({"mode": "diff_accurate", "baseline": "base64data"})

    mock_session.compare_screenshots.assert_called_once_with(
        "base64data", strategy="accurate", color_tolerance=0.1, mismatch_threshold=5.0, include_aa=True
    )


# =============================================================================
# browser_manage
# =============================================================================


@pytest.mark.asyncio
async def test_browser_manage_close(mock_session: Any) -> None:
    """Test browser_manage close action."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "close"})

    assert "closed" in result.lower()
    mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_browser_manage_evaluate_success(mock_session: Any) -> None:
    """Test browser_manage evaluate action."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "evaluate", "value": "2+2"})

    assert "42" in result
    mock_session.evaluate.assert_called_once_with("2+2")


@pytest.mark.asyncio
async def test_browser_manage_evaluate_no_value(mock_session: Any) -> None:
    """Test browser_manage evaluate without value returns error."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "evaluate"})

    assert "Error" in result
    assert "required" in result
    mock_session.evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_browser_manage_new_tab_with_url(mock_session: Any) -> None:
    """Test browser_manage new_tab with URL."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "new_tab", "value": "https://example.com"})

    assert "tab1" in result
    mock_session.new_tab.assert_called_once_with("https://example.com")


@pytest.mark.asyncio
async def test_browser_manage_new_tab_blank(mock_session: Any) -> None:
    """Test browser_manage new_tab without URL."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "new_tab"})

    assert "tab1" in result
    mock_session.new_tab.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_browser_manage_switch_tab(mock_session: Any) -> None:
    """Test browser_manage switch_tab action."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "switch_tab", "value": "tab1"})

    assert "Switched" in result
    mock_session.switch_tab.assert_called_once_with("tab1")


@pytest.mark.asyncio
async def test_browser_manage_list_tabs_with_tabs(mock_session: Any) -> None:
    """Test browser_manage list_tabs with open tabs."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "list_tabs"})

    assert "tab0" in result
    assert "tab1" in result
    mock_session.list_tabs.assert_called_once()


@pytest.mark.asyncio
async def test_browser_manage_list_tabs_empty(mock_session: Any) -> None:
    """Test browser_manage list_tabs with no tabs."""
    mock_session.list_tabs = MagicMock(return_value=[])
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "list_tabs"})

    assert "No open tabs" in result
    mock_session.list_tabs.assert_called_once()


@pytest.mark.asyncio
async def test_browser_manage_close_tab(mock_session: Any) -> None:
    """Test browser_manage close_tab action."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "close_tab", "value": "tab1"})

    assert "Closed" in result
    mock_session.close_tab.assert_called_once_with("tab1")


@pytest.mark.asyncio
async def test_browser_manage_back(mock_session: Any) -> None:
    """Test browser_manage back action."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "back"})

    assert "back" in result.lower()
    mock_session.go_back.assert_called_once()


@pytest.mark.asyncio
async def test_browser_manage_forward(mock_session: Any) -> None:
    """Test browser_manage forward action."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "forward"})

    assert "forward" in result.lower()
    mock_session.go_forward.assert_called_once()


@pytest.mark.asyncio
async def test_browser_manage_save_pdf(mock_session: Any) -> None:
    """Test browser_manage save_pdf action."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "save_pdf"})

    assert "PDF" in result
    mock_session.save_pdf.assert_called_once()


@pytest.mark.asyncio
async def test_browser_manage_resize_success(mock_session: Any) -> None:
    """Test browser_manage resize action."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "resize", "value": "1920x1080"})

    assert "Resized" in result
    mock_session.resize.assert_called_once_with(1920, 1080)


@pytest.mark.asyncio
async def test_browser_manage_resize_invalid_format(mock_session: Any) -> None:
    """Test browser_manage resize with invalid format."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "resize", "value": "invalid"})

    assert "Error" in result
    assert "WIDTHxHEIGHT" in result
    mock_session.resize.assert_not_called()


@pytest.mark.asyncio
async def test_browser_manage_wait_for_load(mock_session: Any) -> None:
    """Test browser_manage wait_for_load action."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "wait_for_load"})

    assert "loaded" in result.lower()
    mock_session.wait_for_load.assert_called_once()


@pytest.mark.asyncio
async def test_browser_manage_console_log(mock_session: Any) -> None:
    """Test browser_manage console_log action."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "console_log"})

    assert "Console" in result
    mock_session.get_console_log.assert_called_once()


@pytest.mark.asyncio
async def test_browser_manage_network_log(mock_session: Any) -> None:
    """Test browser_manage network_log action."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "network_log"})

    assert "Network" in result
    mock_session.get_network_log.assert_called_once()


@pytest.mark.asyncio
async def test_browser_manage_dialog_response_accept(mock_session: Any) -> None:
    """Test browser_manage dialog_response accept."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "dialog_response", "value": "accept"})

    assert "Dialog" in result
    mock_session.set_dialog_response.assert_called_once_with(True, "")


@pytest.mark.asyncio
async def test_browser_manage_dialog_response_dismiss(mock_session: Any) -> None:
    """Test browser_manage dialog_response dismiss."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    await manage_tool.ainvoke({"action": "dialog_response", "value": "dismiss"})

    mock_session.set_dialog_response.assert_called_once_with(False, "")


@pytest.mark.asyncio
async def test_browser_manage_dialog_response_with_prompt(mock_session: Any) -> None:
    """Test browser_manage dialog_response with prompt text."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    await manage_tool.ainvoke({"action": "dialog_response", "value": "accept:my input"})

    mock_session.set_dialog_response.assert_called_once_with(True, "my input")


@pytest.mark.asyncio
async def test_browser_manage_save_session_domain_only(mock_session: Any) -> None:
    """Test browser_manage save_session with domain only."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "save_session", "value": "example.com"})

    assert "Saved" in result
    mock_session.save_session.assert_called_once_with("example.com")


@pytest.mark.asyncio
async def test_browser_manage_save_session_with_label(mock_session: Any) -> None:
    """Test browser_manage save_session with domain and label."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "save_session", "value": "example.com:my-session"})

    assert "Saved" in result
    mock_session.save_session.assert_called_once_with("example.com:my-session")


@pytest.mark.asyncio
async def test_browser_manage_save_session_no_domain(mock_session: Any) -> None:
    """Test browser_manage save_session without domain returns error."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "save_session"})

    assert "Error" in result
    assert "domain" in result
    mock_session.save_session.assert_not_called()


@pytest.mark.asyncio
async def test_browser_manage_restore_session_success(mock_session: Any) -> None:
    """Test browser_manage restore_session."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "restore_session", "value": "example.com"})

    assert "Restored" in result
    mock_session.restore_session.assert_called_once_with("example.com")


@pytest.mark.asyncio
async def test_browser_manage_restore_session_no_domain(mock_session: Any) -> None:
    """Test browser_manage restore_session without domain returns error."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "restore_session"})

    assert "Error" in result
    assert "domain" in result
    mock_session.restore_session.assert_not_called()


@pytest.mark.asyncio
async def test_browser_manage_list_sessions(mock_session: Any) -> None:
    """Test browser_manage list_sessions action."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "list_sessions"})

    assert "Sessions" in result
    mock_session.list_sessions.assert_called_once()


@pytest.mark.asyncio
async def test_browser_manage_delete_session_success(mock_session: Any) -> None:
    """Test browser_manage delete_session."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "delete_session", "value": "example.com"})

    assert "Deleted" in result
    mock_session.delete_session.assert_called_once_with("example.com")


@pytest.mark.asyncio
async def test_browser_manage_delete_session_no_domain(mock_session: Any) -> None:
    """Test browser_manage delete_session without domain returns error."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "delete_session"})

    assert "Error" in result
    assert "domain" in result
    mock_session.delete_session.assert_not_called()


@pytest.mark.asyncio
async def test_browser_manage_wait_for_user(mock_session: Any) -> None:
    """Test browser_manage wait_for_user action."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "wait_for_user"})

    assert "Current page state" in result
    mock_session.snapshot.assert_called_once_with(scope="content", diff=False)


@pytest.mark.asyncio
async def test_browser_manage_unknown_action(mock_session: Any) -> None:
    """Test browser_manage with unknown action."""
    tools = create_browser_tools(mock_session)
    manage_tool = next(t for t in tools if t.name == "browser_manage_tool")

    result = await manage_tool.ainvoke({"action": "invalid_action"})

    assert "Unknown action" in result
    assert "invalid_action" in result


# Integration tests are covered by test_browser_session_integration.py
