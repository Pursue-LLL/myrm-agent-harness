"""Unit tests for commit_stage_tool."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.commit_stage_tool import create_commit_stage_tool


class MockStats:
    def __init__(self, input_tokens: int):
        self.token_usage = type("MockUsage", (), {"total_tokens": input_tokens})()


class MockAgent:
    def __init__(self, input_tokens: int = 0, last_commit: int = 0, session_tokens: int = 0):
        self._last_run_stats = MockStats(input_tokens)
        self._last_stage_commit_tokens = last_commit
        self._last_context: dict | None = (
            {"session_total_tokens": session_tokens} if session_tokens else {}
        )


_TOOL_INPUT = {
    "stage_summary": "Completed testing.",
    "next_stage_plan": "Write more tests.",
    "active_task": "Write tests.",
    "unresolved_issues": [],
}


@pytest.mark.asyncio
async def test_commit_stage_tool_success():
    """Test successful commit stage when throttle is passed."""
    agent = MockAgent(input_tokens=6000, last_commit=0)
    tool = create_commit_stage_tool(agent)

    with patch(
        "myrm_agent_harness.agent.meta_tools.commit_stage_tool._persist_working_state",
        new_callable=AsyncMock,
    ):
        result = await tool.ainvoke(_TOOL_INPUT)

    assert "Success" in result
    assert agent._last_context.get("active_stage_commit_flag") is True
    assert agent._last_stage_commit_tokens == 6000
    assert "active_stage_summary_hint" in agent._last_context


@pytest.mark.asyncio
async def test_commit_stage_tool_success_session_tokens():
    """Test successful commit stage with session total tokens."""
    agent = MockAgent(input_tokens=10, session_tokens=6000, last_commit=0)
    tool = create_commit_stage_tool(agent)

    with patch(
        "myrm_agent_harness.agent.meta_tools.commit_stage_tool._persist_working_state",
        new_callable=AsyncMock,
    ):
        result = await tool.ainvoke(_TOOL_INPUT)

    assert "Success" in result
    assert agent._last_stage_commit_tokens == 6000


@pytest.mark.asyncio
async def test_commit_stage_tool_throttled():
    """Test throttle prevents commit stage if not enough tokens passed."""
    agent = MockAgent(input_tokens=2000, last_commit=0)
    tool = create_commit_stage_tool(agent)

    result = await tool.ainvoke(_TOOL_INPUT)

    assert "Throttled" in result
    assert agent._last_context.get("active_stage_commit_flag") is None
    assert agent._last_stage_commit_tokens == 0


@pytest.mark.asyncio
async def test_commit_stage_tool_no_agent():
    """Test graceful failure when agent instance is not provided."""
    tool = create_commit_stage_tool(None)

    result = await tool.ainvoke(_TOOL_INPUT)

    assert "Error" in result


@pytest.mark.asyncio
async def test_commit_stage_tool_no_dict_context():
    """Test graceful failure when parent _last_context is not a dict."""
    agent = MockAgent(input_tokens=6000, last_commit=0)
    agent._last_context = None
    tool = create_commit_stage_tool(agent)

    result = await tool.ainvoke(_TOOL_INPUT)

    assert "Error" in result
