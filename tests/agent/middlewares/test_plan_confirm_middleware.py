"""Test plan_confirm_middleware.py."""

from unittest.mock import MagicMock, patch

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.middlewares.plan_confirm_middleware import (
    MIN_ITEMS_FOR_CONFIRM,
    PlanConfirmMiddleware,
    _plan_confirmed_var,
    reset_plan_confirm_state,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_plan_confirm_state()
    yield
    reset_plan_confirm_state()


@pytest.fixture
def middleware():
    return PlanConfirmMiddleware()


def _make_request(tool_name: str = "todo_write", args: dict | None = None) -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": tool_name, "args": args or {}, "id": "call_1"},
        tool=MagicMock(),
        state={},
        runtime=MagicMock(),
    )


def _make_todos(n: int) -> list[dict]:
    return [{"id": f"t{i}", "content": f"Task {i}", "status": "pending"} for i in range(n)]


async def _passthrough_handler(req: ToolCallRequest) -> ToolMessage:
    return ToolMessage(content="ok", name=req.tool_call["name"], tool_call_id=req.tool_call["id"])


@pytest.mark.asyncio
async def test_non_todo_write_passes_through(middleware):
    request = _make_request("some_other_tool")
    result = await middleware.awrap_tool_call(request, _passthrough_handler)
    assert isinstance(result, ToolMessage)
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_merge_true_passes_through(middleware):
    request = _make_request(args={"merge": True, "todos": _make_todos(5)})
    with patch(
        "myrm_agent_harness.agent.middlewares.plan_confirm_middleware._is_plan_confirm_enabled",
        return_value=True,
    ):
        result = await middleware.awrap_tool_call(request, _passthrough_handler)
    assert isinstance(result, ToolMessage)


@pytest.mark.asyncio
async def test_few_items_passes_through_and_marks_confirmed(middleware):
    request = _make_request(args={"merge": False, "todos": _make_todos(2)})
    with patch(
        "myrm_agent_harness.agent.middlewares.plan_confirm_middleware._is_plan_confirm_enabled",
        return_value=True,
    ):
        result = await middleware.awrap_tool_call(request, _passthrough_handler)
    assert isinstance(result, ToolMessage)
    assert _plan_confirmed_var.get() is True


@pytest.mark.asyncio
async def test_plan_confirm_disabled_passes_through(middleware):
    request = _make_request(args={"merge": False, "todos": _make_todos(5)})
    with patch(
        "myrm_agent_harness.agent.middlewares.plan_confirm_middleware._is_plan_confirm_enabled",
        return_value=False,
    ):
        result = await middleware.awrap_tool_call(request, _passthrough_handler)
    assert isinstance(result, ToolMessage)


@pytest.mark.asyncio
async def test_already_confirmed_passes_through(middleware):
    _plan_confirmed_var.set(True)
    request = _make_request(args={"merge": False, "todos": _make_todos(5)})
    with patch(
        "myrm_agent_harness.agent.middlewares.plan_confirm_middleware._is_plan_confirm_enabled",
        return_value=True,
    ):
        result = await middleware.awrap_tool_call(request, _passthrough_handler)
    assert isinstance(result, ToolMessage)


@pytest.mark.asyncio
async def test_interrupt_triggered_on_valid_plan(middleware):
    """When all conditions are met, interrupt() should be called with correct payload."""
    captured_payload: dict = {}

    def fake_interrupt(payload):
        captured_payload.update(payload)
        return {"action": "confirm"}

    todos = _make_todos(MIN_ITEMS_FOR_CONFIRM)
    request = _make_request(args={"merge": False, "todos": todos})

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.plan_confirm_middleware._is_plan_confirm_enabled",
            return_value=True,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.plan_confirm_middleware.interrupt",
            side_effect=fake_interrupt,
        ),
    ):
        result = await middleware.awrap_tool_call(request, _passthrough_handler)

    assert isinstance(result, ToolMessage)
    assert captured_payload["action_type"] == "plan_confirm"
    assert captured_payload["tool_name"] == "todo_write"
    assert captured_payload["total_items"] == MIN_ITEMS_FOR_CONFIRM


@pytest.mark.asyncio
async def test_interrupt_payload_structure(middleware):
    """Verify the interrupt payload contains expected fields including goal."""
    captured_payload: dict = {}

    def fake_interrupt(payload):
        captured_payload.update(payload)
        return {"action": "confirm"}

    todos = _make_todos(4)
    request = _make_request(args={"merge": False, "todos": todos, "goal": "Build feature X"})

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.plan_confirm_middleware._is_plan_confirm_enabled",
            return_value=True,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.plan_confirm_middleware.interrupt",
            side_effect=fake_interrupt,
        ),
    ):
        await middleware.awrap_tool_call(request, _passthrough_handler)

    assert captured_payload["action_type"] == "plan_confirm"
    assert captured_payload["tool_name"] == "todo_write"
    assert captured_payload["total_items"] == 4
    assert captured_payload["goal"] == "Build feature X"
    assert len(captured_payload["plan_items"]) == 4
    assert captured_payload["plan_items"][0]["id"] == "t0"
    assert captured_payload["plan_items"][0]["content"] == "Task 0"


@pytest.mark.asyncio
async def test_confirm_action_proceeds(middleware):
    """When resume returns action=confirm, handler should be called."""
    todos = _make_todos(MIN_ITEMS_FOR_CONFIRM)
    request = _make_request(args={"merge": False, "todos": todos})

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.plan_confirm_middleware._is_plan_confirm_enabled",
            return_value=True,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.plan_confirm_middleware.interrupt",
            return_value={"action": "confirm"},
        ),
    ):
        result = await middleware.awrap_tool_call(request, _passthrough_handler)
    assert isinstance(result, ToolMessage)
    assert _plan_confirmed_var.get() is True


@pytest.mark.asyncio
async def test_skip_action_proceeds(middleware):
    """When resume returns action=skip, handler should be called."""
    todos = _make_todos(MIN_ITEMS_FOR_CONFIRM)
    request = _make_request(args={"merge": False, "todos": todos})

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.plan_confirm_middleware._is_plan_confirm_enabled",
            return_value=True,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.plan_confirm_middleware.interrupt",
            return_value={"action": "skip"},
        ),
    ):
        result = await middleware.awrap_tool_call(request, _passthrough_handler)
    assert isinstance(result, ToolMessage)
    assert _plan_confirmed_var.get() is True


@pytest.mark.asyncio
async def test_edit_action_replaces_todos(middleware):
    """When resume returns action=edit with edited_todos, args should be updated."""
    original_todos = _make_todos(MIN_ITEMS_FOR_CONFIRM)
    edited = [{"id": "e1", "content": "Edited task", "status": "pending"}]
    request = _make_request(args={"merge": False, "todos": original_todos})

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.plan_confirm_middleware._is_plan_confirm_enabled",
            return_value=True,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.plan_confirm_middleware.interrupt",
            return_value={"action": "edit", "edited_todos": edited},
        ),
    ):
        result = await middleware.awrap_tool_call(request, _passthrough_handler)
    assert isinstance(result, ToolMessage)
    assert request.tool_call["args"]["todos"] == edited
    assert _plan_confirmed_var.get() is True


@pytest.mark.asyncio
async def test_second_plan_not_intercepted(middleware):
    """After first plan is confirmed, subsequent plans should pass through."""
    todos = _make_todos(MIN_ITEMS_FOR_CONFIRM)

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.plan_confirm_middleware._is_plan_confirm_enabled",
            return_value=True,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.plan_confirm_middleware.interrupt",
            return_value={"action": "confirm"},
        ),
    ):
        request1 = _make_request(args={"merge": False, "todos": todos})
        await middleware.awrap_tool_call(request1, _passthrough_handler)

    request2 = _make_request(args={"merge": False, "todos": _make_todos(10)})
    with patch(
        "myrm_agent_harness.agent.middlewares.plan_confirm_middleware._is_plan_confirm_enabled",
        return_value=True,
    ):
        result = await middleware.awrap_tool_call(request2, _passthrough_handler)
    assert isinstance(result, ToolMessage)


@pytest.mark.asyncio
async def test_non_dict_resume_value_proceeds(middleware):
    """If resume returns a non-dict value, treat as confirm."""
    todos = _make_todos(MIN_ITEMS_FOR_CONFIRM)
    request = _make_request(args={"merge": False, "todos": todos})

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.plan_confirm_middleware._is_plan_confirm_enabled",
            return_value=True,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.plan_confirm_middleware.interrupt",
            return_value="just_a_string",
        ),
    ):
        result = await middleware.awrap_tool_call(request, _passthrough_handler)
    assert isinstance(result, ToolMessage)
    assert _plan_confirmed_var.get() is True


@pytest.mark.asyncio
async def test_sync_wrap_raises(middleware):
    """Synchronous wrap_tool_call is not supported."""
    request = _make_request()
    with pytest.raises(NotImplementedError):
        middleware.wrap_tool_call(request, lambda r: None)
