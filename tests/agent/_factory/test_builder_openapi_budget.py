"""OpenAPI direct budget guard tests for SkillAgent builder."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.config.exceptions import ConfigIncompleteError
from myrm_agent_harness.agent.types import AgentRuntimeSpec


def _heavy_openapi_tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = "x" * 800
    schema = MagicMock()
    schema.model_json_schema.return_value = {
        "type": "object",
        "properties": {f"field_{i}": {"type": "string", "description": "y" * 200} for i in range(8)},
    }
    tool.get_input_schema = MagicMock(return_value=schema)
    return tool


@pytest.mark.asyncio
async def test_create_skill_agent_raises_when_openapi_exceeds_direct_budget() -> None:
    from myrm_agent_harness.agent._factory.builder import create_skill_agent

    heavy_tools = [_heavy_openapi_tool(f"svc_op_{i}") for i in range(8)]
    mock_bridge = MagicMock()
    mock_bridge.get_tools = AsyncMock(return_value=heavy_tools)

    spec = AgentRuntimeSpec(
        agent_id="agent-openapi-budget",
        name="openapi-budget",
        system_prompt="test",
        openapi_services=[{"name": "svc", "enabled": True, "spec_url": "https://example.com/openapi.json"}],
    )

    with (
        patch(
            "myrm_agent_harness.toolkits.openapi_bridge.OpenAPIBridge",
            return_value=mock_bridge,
        ),
        pytest.raises(ConfigIncompleteError) as exc_info,
    ):
        await create_skill_agent(
            spec=spec,
            llm=MagicMock(),
            executor=MagicMock(),
        )

    assert exc_info.value.error_code == "openapi_direct_budget_exceeded"
