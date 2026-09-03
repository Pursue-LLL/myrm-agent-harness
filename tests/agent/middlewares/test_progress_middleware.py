"""Tests for progress_middleware — todo blueprint injection into last HumanMessage."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.meta_tools.progress.schemas import (
    TodoItem,
    TodoStatus,
    TodoStore,
)
from myrm_agent_harness.agent.middlewares.progress_middleware import progress_middleware


@pytest.mark.asyncio
async def test_no_store_passthrough() -> None:
    middleware = progress_middleware(AsyncMock(return_value=None))
    request = ModelRequest(model=AsyncMock(), messages=[HumanMessage(content="hi")])
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await middleware.awrap_model_call(request, handler)
    handler.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_no_todos_passthrough() -> None:
    middleware = progress_middleware(
        AsyncMock(return_value=TodoStore(goal="g", todos=[]))
    )
    request = ModelRequest(model=AsyncMock(), messages=[HumanMessage(content="hi")])
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await middleware.awrap_model_call(request, handler)
    handler.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_all_completed_passthrough() -> None:
    store = TodoStore(
        goal="g", todos=[TodoItem(id="t1", content="done", status=TodoStatus.COMPLETED)]
    )
    middleware = progress_middleware(AsyncMock(return_value=store))
    request = ModelRequest(model=AsyncMock(), messages=[HumanMessage(content="hi")])
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await middleware.awrap_model_call(request, handler)
    handler.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_injects_into_last_string_human_message() -> None:
    store = TodoStore(
        goal="Build feature",
        todos=[
            TodoItem(id="t1", content="step one"),
            TodoItem(id="t2", content="step two"),
        ],
    )
    middleware = progress_middleware(AsyncMock(return_value=store))
    request = ModelRequest(
        model=AsyncMock(),
        messages=[
            HumanMessage(content="hi"),
            AIMessage(content="ok"),
            HumanMessage(content="do it"),
        ],
    )
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await middleware.awrap_model_call(request, handler)
    passed_request = handler.await_args.args[0]
    last_msg = passed_request.messages[-1]
    assert isinstance(last_msg, HumanMessage)
    assert "t1" in last_msg.content
    assert "Build feature" in last_msg.content


@pytest.mark.asyncio
async def test_injects_into_list_content_human_message() -> None:
    store = TodoStore(goal="g", todos=[TodoItem(id="t1", content="step one")])
    middleware = progress_middleware(AsyncMock(return_value=store))
    request = ModelRequest(
        model=AsyncMock(),
        messages=[HumanMessage(content=[{"type": "text", "text": "hi"}])],
    )
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await middleware.awrap_model_call(request, handler)
    passed_request = handler.await_args.args[0]
    last_msg = passed_request.messages[-1]
    assert isinstance(last_msg.content, list)
    assert any(
        part.get("type") == "text" and "t1" in part["text"] for part in last_msg.content
    )


@pytest.mark.asyncio
async def test_appends_when_no_human_message() -> None:
    store = TodoStore(goal="g", todos=[TodoItem(id="t1", content="step one")])
    middleware = progress_middleware(AsyncMock(return_value=store))
    request = ModelRequest(
        model=AsyncMock(),
        messages=[AIMessage(content="only ai")],
    )
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await middleware.awrap_model_call(request, handler)
    passed_request = handler.await_args.args[0]
    last_msg = passed_request.messages[-1]
    assert isinstance(last_msg, HumanMessage)
    assert "t1" in last_msg.content


@pytest.mark.asyncio
async def test_workspace_root_from_runtime_context() -> None:
    store = TodoStore(goal="g", todos=[TodoItem(id="t1", content="step one")])
    get_todos = AsyncMock(return_value=store)
    middleware = progress_middleware(get_todos)
    runtime = type(
        "Runtime",
        (),
        {"context": {"workspace_root": "/tmp/ws"}},
    )()
    request = ModelRequest(
        model=AsyncMock(), messages=[HumanMessage(content="hi")], runtime=runtime
    )
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await middleware.awrap_model_call(request, handler)
    assert get_todos.await_args.args[0] == "/tmp/ws"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_idempotent_strip_on_repeated_calls() -> None:
    store = TodoStore(goal="g", todos=[TodoItem(id="t1", content="step one")])
    middleware = progress_middleware(AsyncMock(return_value=store))
    initial_human_msg = HumanMessage(
        content=(
            "original query\n\n"
            "[SYSTEM INSTRUCTION]\n"
            "## Task progress (active todos)\n"
            "**Goal:** old goal\n"
            "> [pending] t0: old step\n"
            "Current focus: `t0` — old step\n"
            "Mark items completed with `todo_write(merge=true)` as you finish them."
        )
    )
    request = ModelRequest(model=AsyncMock(), messages=[initial_human_msg])
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await middleware.awrap_model_call(request, handler)
    passed_request = handler.await_args.args[0]
    last_msg = passed_request.messages[-1]
    assert isinstance(last_msg, HumanMessage)
    # Ensure "original query" is present and only ONE "[SYSTEM INSTRUCTION]" block exists
    assert last_msg.content.startswith("original query")
    assert last_msg.content.count("[SYSTEM INSTRUCTION]") == 1
    assert "t1" in last_msg.content
    assert "t0" not in last_msg.content


@pytest.mark.asyncio
async def test_compact_focus_view_for_many_tasks() -> None:
    store = TodoStore(
        goal="Big refactor",
        todos=[
            TodoItem(id="t1", content="done 1", status=TodoStatus.COMPLETED),
            TodoItem(id="t2", content="done 2", status=TodoStatus.COMPLETED),
            TodoItem(id="t3", content="done 3", status=TodoStatus.COMPLETED),
            TodoItem(id="t4", content="in progress 4", status=TodoStatus.IN_PROGRESS),
            TodoItem(id="t5", content="pending 5", status=TodoStatus.PENDING),
            TodoItem(id="t6", content="pending 6", status=TodoStatus.PENDING),
            TodoItem(id="t7", content="pending 7", status=TodoStatus.PENDING),
            TodoItem(id="t8", content="pending 8", status=TodoStatus.PENDING),
        ],
    )
    middleware = progress_middleware(AsyncMock(return_value=store))
    request = ModelRequest(model=AsyncMock(), messages=[HumanMessage(content="start")])
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await middleware.awrap_model_call(request, handler)
    passed_request = handler.await_args.args[0]
    last_msg = passed_request.messages[-1]
    assert isinstance(last_msg, HumanMessage)
    # Check compact summary
    assert "[✓] 3 completed" in last_msg.content
    assert "> [in_progress] t4: in progress 4" in last_msg.content
    assert "Current focus: `t4` — in progress 4" in last_msg.content
    assert "... and 1 more pending task(s)" in last_msg.content


@pytest.mark.asyncio
async def test_blocked_task_focus_skip_and_warning() -> None:
    store = TodoStore(
        goal="Handle payments",
        todos=[
            TodoItem(id="t1", content="fetch api key", status=TodoStatus.BLOCKED),
            TodoItem(id="t2", content="create local db", status=TodoStatus.PENDING),
        ],
    )
    middleware = progress_middleware(AsyncMock(return_value=store))
    request = ModelRequest(model=AsyncMock(), messages=[HumanMessage(content="start")])
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await middleware.awrap_model_call(request, handler)
    passed_request = handler.await_args.args[0]
    last_msg = passed_request.messages[-1]
    assert isinstance(last_msg, HumanMessage)
    # Check that focus skipped blocked t1 and targeted pending t2
    assert "Current focus: `t2` — create local db" in last_msg.content
    assert "[BLOCKED TASKS DETECTED]" in last_msg.content


@pytest.mark.asyncio
async def test_compact_summary_with_cancelled_items() -> None:
    store = TodoStore(
        goal="Big refactor with cancelled",
        todos=[
            TodoItem(id="t1", content="done 1", status=TodoStatus.COMPLETED),
            TodoItem(id="t2", content="cancel 2", status=TodoStatus.CANCELLED),
            TodoItem(id="t3", content="cancel 3", status=TodoStatus.CANCELLED),
            TodoItem(id="t4", content="in progress 4", status=TodoStatus.IN_PROGRESS),
            TodoItem(id="t5", content="pending 5", status=TodoStatus.PENDING),
        ],
    )
    middleware = progress_middleware(AsyncMock(return_value=store))
    request = ModelRequest(model=AsyncMock(), messages=[HumanMessage(content="start")])
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await middleware.awrap_model_call(request, handler)
    passed_request = handler.await_args.args[0]
    last_msg = passed_request.messages[-1]
    assert isinstance(last_msg, HumanMessage)
    assert "[✓] 1 completed, 2 cancelled" in last_msg.content


@pytest.mark.asyncio
async def test_list_content_with_previous_progress_stripped() -> None:
    store = TodoStore(
        goal="Strip check",
        todos=[TodoItem(id="t1", content="step one", status=TodoStatus.PENDING)],
    )
    middleware = progress_middleware(AsyncMock(return_value=store))
    old_content = (
        "[SYSTEM INSTRUCTION]\n"
        "## Task progress (active todos)\n"
        "**Goal:** old goal\n"
        "> [pending] t0: old step\n"
    )
    request = ModelRequest(
        model=AsyncMock(),
        messages=[
            HumanMessage(
                content=[
                    {"type": "text", "text": f"User query text\n\n{old_content}"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ]
            )
        ],
    )
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await middleware.awrap_model_call(request, handler)
    passed_request = handler.await_args.args[0]
    last_msg = passed_request.messages[-1]
    assert isinstance(last_msg.content, list)
    text_parts = [p for p in last_msg.content if p.get("type") == "text"]
    assert len(text_parts) == 2
    assert text_parts[0]["text"] == "User query text"
    assert "t1" in text_parts[1]["text"]
    assert "t0" not in text_parts[0]["text"]



