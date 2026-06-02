from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from myrm_agent_harness.agent.sub_agents.planner import PlannerConfig
from myrm_agent_harness.agent.sub_agents.planner.planner_agent_tools import create_planner_tool


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="mock response"))
    return llm

@pytest.fixture
def mock_storage():
    storage = MagicMock()
    storage.get = AsyncMock(return_value=None)
    storage.set = AsyncMock()
    return storage

@pytest.mark.asyncio
async def test_create_planner_tool(mock_llm, mock_storage):
    config = PlannerConfig(output_format="markdown")
    tool = create_planner_tool(mock_llm, mock_storage, planner_config=config, available_skills=[("skill1", "desc1")])
    assert tool.name == "planner_tool"
    assert "Task planner" in tool.description

@pytest.mark.asyncio
async def test_planner_tool_create_action(mock_llm, mock_storage):
    with patch("myrm_agent_harness.agent.sub_agents.planner.PlannerAgent.create_plan", new_callable=AsyncMock) as mock_create:
        mock_plan = MagicMock()
        mock_plan.to_markdown.return_value = "markdown plan"
        mock_plan.to_line_format.return_value = "line plan"
        mock_plan.model_dump_json.return_value = "json plan"
        mock_plan.goal = "test goal"
        mock_plan.steps = [MagicMock(step_id="1", status="pending", description="desc")]
        mock_create.return_value = mock_plan

        config = PlannerConfig(output_format="markdown")
        tool = create_planner_tool(mock_llm, mock_storage, planner_config=config)

        # Test missing description
        result = await tool.ainvoke({"action": "create"})
        assert "Error: task_description is required" in result

        # Test success markdown
        result = await tool.ainvoke({"action": "create", "task_description": "do something"})
        assert result == "markdown plan"
        mock_create.assert_called_once_with("do something")

        # Test success json
        config_json = PlannerConfig(output_format="json")
        tool_json = create_planner_tool(mock_llm, mock_storage, planner_config=config_json)
        result = await tool_json.ainvoke({"action": "create", "task_description": "do something"})
        assert result == "json plan"

        # Test success line
        config_line = PlannerConfig(output_format="line")
        tool_line = create_planner_tool(mock_llm, mock_storage, planner_config=config_line)
        result = await tool_line.ainvoke({"action": "create", "task_description": "do something"})
        assert result == "line plan"

@pytest.mark.asyncio
async def test_planner_tool_update_action(mock_llm, mock_storage):
    with patch("myrm_agent_harness.agent.sub_agents.planner.PlannerAgent.get_current_plan", new_callable=AsyncMock) as mock_get, \
         patch("myrm_agent_harness.agent.sub_agents.planner.PlannerAgent.update_plan", new_callable=AsyncMock) as mock_update:

        mock_plan = MagicMock()
        mock_get.return_value = mock_plan

        mock_updated_plan = MagicMock()
        mock_updated_plan.to_summary.return_value = "plan summary"
        mock_update.return_value = mock_updated_plan

        tool = create_planner_tool(mock_llm, mock_storage)

        # Test update without alignment check when completing a step
        result = await tool.ainvoke({"action": "update", "completed_step_id": "step_1"})
        assert "Error: alignment_check is REQUIRED" in result

        # Test success update
        result = await tool.ainvoke({
            "action": "update",
            "completed_step_id": "step_1",
            "alignment_check": "looks good",
            "feedback": "some feedback"
        })
        assert result == "plan summary"
        mock_update.assert_called_once()
        args = mock_update.call_args[0]
        assert args[0] == mock_plan
        assert args[1] == "step_1"
        assert args[2] == "some feedback"
        assert "some feedback" in args[2]

@pytest.mark.asyncio
async def test_planner_tool_update_no_plan(mock_llm, mock_storage):
    with patch("myrm_agent_harness.agent.sub_agents.planner.PlannerAgent.get_current_plan", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        tool = create_planner_tool(mock_llm, mock_storage)
        result = await tool.ainvoke({"action": "update"})
        assert "Error: No existing plan found" in result

@pytest.mark.asyncio
async def test_planner_tool_get_action(mock_llm, mock_storage):
    with patch("myrm_agent_harness.agent.sub_agents.planner.PlannerAgent.get_current_plan", new_callable=AsyncMock) as mock_get:
        mock_plan = MagicMock()
        mock_plan.to_line_format.return_value = "line format plan"
        mock_plan.to_markdown.return_value = "markdown plan"
        mock_plan.model_dump_json.return_value = "json plan"
        mock_plan.goal = "test"
        mock_plan.steps = [
            MagicMock(step_id="1", status="in_progress", description="desc1"),
            MagicMock(step_id="2", status="completed", description="desc2"),
            MagicMock(step_id="3", status="skipped", description="desc3"),
            MagicMock(step_id="4", status="pending", description="desc4")
        ]
        mock_get.return_value = mock_plan

        tool = create_planner_tool(mock_llm, mock_storage)
        result = await tool.ainvoke({"action": "get"})
        assert result == "line format plan"

        config_json = PlannerConfig(output_format="json")
        tool_json = create_planner_tool(mock_llm, mock_storage, planner_config=config_json)
        result = await tool_json.ainvoke({"action": "get"})
        assert result == "json plan"

        config_md = PlannerConfig(output_format="markdown")
        tool_md = create_planner_tool(mock_llm, mock_storage, planner_config=config_md)
        result = await tool_md.ainvoke({"action": "get"})
        assert result == "markdown plan"

        # Test no plan
        mock_get.return_value = None
        result = await tool.ainvoke({"action": "get"})
        assert "No plan exists" in result

@pytest.mark.asyncio
async def test_planner_tool_unknown_action(mock_llm, mock_storage):
    tool = create_planner_tool(mock_llm, mock_storage)
    with pytest.raises(ValidationError):
        await tool.ainvoke({"action": "unknown"})

