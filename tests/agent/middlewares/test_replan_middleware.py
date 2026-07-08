"""Test replan_middleware.py."""

from unittest.mock import MagicMock, patch

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.middlewares.replan_middleware import (
    ReplanMiddleware,
    _per_tool_errors_var,
    reset_replan_attempts,
)


@pytest.fixture(autouse=True)
def reset_attempts():
    reset_replan_attempts()
    yield
    reset_replan_attempts()


@pytest.fixture
def middleware():
    return ReplanMiddleware()


@pytest.mark.asyncio
async def test_awrap_tool_call_success(middleware):
    """Test that awrap_tool_call returns handler result on success."""
    request = ToolCallRequest(
        tool_call={"name": "test_tool", "args": {}, "id": "call_1"},
        tool=MagicMock(),
        state={},
        runtime=MagicMock(),
    )
    expected_message = ToolMessage(
        content="success", name="test_tool", tool_call_id="call_1"
    )

    async def handler(req):
        return expected_message

    result = await middleware.awrap_tool_call(request, handler)
    assert result == expected_message


@pytest.mark.asyncio
async def test_awrap_tool_call_propagates_graph_interrupt(middleware):
    """GraphInterrupt from HITL tools (e.g. ask_question_tool) must not be swallowed."""
    from langgraph.errors import GraphInterrupt

    request = ToolCallRequest(
        tool_call={"name": "ask_question_tool", "args": {}, "id": "call_clarify"},
        tool=MagicMock(),
        state={},
        runtime=MagicMock(),
    )

    async def handler(req):
        raise GraphInterrupt("clarification")

    with pytest.raises(GraphInterrupt):
        await middleware.awrap_tool_call(request, handler)


@pytest.mark.asyncio
@patch(
    "myrm_agent_harness.agent.security.guards.loop_suggestions.core.get_tool_suggestion"
)
async def test_awrap_tool_call_catches_error(mock_get_suggestion, middleware):
    """Test that awrap_tool_call catches exceptions and returns a Replan ToolMessage."""
    mock_get_suggestion.return_value = "Try checking the permissions."

    request = ToolCallRequest(
        tool_call={
            "name": "bash_code_execute_tool",
            "args": {"command": "ls /root"},
            "id": "call_err_1",
        },
        tool=MagicMock(),
        state={},
        runtime=MagicMock(),
    )

    async def handler(req):
        raise ValueError("Permission denied")

    result = await middleware.awrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert result.name == "bash_code_execute_tool"
    assert result.tool_call_id == "call_err_1"
    assert result.status == "error"
    assert "ToolExecutionError: Permission denied" in result.content
    assert "Diagnostic Hint: Try checking the permissions." in result.content
    mock_get_suggestion.assert_called_once_with("bash_code_execute_tool")


@pytest.mark.asyncio
@patch(
    "myrm_agent_harness.agent.security.guards.loop_suggestions.core.get_tool_suggestion"
)
async def test_awrap_tool_call_empty_args(mock_get_suggestion, middleware):
    """Test error handling when tool_call args is an empty dict."""
    mock_get_suggestion.return_value = "Check docs."

    request = ToolCallRequest(
        tool_call={"name": "file_read", "args": {}, "id": "call_empty_1"},
        tool=MagicMock(),
        state={},
        runtime=MagicMock(),
    )

    async def handler(req):
        raise FileNotFoundError("No such file")

    result = await middleware.awrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "ToolExecutionError: No such file" in result.content
    assert "Diagnostic Hint:" in result.content


@pytest.mark.asyncio
@patch(
    "myrm_agent_harness.agent.security.guards.loop_suggestions.core.get_tool_suggestion"
)
async def test_awrap_tool_call_missing_name(mock_get_suggestion, middleware):
    """Test handling when tool_call lacks 'name' key."""
    mock_get_suggestion.return_value = "Generic recovery."

    request = ToolCallRequest(
        tool_call={"args": {"x": 1}, "id": "call_no_name"},
        tool=MagicMock(),
        state={},
        runtime=MagicMock(),
    )

    async def handler(req):
        raise RuntimeError("Something broke")

    result = await middleware.awrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    assert result.name == "unknown"
    assert "ToolExecutionError" in result.content


@pytest.mark.asyncio
async def test_awrap_tool_call_no_exception(middleware):
    """Test that successful handler returns result as-is (no error wrapping)."""
    request = ToolCallRequest(
        tool_call={"name": "test_tool", "args": {"query": "hello"}, "id": "call_ok"},
        tool=MagicMock(),
        state={},
        runtime=MagicMock(),
    )

    expected = ToolMessage(
        content="result data", name="test_tool", tool_call_id="call_ok"
    )

    async def handler(req):
        return expected

    _per_tool_errors_var.set({"test_tool": 2})
    result = await middleware.awrap_tool_call(request, handler)
    assert result is expected
    assert "test_tool" not in _per_tool_errors_var.get()


@pytest.mark.asyncio
async def test_awrap_tool_call_exceeds_max_attempts(middleware):
    """Test that awrap_tool_call returns engine limit reached message when max attempts exceeded."""
    middleware.max_attempts = 2
    _per_tool_errors_var.set({"bash_code_execute_tool": 2})

    request = ToolCallRequest(
        tool_call={
            "name": "bash_code_execute_tool",
            "args": {"command": "ls"},
            "id": "call_err_limit",
        },
        tool=MagicMock(),
        state={},
        runtime=MagicMock(),
    )

    async def handler(req):
        raise ValueError("Permission denied")

    result = await middleware.awrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert result.name == "bash_code_execute_tool"
    assert result.tool_call_id == "call_err_limit"
    assert result.status == "error"
    assert "Engine limit reached: max_replan_attempts exceeded" in result.content
    assert _per_tool_errors_var.get()["bash_code_execute_tool"] == 3


@pytest.mark.asyncio
@patch(
    "myrm_agent_harness.agent.security.guards.loop_suggestions.core.get_tool_suggestion"
)
async def test_per_tool_counting_isolation(mock_get_suggestion, middleware):
    """Verify that a success on tool_a does NOT reset tool_b's error count."""
    mock_get_suggestion.return_value = "Check syntax."
    middleware.max_attempts = 3

    _per_tool_errors_var.set({"bash_code_execute_tool": 3})

    success_request = ToolCallRequest(
        tool_call={"name": "skill_select_tool", "args": {}, "id": "call_ok"},
        tool=MagicMock(),
        state={},
        runtime=MagicMock(),
    )

    async def ok_handler(req):
        return ToolMessage(content="ok", name="skill_select_tool", tool_call_id="call_ok")

    await middleware.awrap_tool_call(success_request, ok_handler)
    assert _per_tool_errors_var.get().get("bash_code_execute_tool") == 3

    fail_request = ToolCallRequest(
        tool_call={"name": "bash_code_execute_tool", "args": {"command": "echo"}, "id": "call_f"},
        tool=MagicMock(),
        state={},
        runtime=MagicMock(),
    )

    async def fail_handler(req):
        raise SyntaxError("bad code")

    result = await middleware.awrap_tool_call(fail_request, fail_handler)
    assert _per_tool_errors_var.get()["bash_code_execute_tool"] == 4
    assert "Engine limit reached" in result.content
