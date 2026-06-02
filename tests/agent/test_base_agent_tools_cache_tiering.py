"""Test base_agent.py add_tools cache tiering."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.base_agent import BaseAgent


class DummyTool(BaseTool):
    name: str = ""
    description: str = "dummy tool"

    def _run(self, *args, **kwargs):
        pass

    async def _arun(self, *args, **kwargs):
        pass


@pytest.fixture
def mock_agent():
    # We don't need a fully initialized agent, just enough to test add_tools.
    agent = BaseAgent.__new__(BaseAgent)
    agent.user_tools = []
    agent._cached_tools = None
    agent._tools_initialized = False

    # Mock LLM and config
    agent.llm = MagicMock()
    agent.config = MagicMock()
    agent.config.parallel_tool_calls = False
    agent.checkpointer = None
    agent.context_schema = None
    agent._cached_system_prompt = "system"
    agent._cached_middlewares = []

    from myrm_agent_harness.agent.tool_management import ToolRegistry
    agent._tool_registry = ToolRegistry()

    return agent


@pytest.mark.asyncio
async def test_add_tools_sorting_when_cached_is_none(mock_agent):
    """Test that add_tools sorts tools correctly when _cached_tools is None."""
    t1 = DummyTool(name="skill_manage_tool")  # EXTENDED
    t2 = DummyTool(name="bash_code_execute_tool")  # CORE
    t3 = DummyTool(name="web_search_tool")  # COMMON

    # Mock create_agent to prevent errors from LangGraph compilation
    with patch("myrm_agent_harness.agent.base_agent.create_agent"):
        mock_agent.add_tools([t1, t2, t3])

    assert len(mock_agent.user_tools) == 3
    # Expect order: CORE, COMMON, EXTENDED
    assert mock_agent.user_tools[0].name == "bash_code_execute_tool"
    assert mock_agent.user_tools[1].name == "web_search_tool"
    assert mock_agent.user_tools[2].name == "skill_manage_tool"


@pytest.mark.asyncio
async def test_add_tools_sorting_when_cached_exists(mock_agent):
    """Test that add_tools sorts tools correctly when _cached_tools already exists."""
    t1 = DummyTool(name="bash_code_execute_tool")  # CORE
    mock_agent._cached_tools = [t1]

    t2 = DummyTool(name="skill_select_tool")  # EXTENDED
    t3 = DummyTool(name="web_search_tool")  # COMMON
    t4 = DummyTool(name="file_read_tool")  # CORE

    with patch("myrm_agent_harness.agent.base_agent.create_agent"):
        mock_agent.add_tools([t2, t3, t4])

    assert len(mock_agent._cached_tools) == 4
    # Expect order: CORE, CORE, COMMON, EXTENDED
    # Also alphabetized within layers: bash_code_execute_tool, file_read_tool
    assert mock_agent._cached_tools[0].name == "bash_code_execute_tool"
    assert mock_agent._cached_tools[1].name == "file_read_tool"
    assert mock_agent._cached_tools[2].name == "web_search_tool"
    assert mock_agent._cached_tools[3].name == "skill_select_tool"
