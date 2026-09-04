"""Integration: ToolError diagnostic_info → executor → SSE guardrail_blocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.errors.tool_error_category import ToolErrorCategory
from myrm_agent_harness.agent.middlewares.tooling.tool_executor import execute_with_retry
from myrm_agent_harness.agent.streaming.event_handlers import _handle_tool_result
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.utils.errors import ToolError


def _make_request(tool_name: str = "bash_code_execute_tool", tool_call_id: str = "tc_1") -> MagicMock:
    req = MagicMock()
    req.tool_call = {"name": tool_name, "id": tool_call_id}
    return req


@pytest.mark.asyncio
async def test_myrm_tools_blocked_reaches_sse_as_guardrail_blocked() -> None:
    err = ToolError(
        "Command blocked: import myrm_tools",
        user_hint="Use skills.* or tools.* imports for MCP batch scripts.",
        diagnostic_info={"error_category": ToolErrorCategory.GUARDRAIL_BLOCKED.value},
        error_code="MYRM_TOOLS_BLOCKED",
    )
    handler = AsyncMock(side_effect=err)

    with (
        patch("myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_event_logger", return_value=None),
        patch("myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_terminal_errors", return_value=set()),
    ):
        tool_msg = await execute_with_retry(
            _make_request(),
            handler,
            "bash_code_execute_tool",
            "tc_guardrail",
            allowed_domains=None,
        )

    assert isinstance(tool_msg, ToolMessage)
    assert tool_msg.additional_kwargs.get("error_category") == "guardrail_blocked"

    events: list[dict] = []
    async for event in _handle_tool_result(tool_msg, "msg_guardrail", None):
        events.append(event)

    assert events[0]["type"] == AgentEventType.TASKS_STEPS.value
    assert events[0]["status"] == "error"
    assert events[0]["error_category"] == "guardrail_blocked"
    assert "skills" in events[0]["error_hint"]


@pytest.mark.asyncio
async def test_tool_error_with_traceback_and_secrets_is_redacted_in_sse() -> None:
    """Negative regression: error content & error_hint carrying secrets and paths must be redacted in SSE."""
    raw_error_message = (
        "Traceback (most recent call last):\n"
        '  File "/Users/alice/projects/app/main.py", line 42, in run\n'
        "    client = Anthropic(api_key='sk-ant-api03-abcdefghijklmnop1234567890')\n"
        "ValueError: Connection failed with token ghp_abcdefghijklmnop12345678901234567890"
    )
    raw_hint = "Please verify your key sk-ant-api03-abcdefghijklmnop1234567890 in /Users/alice/.env"

    err = ToolError(
        raw_error_message,
        user_hint=raw_hint,
        diagnostic_info={"error_category": ToolErrorCategory.UNKNOWN.value},
        error_code="COMMAND_FAILED",
    )
    handler = AsyncMock(side_effect=err)

    with (
        patch("myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_event_logger", return_value=None),
        patch("myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_terminal_errors", return_value=set()),
    ):
        tool_msg = await execute_with_retry(
            _make_request(),
            handler,
            "bash_code_execute_tool",
            "tc_redact_test",
            allowed_domains=None,
        )

    # 1. ToolMessage layer assertions
    assert isinstance(tool_msg, ToolMessage)
    content_str = str(tool_msg.content)
    assert "sk-ant-api03" not in content_str
    assert "ghp_abcdefghijklmnop12345678901234567890" not in content_str
    assert "sk-ant-api03" not in str(tool_msg.additional_kwargs.get("error_hint", ""))

    # 2. SSE streaming event layer assertions
    events: list[dict] = []
    async for event in _handle_tool_result(tool_msg, "msg_redact_test", None):
        events.append(event)

    assert len(events) >= 1
    step_event = events[0]
    assert step_event["status"] == "error"
    error_payload = step_event["error"]
    assert "sk-ant-api03" not in error_payload
    assert "ghp_abcdefghijklmnop12345678901234567890" not in error_payload
    assert "/Users/alice" not in error_payload
    assert "<HOME>" in error_payload

    hint_payload = step_event["error_hint"]
    assert "sk-ant-api03" not in hint_payload
    assert "/Users/alice" not in hint_payload
    assert "<HOME>" in hint_payload

