"""Unit tests for transient side-channel sub-inquiry engine (/btw).

Verifies:
1. Pure read-only background context message construction without reference leakage.
2. Zero-pollution execution invariant: parent_messages is NEVER mutated or appended.
3. Metadata tracking: latency, tokens, timestamp, and markdown note card formatting.
4. Fault tolerance when the underlying model invocation fails.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.runtime.context.transient_sub_inquiry import (
    TransientInquiryRequest,
    build_transient_context_messages,
    execute_transient_sub_inquiry,
)


def test_build_transient_context_messages() -> None:
    parent_messages = [
        SystemMessage(content="You are a principal engineer."),
        HumanMessage(content="Please build the user auth service."),
        AIMessage(content="I am setting up JWT tokens and database schema."),
    ]
    initial_len = len(parent_messages)

    req = TransientInquiryRequest(
        question="What database are we using?",
        parent_messages=parent_messages,
        max_context_turns=2,
    )

    transient_list = build_transient_context_messages(req)

    # 1. Parent list must NOT be mutated
    assert len(parent_messages) == initial_len

    # 2. Transient list must have system prompt, recent 2 messages, and the side inquiry
    assert len(transient_list) == 4
    assert isinstance(transient_list[0], SystemMessage)
    assert "side-channel" in transient_list[0].content

    # Last message is the side inquiry
    assert "[Side Inquiry]: What database are we using?" in str(transient_list[-1].content)


@pytest.mark.asyncio
async def test_execute_transient_sub_inquiry_success() -> None:
    parent_messages = [
        HumanMessage(content="Working on task A"),
        AIMessage(content="Completed task A"),
    ]
    initial_len = len(parent_messages)

    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = AIMessage(
        content="The port default is 8080.",
        usage_metadata={"input_tokens": 30, "output_tokens": 12, "total_tokens": 42},
    )

    req = TransientInquiryRequest(
        question="What is the default port?",
        parent_messages=parent_messages,
    )

    response = await execute_transient_sub_inquiry(req, mock_llm)

    # Invariant assertions
    assert response.parent_context_polluted is False
    assert len(parent_messages) == initial_len
    assert response.answer == "The port default is 8080."
    assert response.tokens_used == 42
    assert response.latency_ms >= 0.0
    assert response.timestamp != ""

    # Markdown rendering verification
    md = response.to_markdown()
    assert "Side Inquiry (/btw)" in md
    assert "The port default is 8080." in md
    assert "100% Isolated" in md


@pytest.mark.asyncio
async def test_execute_transient_sub_inquiry_llm_failure_tolerance() -> None:
    parent_messages = [HumanMessage(content="Initial message")]
    initial_len = len(parent_messages)

    mock_llm = AsyncMock()
    mock_llm.ainvoke.side_effect = RuntimeError("Rate limit exceeded")

    req = TransientInquiryRequest(
        question="Quick check",
        parent_messages=parent_messages,
    )

    response = await execute_transient_sub_inquiry(req, mock_llm)

    # Invariant holds even on model error
    assert response.parent_context_polluted is False
    assert len(parent_messages) == initial_len
    assert "Error during side inquiry: Rate limit exceeded" in response.answer
