"""Unit tests for RestrictedAccessibilityBrowserSession and tools factory."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.session.restricted_ax_session import (
    RestrictedAccessibilityBrowserSession,
    RestrictedAxSecurityViolationError,
    create_restricted_ax_browser_tools,
)


def test_restricted_ax_session_flags_and_eval_blocking():
    """Restricted AX session must enforce is_restricted_ax_mode and forbid evaluate."""
    session = RestrictedAccessibilityBrowserSession()
    assert session.is_restricted_ax_mode is True

    # evaluate() must physically raise RestrictedAxSecurityViolationError
    with pytest.raises(RestrictedAxSecurityViolationError) as exc_info:
        import asyncio
        asyncio.run(session.evaluate("document.cookie"))

    err_msg = str(exc_info.value)
    assert "strictly forbids JavaScript evaluation" in err_msg
    assert "document.cookie" in err_msg


def test_create_restricted_ax_browser_tools_omits_execute_script():
    """Factory must return only safe tools and strictly exclude browser_execute_script_tool."""
    mock_session = MagicMock()
    mock_session.session_id = "mock-session"

    tools = create_restricted_ax_browser_tools(mock_session)

    # Exactly 7 safe tools
    assert len(tools) == 7

    tool_names = [getattr(t, "name", str(t)) for t in tools]

    # Verify browser_execute_script_tool is absent
    assert "browser_execute_script_tool" not in tool_names

    # Verify essential accessibility and interaction tools are present
    expected_tools = {
        "browser_navigate_tool",
        "browser_snapshot_tool",
        "browser_interact_tool",
        "browser_extract_tool",
        "browser_inspect_tool",
        "browser_manage_tool",
        "browser_ask_human_tool",
    }
    assert expected_tools.issubset(set(tool_names))
