"""Tests for ClarificationGuardMiddleware ask_question_tool batching rules."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.middlewares.clarification_guard_middleware import (
    ASK_QUESTION_TOOL_NAME,
    ClarificationGuardMiddleware,
)


def _ai_with_tool_calls(tool_calls: list[dict[str, object]]) -> AIMessage:
    return AIMessage(content="", tool_calls=tool_calls)


@pytest.mark.asyncio
async def test_no_op_when_ask_question_absent() -> None:
    middleware = ClarificationGuardMiddleware()
    state = {
        "messages": [
            HumanMessage(content="hi"),
            _ai_with_tool_calls(
                [{"name": "web_search_tool", "args": {"query": "x"}, "id": "call_1", "type": "tool_call"}]
            ),
        ]
    }
    result = await middleware.aafter_model(state, None)
    assert result is None


@pytest.mark.asyncio
async def test_single_ask_question_unchanged() -> None:
    middleware = ClarificationGuardMiddleware()
    ai_msg = _ai_with_tool_calls(
        [
            {
                "name": ASK_QUESTION_TOOL_NAME,
                "args": {"questions": [{"id": "q1", "prompt": "Which?"}]},
                "id": "call_clarify",
                "type": "tool_call",
            }
        ]
    )
    state = {"messages": [ai_msg]}
    result = await middleware.aafter_model(state, None)
    assert result is None
    assert len(ai_msg.tool_calls) == 1


@pytest.mark.asyncio
async def test_duplicate_ask_question_calls_blocked() -> None:
    middleware = ClarificationGuardMiddleware()
    ai_msg = _ai_with_tool_calls(
        [
            {
                "name": ASK_QUESTION_TOOL_NAME,
                "args": {"questions": [{"id": "q1", "prompt": "A?"}]},
                "id": "call_1",
                "type": "tool_call",
            },
            {
                "name": ASK_QUESTION_TOOL_NAME,
                "args": {"questions": [{"id": "q2", "prompt": "B?"}]},
                "id": "call_2",
                "type": "tool_call",
            },
        ]
    )
    state = {"messages": [ai_msg]}

    result = await middleware.aafter_model(state, None)
    assert result is not None
    messages = result["messages"]
    assert len(messages) == 2
    assert len(ai_msg.tool_calls) == 1
    assert ai_msg.tool_calls[0]["id"] == "call_1"

    blocked = messages[1]
    assert isinstance(blocked, ToolMessage)
    assert blocked.tool_call_id == "call_2"
    assert blocked.status == "error"
    assert "only one call per turn" in str(blocked.content)


@pytest.mark.asyncio
async def test_ask_question_blocks_coexisting_tools() -> None:
    middleware = ClarificationGuardMiddleware()
    ai_msg = _ai_with_tool_calls(
        [
            {
                "name": ASK_QUESTION_TOOL_NAME,
                "args": {"questions": [{"id": "q1", "prompt": "Scope?"}]},
                "id": "call_clarify",
                "type": "tool_call",
            },
            {
                "name": "web_search_tool",
                "args": {"query": "test"},
                "id": "call_search",
                "type": "tool_call",
            },
        ]
    )
    state = {"messages": [ai_msg]}

    result = await middleware.aafter_model(state, None)
    assert result is not None
    messages = result["messages"]
    assert len(ai_msg.tool_calls) == 1
    assert ai_msg.tool_calls[0]["name"] == ASK_QUESTION_TOOL_NAME

    blocked = messages[1]
    assert isinstance(blocked, ToolMessage)
    assert blocked.tool_call_id == "call_search"
    assert blocked.status == "error"
    assert "only tool in this turn" in str(blocked.content)
