"""Tests for browser tool output credential redaction.

Browser-sourced content must be credential-redacted (via redact_sensitive_text)
before it is wrapped with the untrusted-content boundary, so page-displayed
API keys / tokens never reach the LLM context or the persistent memory store.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.tools.common import mark_untrusted
from myrm_agent_harness.toolkits.browser.tools.inspect import create_inspect_tool
from myrm_agent_harness.toolkits.browser.tools.interact import create_interact_tool
from myrm_agent_harness.toolkits.browser.tools.manage import create_manage_tool
from myrm_agent_harness.toolkits.browser.tools.navigate import create_navigate_tool


class TestMarkUntrustedRedaction:
    def test_redacts_api_key_tokens(self) -> None:
        output = mark_untrusted("Token shown on page: ghp_abcdefghijklmnop")
        assert "ghp_abcdefghijklmnop" not in output
        assert "..." in output or "***" in output

    def test_redacts_openai_key(self) -> None:
        output = mark_untrusted("API Key: sk-proj-abcdefghijklmnop1234567890")
        assert "sk-proj-abcdefghijklmnop1234567890" not in output

    def test_redacts_authorization_header(self) -> None:
        output = mark_untrusted("Authorization: Bearer sk-ant-api03-longtoken12345678")
        assert "sk-ant-api03-longtoken12345678" not in output

    def test_redacts_password_env_assignment(self) -> None:
        output = mark_untrusted("DB_PASSWORD=supersecret1234567890")
        assert "supersecret1234567890" not in output

    def test_preserves_normal_text(self) -> None:
        text = "This is a normal page description with no secrets."
        output = mark_untrusted(text)
        assert text in output

    def test_wraps_with_untrusted_boundary(self) -> None:
        output = mark_untrusted("Hello world")
        assert "UNTRUSTED_DATA" in output
        assert "END_UNTRUSTED_DATA" in output
        assert "SECURITY NOTICE" in output

    def test_empty_content_returns_empty(self) -> None:
        assert mark_untrusted("") == ""


@pytest.mark.asyncio
async def test_manage_console_log_redacted_and_wrapped() -> None:
    session = MagicMock()
    session.get_console_log.return_value = "Console: loaded config with key ghp_abcdefghijklmnop"
    tool = create_manage_tool(session)  # type: ignore[arg-type]

    output = await tool.ainvoke({"action": "console_log", "value": ""})

    assert "ghp_abcdefghijklmnop" not in output
    assert "UNTRUSTED_DATA" in output
    session.get_console_log.assert_called_once_with()


@pytest.mark.asyncio
async def test_manage_network_log_redacted_and_wrapped() -> None:
    session = MagicMock()
    session.get_network_log.return_value = "GET /api Authorization: Bearer sk-ant-api03-longtoken12345678"
    tool = create_manage_tool(session)  # type: ignore[arg-type]

    output = await tool.ainvoke({"action": "network_log", "value": ""})

    assert "sk-ant-api03-longtoken12345678" not in output
    assert "UNTRUSTED_DATA" in output
    session.get_network_log.assert_called_once_with()


@pytest.mark.asyncio
async def test_manage_evaluate_redacted_and_wrapped() -> None:
    session = MagicMock()
    session.evaluate = AsyncMock(return_value="returned sk-proj-abcdefghijklmnop1234567890")
    tool = create_manage_tool(session)  # type: ignore[arg-type]

    output = await tool.ainvoke({"action": "evaluate", "value": "document.title"})

    assert "sk-proj-abcdefghijklmnop1234567890" not in output
    assert "UNTRUSTED_DATA" in output
    session.evaluate.assert_awaited_once_with("document.title")


@pytest.mark.asyncio
async def test_inspect_redacted_and_wrapped() -> None:
    session = MagicMock()
    session.inspect = AsyncMock(return_value="Title: Example\nURL: https://x.com?token=ghp_abcdefghijklmnop")
    tool = create_inspect_tool(session)  # type: ignore[arg-type]

    output = await tool.ainvoke({})

    assert "ghp_abcdefghijklmnop" not in output
    assert "UNTRUSTED_DATA" in output
    session.inspect.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_navigate_redacted_and_wrapped() -> None:
    session = MagicMock()
    session.navigate = AsyncMock(
        return_value="Navigated to https://x.com/login (status=200, title=Login)"
    )
    tool = create_navigate_tool(session)  # type: ignore[arg-type]

    output = await tool.ainvoke({"url": "https://x.com/login"})

    assert "Navigated" in output
    assert "UNTRUSTED_DATA" in output
    session.navigate.assert_awaited_once_with("https://x.com/login", verify_goal=None)


@pytest.mark.asyncio
async def test_interact_redacted_and_wrapped() -> None:
    session = MagicMock()
    session.list_downloads.return_value = []
    session.interact = AsyncMock(return_value="Clicked element with key sk-proj-abcdefghijklmnop1234567890")
    tool = create_interact_tool(session)  # type: ignore[arg-type]

    output = await tool.ainvoke({"action": "click", "ref": "e0"})

    assert "sk-proj-abcdefghijklmnop1234567890" not in output
    assert "UNTRUSTED_DATA" in output
    session.interact.assert_awaited_once_with("click", "e0", "", verify_goal=None)
