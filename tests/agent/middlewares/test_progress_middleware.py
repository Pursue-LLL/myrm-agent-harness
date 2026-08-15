"""Tests for progress_middleware — todo blueprint injection into last HumanMessage."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.meta_tools.progress.schemas import TodoItem, TodoStatus, TodoStore
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
    middleware = progress_middleware(AsyncMock(return_value=TodoStore(goal="g", todos=[])))
    request = ModelRequest(model=AsyncMock(), messages=[HumanMessage(content="hi")])
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await middleware.awrap_model_call(request, handler)
    handler.assert_awaited_once_with(request)


@pytest.mark.asyncio
async def test_all_completed_passthrough() -> None:
    store = TodoStore(goal="g", todos=[TodoItem(id="t1", content="done", status=TodoStatus.COMPLETED)])
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
        messages=[HumanMessage(content="hi"), AIMessage(content="ok"), HumanMessage(content="do it")],
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
    assert any(part.get("type") == "text" and "t1" in part["text"] for part in last_msg.content)


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
    request = ModelRequest(model=AsyncMock(), messages=[HumanMessage(content="hi")], runtime=runtime)
    handler = AsyncMock(return_value=ModelResponse(result=[]))
    await middleware.awrap_model_call(request, handler)
    assert get_todos.await_args.args[0] == "/tmp/ws"
    handler.assert_awaited_once()
