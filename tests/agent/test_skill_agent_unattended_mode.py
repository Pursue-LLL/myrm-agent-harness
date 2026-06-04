"""Tests for SkillAgent unattended mode behavior."""

from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import tool

from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.agent.types import AgentRuntimeConfig


@tool
def regular_tool() -> str:
    """A regular tool."""
    return "ok"


@tool
def interactive_tool() -> str:
    """An interactive tool."""
    return "ask"


# Mark the interactive tool with tags
interactive_tool.tags = ["interactive"]


class MockConfig(AgentRuntimeConfig):
    unattended: bool = False


@pytest.mark.asyncio
async def test_build_tools_filters_interactive_when_unattended():
    """When config.unattended is True, interactive tools are skipped."""
    mock_llm = AsyncMock()

    agent = SkillAgent(
        llm=mock_llm,
        tools=[regular_tool, interactive_tool],
    )
    from unittest.mock import MagicMock
    agent.config = MagicMock()
    agent.config.unattended = True

    agent.skill_backend = AsyncMock()
    agent.skill_backend.list_skills.return_value = []

    tools = await agent._build_tools()

    tool_names = [t.name for t in tools]
    assert "regular_tool" in tool_names
    assert "interactive_tool" not in tool_names, "Interactive tool should be filtered in unattended mode"


@pytest.mark.asyncio
async def test_build_tools_keeps_interactive_when_attended():
    """When config.unattended is False, interactive tools are retained."""
    mock_llm = AsyncMock()

    agent = SkillAgent(
        llm=mock_llm,
        tools=[regular_tool, interactive_tool],
    )
    from unittest.mock import MagicMock
    agent.config = MagicMock()
    agent.config.unattended = False

    agent.skill_backend = AsyncMock()
    agent.skill_backend.list_skills.return_value = []

    tools = await agent._build_tools()

    tool_names = [t.name for t in tools]
    assert "regular_tool" in tool_names
    assert "interactive_tool" in tool_names, "Interactive tool should be kept when attended"
