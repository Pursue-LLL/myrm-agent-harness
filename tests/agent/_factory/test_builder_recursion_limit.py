"""Recursion-limit mapping tests for the SkillAgent factory builder.

Each LangGraph turn consumes two nodes (model + tools), so the user-facing
turn budget ``max_iterations`` must map to ``2 * max_iterations`` graph
nodes — the same contract subagent builders use (``max_turns * 2``).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.types import AgentRuntimeSpec


@pytest.mark.asyncio
async def test_create_skill_agent_doubles_max_iterations_into_recursion_limit() -> None:
    from myrm_agent_harness.agent._factory.builder import create_skill_agent

    spec = AgentRuntimeSpec(
        agent_id="agent-recursion-limit",
        name="recursion-limit",
        system_prompt="test",
        max_iterations=40,
    )

    with patch(
        "myrm_agent_harness.agent.skill_agent.SkillAgent",
    ) as mock_skill_agent_cls:
        mock_skill_agent_cls.return_value = MagicMock()
        await create_skill_agent(spec=spec, llm=MagicMock(), executor=MagicMock())

    config = mock_skill_agent_cls.call_args.kwargs["config"]
    assert config.recursion_limit == 80  # max_iterations (turns) * 2 graph nodes


@pytest.mark.asyncio
async def test_create_skill_agent_default_max_iterations_maps_to_twice_default() -> None:
    from myrm_agent_harness.agent._factory.builder import create_skill_agent

    spec = AgentRuntimeSpec(
        agent_id="agent-recursion-limit-default",
        name="recursion-limit-default",
        system_prompt="test",
    )

    with patch(
        "myrm_agent_harness.agent.skill_agent.SkillAgent",
    ) as mock_skill_agent_cls:
        mock_skill_agent_cls.return_value = MagicMock()
        await create_skill_agent(spec=spec, llm=MagicMock(), executor=MagicMock())

    config = mock_skill_agent_cls.call_args.kwargs["config"]
    assert config.recursion_limit == 100  # spec default 50 turns -> 100 graph nodes
