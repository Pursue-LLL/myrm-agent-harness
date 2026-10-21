"""Unit tests for browser_ask_human (takeover) tool.

Tests the tool creation, input validation, error paths, and interrupt/resume flow
using mocks. No real browser or network required.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_session():
    """Create a mock BrowserSession with a mock page."""
    session = MagicMock()
    page = MagicMock()
    page.url = "https://example.com/checkout"
    page.is_closed = MagicMock(return_value=False)
    page.screenshot = AsyncMock(return_value=b"\xff\xd8\xff\xe0fake_jpeg")
    page.title = AsyncMock(return_value="Checkout - Example Store")
    session.page = page
    session.is_browser_managed = MagicMock(return_value=True)
    return session


@pytest.fixture
def mock_session_no_page():
    """Session with no active page (None)."""
    session = MagicMock()
    session.page = None
    return session


@pytest.fixture
def mock_session_closed_page():
    """Session with a closed page."""
    session = MagicMock()
    page = MagicMock()
    page.is_closed = MagicMock(return_value=True)
    session.page = page
    return session


class TestCreateTakeoverTool:
    """Test tool creation and metadata."""

    def test_creates_tool_with_correct_name(self, mock_session):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        tool = create_takeover_tool(mock_session)
        assert tool.name == "browser_ask_human_tool"

    def test_tool_has_description(self, mock_session):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        tool = create_takeover_tool(mock_session)
        assert "take over" in tool.description.lower() or "takeover" in tool.description.lower()

    def test_tool_has_reason_arg(self, mock_session):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        tool = create_takeover_tool(mock_session)
        schema = tool.args_schema.model_json_schema()
        assert "reason" in schema["properties"]


class TestTakeoverToolNoPage:
    """Test tool behavior when no page is available."""

    def test_returns_error_when_no_page(self, mock_session_no_page):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        tool = create_takeover_tool(mock_session_no_page)
        result = asyncio.run(tool.ainvoke({"reason": "test"}))
        assert "Error" in result
        assert "No active browser page" in result

    def test_returns_error_when_tab_controller_lookup_fails(self, mock_session_no_page):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        mock_session_no_page._tab_controller.list_tabs = MagicMock(side_effect=RuntimeError("tabs unavailable"))
        tool = create_takeover_tool(mock_session_no_page)
        result = asyncio.run(tool.ainvoke({"reason": "test"}))
        assert "Error" in result
        assert "No active browser page" in result

    def test_returns_error_when_page_closed(self, mock_session_closed_page):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        tool = create_takeover_tool(mock_session_closed_page)
        result = asyncio.run(tool.ainvoke({"reason": "test"}))
        assert "Error" in result
        assert "No active browser page" in result


class TestTakeoverToolInterruptFlow:
    """Test the interrupt/resume flow with mocked LangGraph interrupt."""

    def test_dispatches_event_and_calls_interrupt(self, mock_session):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        tool = create_takeover_tool(mock_session)

        with (
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ) as mock_dispatch,
            patch("langgraph.types.interrupt") as mock_interrupt,
        ):
            mock_interrupt.return_value = {"decision": "approve", "message": "Done!"}

            asyncio.run(tool.ainvoke({"reason": "Please complete payment"}))

            assert mock_dispatch.call_count == 2
            first_call = mock_dispatch.call_args_list[0]
            assert first_call[0][0] == "browser_takeover_requested"
            payload = first_call[0][1]
            assert payload["reason"] == "Please complete payment"
            assert payload["url"] == "https://example.com/checkout"
            assert payload["screenshot_base64"] is not None
            assert payload["is_managed"] is True

            second_call = mock_dispatch.call_args_list[1]
            assert second_call[0][0] == "browser_takeover_completed"

            mock_interrupt.assert_called_once()
            interrupt_payload = mock_interrupt.call_args[0][0]
            assert interrupt_payload["action_type"] == "browser_takeover"
            assert interrupt_payload["reason"] == "Please complete payment"

    def test_dispatches_is_managed_false_for_local_browser(self, mock_session):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        mock_session.is_browser_managed = MagicMock(return_value=False)
        tool = create_takeover_tool(mock_session)

        with (
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ) as mock_dispatch,
            patch("langgraph.types.interrupt", return_value="done"),
        ):
            asyncio.run(tool.ainvoke({"reason": "Enter SMS code"}))

            payload = mock_dispatch.call_args_list[0][0][1]
            assert payload["is_managed"] is False

    def test_result_includes_user_message(self, mock_session):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        tool = create_takeover_tool(mock_session)

        with (
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ),
            patch("langgraph.types.interrupt", return_value={"message": "Payment done"}),
        ):
            result = asyncio.run(tool.ainvoke({"reason": "Complete payment"}))
            assert "Payment done" in result
            assert "User completed" in result

    def test_result_includes_url_change(self, mock_session):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        tool = create_takeover_tool(mock_session)
        type(mock_session.page).url = property(
            lambda self, _urls=iter(["https://example.com/checkout", "https://example.com/thank-you"]): next(_urls)
        )

        with (
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ),
            patch("langgraph.types.interrupt", return_value="ok"),
        ):
            result = asyncio.run(tool.ainvoke({"reason": "test"}))
            assert "thank-you" in result

    def test_result_with_string_response(self, mock_session):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        tool = create_takeover_tool(mock_session)

        with (
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ),
            patch("langgraph.types.interrupt", return_value="I finished the 2FA"),
        ):
            result = asyncio.run(tool.ainvoke({"reason": "Enter 2FA code"}))
            assert "I finished the 2FA" in result


class TestTakeoverToolRedaction:
    """Credential redaction of the result returned to the LLM.

    post_url can carry an OAuth callback code, and post_title / user_message
    are page-or-user-sourced; all must pass the unified output boundary so
    nothing reaches the LLM context in plaintext.
    """

    def test_oauth_code_in_post_url_is_redacted(self):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        session = MagicMock()
        page = MagicMock()
        page.url = "https://app.example.com/login"
        page.is_closed = MagicMock(return_value=False)
        page.screenshot = AsyncMock(return_value=b"\xff\xd8\xff\xe0fake_jpeg")
        page.title = AsyncMock(return_value="Account")
        session.page = page
        session.is_browser_managed = MagicMock(return_value=True)

        post_url = "https://app.example.com/callback?code=4d3f9c2a1b8e7f6d5c4b3a2"
        urls = iter(["https://app.example.com/login", post_url])
        type(page).url = property(lambda self, _i=urls: next(_i))

        tool = create_takeover_tool(session)

        with (
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ),
            patch("langgraph.types.interrupt", return_value="done"),
        ):
            result = asyncio.run(tool.ainvoke({"reason": "Please complete OAuth login"}))

        assert post_url not in result
        assert "4d3f9c2a1b8e7f6d5c4b3a2" not in result
        assert "callback" in result

    def test_user_message_with_credential_is_redacted(self):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        session = MagicMock()
        page = MagicMock()
        page.url = "https://example.com/checkout"
        page.is_closed = MagicMock(return_value=False)
        page.screenshot = AsyncMock(return_value=b"\xff\xd8\xff\xe0fake_jpeg")
        page.title = AsyncMock(return_value="Checkout")
        session.page = page
        session.is_browser_managed = MagicMock(return_value=True)

        tool = create_takeover_tool(session)

        with (
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ),
            patch(
                "langgraph.types.interrupt",
                return_value={"message": "API key is sk-proj-abcdefghijklmnop12345678"},
            ),
        ):
            result = asyncio.run(tool.ainvoke({"reason": "Complete payment"}))

        assert "sk-proj-abcdefghijklmnop12345678" not in result
        assert "API key is sk-pro..." in result

    def test_plain_url_change_still_readable(self):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        session = MagicMock()
        page = MagicMock()
        page.url = "https://example.com/checkout"
        page.is_closed = MagicMock(return_value=False)
        page.screenshot = AsyncMock(return_value=b"\xff\xd8\xff\xe0fake_jpeg")
        page.title = AsyncMock(return_value="Thank You")
        session.page = page
        session.is_browser_managed = MagicMock(return_value=True)

        urls = iter(["https://example.com/checkout", "https://example.com/thank-you"])
        type(page).url = property(lambda self, _i=urls: next(_i))

        tool = create_takeover_tool(session)

        with (
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ),
            patch("langgraph.types.interrupt", return_value="done"),
        ):
            result = asyncio.run(tool.ainvoke({"reason": "test"}))

        assert "https://example.com/thank-you" in result

    def test_logger_redacts_post_url_credential(self, caplog):
        """Logger arguments must be redacted before they reach the log sink:
        the takeover logger previously wrote the post_url verbatim, leaking an
        OAuth code into server logs (no global formatter is guaranteed when the
        harness runs outside the server)."""
        import logging

        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        session = MagicMock()
        page = MagicMock()
        page.url = "https://app.example.com/login"
        page.is_closed = MagicMock(return_value=False)
        page.screenshot = AsyncMock(return_value=b"\xff\xd8\xff\xe0fake_jpeg")
        page.title = AsyncMock(return_value="Account")
        session.page = page
        session.is_browser_managed = MagicMock(return_value=True)

        post_url = "https://app.example.com/callback?code=4d3f9c2a1b8e7f6d5c4b3a2"
        urls = iter(["https://app.example.com/login", post_url])
        type(page).url = property(lambda self, _i=urls: next(_i))

        tool = create_takeover_tool(session)

        takeover_logger = logging.getLogger("myrm_agent_harness.toolkits.browser.tools.takeover")
        takeover_logger.setLevel(logging.INFO)
        with (
            caplog.at_level(logging.INFO, logger=takeover_logger.name),
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ),
            patch("langgraph.types.interrupt", return_value="done"),
        ):
            asyncio.run(tool.ainvoke({"reason": "Please complete OAuth login"}))

        assert "4d3f9c2a1b8e7f6d5c4b3a2" not in caplog.text
        assert "callback" in caplog.text


class TestTakeoverToolScreenshotFailure:
    """Test graceful handling when screenshot fails."""

    def test_works_without_screenshot(self, mock_session):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        mock_session.page.screenshot = AsyncMock(side_effect=Exception("GPU error"))
        tool = create_takeover_tool(mock_session)

        with (
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ) as mock_dispatch,
            patch("langgraph.types.interrupt", return_value="done"),
        ):
            result = asyncio.run(tool.ainvoke({"reason": "Help needed"}))
            assert "User completed" in result
            first_call = mock_dispatch.call_args_list[0]
            payload = first_call[0][1]
            assert payload["screenshot_base64"] is None

    def test_resolves_page_via_tab_controller_when_session_page_missing(self, mock_session_no_page):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        page = MagicMock()
        page.is_closed = MagicMock(return_value=False)
        page.url = "https://bank.example/login"
        page.screenshot = AsyncMock(return_value=b"\xff\xd8\xff\xe0fake_jpeg")
        mock_session_no_page._tab_controller.list_tabs = MagicMock(return_value=["tab-1"])
        mock_session_no_page._tab_controller.get_active_page = MagicMock(return_value=page)
        mock_session_no_page.is_browser_managed = MagicMock(return_value=False)

        tool = create_takeover_tool(mock_session_no_page)

        with (
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ) as mock_dispatch,
            patch("langgraph.types.interrupt", return_value="done"),
        ):
            result = asyncio.run(tool.ainvoke({"reason": "Enter SMS code"}))

        assert "User completed" in result
        payload = mock_dispatch.call_args_list[0][0][1]
        assert payload["url"] == "https://bank.example/login"
        assert payload["is_managed"] is False

    def test_continues_when_post_interrupt_url_and_title_fail(self, mock_session):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        url_reads = {"count": 0}

        def _read_url(_self: object) -> str:
            url_reads["count"] += 1
            if url_reads["count"] == 1:
                return "https://example.com/checkout"
            raise RuntimeError("url gone")

        type(mock_session.page).url = property(_read_url)
        mock_session.page.title = AsyncMock(side_effect=RuntimeError("title failed"))
        tool = create_takeover_tool(mock_session)

        with (
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ),
            patch("langgraph.types.interrupt", return_value="done"),
        ):
            result = asyncio.run(tool.ainvoke({"reason": "Enter 2FA code"}))

        assert "User completed" in result
        assert "respond to the user" in result.lower()

    def test_continues_when_initial_url_read_fails(self, mock_session):
        from myrm_agent_harness.toolkits.browser.tools.takeover import (
            create_takeover_tool,
        )

        type(mock_session.page).url = property(lambda _self: (_ for _ in ()).throw(RuntimeError("url unavailable")))
        tool = create_takeover_tool(mock_session)

        with (
            patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new_callable=AsyncMock,
            ) as mock_dispatch,
            patch("langgraph.types.interrupt", return_value="done"),
        ):
            result = asyncio.run(tool.ainvoke({"reason": "Enter SMS code"}))

        assert "User completed" in result
        payload = mock_dispatch.call_args_list[0][0][1]
        assert payload["url"] == ""
