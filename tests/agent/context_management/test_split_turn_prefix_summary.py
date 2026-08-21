"""Tests for Pi-style compaction split turn prefix summarization."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.schemas import ContextConfig, StructuredSummary
from myrm_agent_harness.agent.context_management.strategies.summary.summarizer import (
    _summarize_full_with_audit,
    _summarize_incremental_with_audit,
    generate_structured_summary,
)
from myrm_agent_harness.agent.context_management.strategies.summary.summary_builder import (
    TailExtractionResult,
    extract_recent_messages_with_split_context,
)
from myrm_agent_harness.agent.context_management.strategies.summary.summary_prompts import (
    SPLIT_TURN_PROMPT_SUFFIX,
)


def test_split_turn_detection_and_extraction() -> None:
    """Verify that when a turn exceeds the recent tail budget, split context is cleanly extracted."""
    human_msg = HumanMessage(content="Refactor the entire auth subsystem")
    ai1 = AIMessage(content="Checking files", tool_calls=[{"name": "list_dir", "args": {}, "id": "call_1"}])
    tool1 = ToolMessage(content="auth.py, tokens.py, login.py", name="list_dir", tool_call_id="call_1")
    ai2 = AIMessage(content="Reading auth.py", tool_calls=[{"name": "read_file", "args": {"p": "auth.py"}, "id": "call_2"}])
    tool2 = ToolMessage(content="class AuthManager: pass", name="read_file", tool_call_id="call_2")
    ai3 = AIMessage(content="Modifying auth.py", tool_calls=[{"name": "edit_file", "args": {"p": "auth.py"}, "id": "call_3"}])
    tool3 = ToolMessage(content="OK", name="edit_file", tool_call_id="call_3")

    messages = [human_msg, ai1, tool1, ai2, tool2, ai3, tool3]

    # Set budget small enough that only (ai3, tool3) fits in recent tail
    res: TailExtractionResult = extract_recent_messages_with_split_context(messages, tail_budget_tokens=30)

    assert res.is_split_turn is True
    assert res.split_human_message == human_msg
    assert len(res.turn_prefix_messages) == 5
    assert res.turn_prefix_messages[0] == human_msg
    assert res.turn_prefix_messages[1] == ai1
    assert res.turn_prefix_messages[2] == tool1
    assert res.turn_prefix_messages[3] == ai2
    assert res.turn_prefix_messages[4] == tool2
    assert len(res.messages) == 2
    assert res.messages[0] == ai3
    assert res.messages[1] == tool3


@pytest.mark.asyncio
async def test_summarize_full_includes_split_turn_prefix_in_prompt() -> None:
    """Ensure full summarization injects SPLIT_TURN_PROMPT_SUFFIX when turn_prefix_messages exist."""
    human_msg = HumanMessage(content="User active query")
    prefix_ai = AIMessage(content="Prefix action")
    turn_prefix = [human_msg, prefix_ai]

    mock_llm = MagicMock()
    mock_structured_llm = AsyncMock()
    mock_structured_llm.ainvoke.return_value = StructuredSummary(
        user_goal="User active query",
        active_task="User active query",
        completed_actions=["Prefix action done"],
        active_state="Mid-execution",
    )
    mock_llm.with_structured_output.return_value = mock_structured_llm

    with patch("myrm_agent_harness.agent.context_management.strategies.summary.summarizer._invoke_summary") as mock_invoke:
        mock_invoke.return_value = StructuredSummary(
            user_goal="User active query",
            active_task="User active query",
            completed_actions=["Prefix action done"],
            active_state="Mid-execution",
        )

        summary = await _summarize_full_with_audit(
            llm=mock_llm,
            messages=[human_msg, prefix_ai],
            dump_path="",
            entities=set(),
            turn_prefix_messages=turn_prefix,
        )

        assert mock_invoke.called
        call_args = mock_invoke.call_args
        prompt_used = call_args[0][3]  # 4th arg is prompt
        assert "ACTIVE TURN PREFIX CONTEXT (SPLIT TURN)" in prompt_used
        assert "User active query" in prompt_used
        assert "Prefix action" in prompt_used
        assert summary.active_task == "User active query"


@pytest.mark.asyncio
async def test_summarize_incremental_includes_split_turn_prefix_in_prompt() -> None:
    """Ensure incremental summarization injects SPLIT_TURN_PROMPT_SUFFIX when turn_prefix_messages exist."""
    existing_summary = StructuredSummary(
        user_goal="Build features",
        completed_actions=["Old feature done"],
    )
    human_msg = HumanMessage(content="Active ongoing instruction")
    turn_prefix = [human_msg]

    mock_llm = MagicMock()
    with patch("myrm_agent_harness.agent.context_management.strategies.summary.summarizer._invoke_summary") as mock_invoke:
        mock_invoke.return_value = StructuredSummary(
            user_goal="Build features + Active instruction",
            active_task="Active ongoing instruction",
            completed_actions=["Old feature done"],
        )

        summary = await _summarize_incremental_with_audit(
            llm=mock_llm,
            existing_summary=existing_summary,
            new_messages=[human_msg],
            dump_path="",
            all_messages=[human_msg],
            entities=set(),
            turn_prefix_messages=turn_prefix,
        )

        assert mock_invoke.called
        prompt_used = mock_invoke.call_args[0][3]
        assert "ACTIVE TURN PREFIX CONTEXT (SPLIT TURN)" in prompt_used
        assert "Active ongoing instruction" in prompt_used
        assert summary.active_task == "Active ongoing instruction"


@pytest.mark.asyncio
async def test_generate_structured_summary_end_to_end_split_turn() -> None:
    """End-to-end integration test verifying generate_structured_summary with a split turn."""
    human_msg = HumanMessage(content="Run complex task step by step")
    ai1 = AIMessage(content="Step 1", tool_calls=[{"name": "tool1", "args": {}, "id": "c1"}])
    t1 = ToolMessage(content="Result 1 " * 100, name="tool1", tool_call_id="c1")
    ai2 = AIMessage(content="Step 2", tool_calls=[{"name": "tool2", "args": {}, "id": "c2"}])
    t2 = ToolMessage(content="Result 2 " * 100, name="tool2", tool_call_id="c2")

    messages = [
        SystemMessage(content="System prompt prefix"),
        human_msg,
        ai1,
        t1,
        ai2,
        t2,
    ]

    mock_llm = MagicMock()
    with patch("myrm_agent_harness.agent.context_management.strategies.summary.summarizer._invoke_summary") as mock_invoke:
        mock_invoke.return_value = StructuredSummary(
            user_goal="Run complex task step by step",
            active_task="Run complex task step by step",
            completed_actions=["Step 1 finished"],
            active_state="Step 2 executing",
        )

        cfg = ContextConfig(max_context_tokens=1000, tail_budget_ratio=0.2)
        new_msgs, summary = await generate_structured_summary(
            messages=messages,
            llm=mock_llm,
            config=cfg,
        )

        assert mock_invoke.called
        prompt_used = mock_invoke.call_args[0][3]
        assert "ACTIVE TURN PREFIX CONTEXT (SPLIT TURN)" in prompt_used
        assert summary.active_task == "Run complex task step by step"
        # Verify message structure: [SystemMessage, HumanMessage, AIMessage, SummaryMessage, recent_messages...]
        assert any(isinstance(m, SystemMessage) for m in new_msgs)
        assert any("[STRUCTURED SUMMARY]" in str(m.content) for m in new_msgs)
