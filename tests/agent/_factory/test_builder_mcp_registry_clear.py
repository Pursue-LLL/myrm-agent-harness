"""Builder clears MCP registry when agent has no MCP servers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.types import AgentRuntimeSpec


@pytest.mark.asyncio
async def test_create_skill_agent_clears_mcp_registry_when_no_mcp_servers() -> None:
    from myrm_agent_harness.agent._factory.builder import create_skill_agent

    spec = AgentRuntimeSpec(
        agent_id="agent-no-mcp",
        name="no-mcp",
        system_prompt="test",
        mcp_servers=[],
    )

    with (
        patch("myrm_agent_harness.agent.skills.runtime.registry.skill_registry.clear_mcp_skills") as clear_mock,
        patch(
            "myrm_agent_harness.agent._factory.builder.route_mcp_servers",
            new=AsyncMock(),
        ) as route_mock,
        patch(
            "myrm_agent_harness.agent.skill_agent.SkillAgent",
            side_effect=RuntimeError("stop-after-mcp-section"),
        ),
        pytest.raises(RuntimeError, match="stop-after-mcp-section"),
    ):
        await create_skill_agent(
            spec=spec,
            llm=MagicMock(),
            executor=MagicMock(),
        )

    clear_mock.assert_called_once()
    route_mock.assert_not_called()
