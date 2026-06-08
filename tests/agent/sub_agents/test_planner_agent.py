"""Tests for PlannerAgent.create_plan — text and multimodal input paths."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents.planner.agent import PlannerAgent
from myrm_agent_harness.agent.sub_agents.planner.schemas import Plan, PlanStep


def _mock_plan() -> Plan:
    return Plan(
        goal="Build a project",
        reasoning="Step-by-step approach",
        steps=[PlanStep(step_id="s1", description="Setup env", expected_output="env ready")],
        current_step_id="s1",
    )


@pytest.fixture
def planner() -> PlannerAgent:
    llm = MagicMock()
    storage = AsyncMock()
    storage.save_plan = AsyncMock()

    from myrm_agent_harness.agent.sub_agents.planner.config import PlannerConfig

    config = PlannerConfig()
    return PlannerAgent(llm, storage, config)


class TestCreatePlanText:
    """Text-only create_plan path."""

    @pytest.mark.asyncio
    async def test_string_input_produces_plan(self, planner: PlannerAgent):
        mock_plan = _mock_plan()
        planner.llm.with_structured_output = MagicMock(
            return_value=AsyncMock(ainvoke=AsyncMock(return_value=mock_plan))
        )

        result = await planner.create_plan("Build a web scraper")

        assert result is mock_plan
        assert result.current_step_id == "s1"

        structured_llm = planner.llm.with_structured_output.return_value
        call_args = structured_llm.ainvoke.call_args[0][0]
        assert call_args[1].content == "Please create a plan for the following task:\n\nBuild a web scraper"

    @pytest.mark.asyncio
    async def test_string_input_raises_on_bad_return(self, planner: PlannerAgent):
        planner.llm.with_structured_output = MagicMock(
            return_value=AsyncMock(ainvoke=AsyncMock(return_value="not a plan"))
        )

        with pytest.raises(ValueError, match="unexpected type"):
            await planner.create_plan("test task")


class TestCreatePlanMultimodal:
    """Multimodal create_plan path."""

    @pytest.mark.asyncio
    async def test_multimodal_input_preserves_image_parts(self, planner: PlannerAgent):
        mock_plan = _mock_plan()
        planner.llm.with_structured_output = MagicMock(
            return_value=AsyncMock(ainvoke=AsyncMock(return_value=mock_plan))
        )

        multimodal_input = [
            {"type": "text", "text": "Goal Objective: Build app\n\nCurrent Request: "},
            {"type": "text", "text": "Plan from this diagram"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]

        result = await planner.create_plan(multimodal_input)

        assert result is mock_plan
        structured_llm = planner.llm.with_structured_output.return_value
        call_args = structured_llm.ainvoke.call_args[0][0]
        human_msg = call_args[1]
        assert isinstance(human_msg.content, list)
        assert human_msg.content[0]["type"] == "text"
        assert "Please create a plan" in human_msg.content[0]["text"]
        # Original multimodal parts are preserved after instruction prefix
        assert human_msg.content[1] == multimodal_input[0]
        assert human_msg.content[3]["type"] == "image_url"

    @pytest.mark.asyncio
    async def test_multimodal_sets_current_step_id(self, planner: PlannerAgent):
        plan = Plan(
            goal="Test goal",
            reasoning="Test reasoning",
            steps=[
                PlanStep(step_id="a", description="Do first", expected_output="first done"),
                PlanStep(step_id="b", description="Do second", expected_output="second done"),
            ],
            current_step_id=None,
        )
        planner.llm.with_structured_output = MagicMock(
            return_value=AsyncMock(ainvoke=AsyncMock(return_value=plan))
        )

        result = await planner.create_plan([{"type": "text", "text": "task"}])

        assert result.current_step_id == "a"
