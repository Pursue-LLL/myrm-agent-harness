"""OpenAPI load-failure guard tests for SkillAgent builder."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.config.exceptions import ConfigIncompleteError
from myrm_agent_harness.agent.types import AgentRuntimeSpec


def _light_openapi_tool(name: str = "svc_list_items") -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = "list items"
    schema = MagicMock()
    schema.model_json_schema.return_value = {
        "type": "object",
        "properties": {"limit": {"type": "integer"}},
    }
    tool.get_input_schema = MagicMock(return_value=schema)
    return tool


@pytest.mark.asyncio
async def test_create_skill_agent_raises_when_openapi_load_raises() -> None:
    from myrm_agent_harness.agent._factory.builder import create_skill_agent

    mock_bridge = MagicMock()
    mock_bridge.get_tools = AsyncMock(side_effect=ValueError("Invalid spec URL"))

    spec = AgentRuntimeSpec(
        agent_id="agent-openapi-load-fail",
        name="openapi-load-fail",
        system_prompt="test",
        openapi_services=[
            {"name": "svc", "enabled": True, "spec_url": "https://example.com/bad.json"}
        ],
    )

    with patch(
        "myrm_agent_harness.toolkits.openapi_bridge.OpenAPIBridge",
        return_value=mock_bridge,
    ), pytest.raises(ConfigIncompleteError) as exc_info:
        await create_skill_agent(
            spec=spec,
            llm=MagicMock(),
            executor=MagicMock(),
        )

    assert exc_info.value.error_code == "openapi_load_failed"


@pytest.mark.asyncio
async def test_create_skill_agent_raises_when_enabled_openapi_produces_zero_tools() -> None:
    from myrm_agent_harness.agent._factory.builder import create_skill_agent

    mock_bridge = MagicMock()
    mock_bridge.get_tools = AsyncMock(return_value=[])

    spec = AgentRuntimeSpec(
        agent_id="agent-openapi-zero-tools",
        name="openapi-zero-tools",
        system_prompt="test",
        openapi_services=[
            {
                "name": "svc",
                "enabled": True,
                "spec_url": "https://example.com/openapi.json",
                "selected_endpoints": ["nonexistent_operation"],
            }
        ],
    )

    with patch(
        "myrm_agent_harness.toolkits.openapi_bridge.OpenAPIBridge",
        return_value=mock_bridge,
    ), pytest.raises(ConfigIncompleteError) as exc_info:
        await create_skill_agent(
            spec=spec,
            llm=MagicMock(),
            executor=MagicMock(),
        )

    assert exc_info.value.error_code == "openapi_load_failed"


@pytest.mark.asyncio
async def test_create_skill_agent_skips_load_failed_when_all_openapi_disabled() -> None:
    from myrm_agent_harness.agent._factory.builder import create_skill_agent

    mock_bridge = MagicMock()
    mock_bridge.get_tools = AsyncMock(side_effect=ValueError("should not be called"))

    spec = AgentRuntimeSpec(
        agent_id="agent-openapi-all-disabled",
        name="openapi-all-disabled",
        system_prompt="test",
        openapi_services=[
            {"name": "svc", "enabled": False, "spec_url": "https://example.com/bad.json"}
        ],
    )

    with patch(
        "myrm_agent_harness.toolkits.openapi_bridge.OpenAPIBridge",
        return_value=mock_bridge,
    ), patch(
        "myrm_agent_harness.agent.skill_agent.SkillAgent",
    ) as mock_skill_agent_cls:
        mock_skill_agent_cls.return_value = MagicMock()
        await create_skill_agent(
            spec=spec,
            llm=MagicMock(),
            executor=MagicMock(),
        )

    mock_bridge.get_tools.assert_not_called()


@pytest.mark.asyncio
async def test_create_skill_agent_allows_partial_openapi_load_success() -> None:
    from myrm_agent_harness.agent._factory.builder import create_skill_agent

    good_tool = _light_openapi_tool()

    async def _get_tools_side_effect(
        config: object,
    ) -> list[MagicMock]:
        from myrm_agent_harness.toolkits.openapi_bridge import OpenAPIServiceConfig

        svc = (
            config
            if isinstance(config, OpenAPIServiceConfig)
            else OpenAPIServiceConfig.model_validate(config)
        )
        if svc.name == "bad":
            raise ValueError("bad spec")
        return [good_tool]

    mock_bridge = MagicMock()
    mock_bridge.get_tools = AsyncMock(side_effect=_get_tools_side_effect)

    spec = AgentRuntimeSpec(
        agent_id="agent-openapi-partial",
        name="openapi-partial",
        system_prompt="test",
        openapi_services=[
            {"name": "bad", "enabled": True, "spec_url": "https://example.com/bad.json"},
            {"name": "good", "enabled": True, "spec_url": "https://example.com/good.json"},
        ],
    )

    with patch(
        "myrm_agent_harness.toolkits.openapi_bridge.OpenAPIBridge",
        return_value=mock_bridge,
    ), patch(
        "myrm_agent_harness.agent.skill_agent.SkillAgent",
    ) as mock_skill_agent_cls:
        mock_skill_agent_cls.return_value = MagicMock()
        await create_skill_agent(
            spec=spec,
            llm=MagicMock(),
            executor=MagicMock(),
        )

    call_kwargs = mock_skill_agent_cls.call_args.kwargs
    bound_tools = call_kwargs.get("tools") or []
    assert any(getattr(tool, "name", None) == good_tool.name for tool in bound_tools)


@pytest.mark.asyncio
async def test_create_skill_agent_binds_openapi_tools_when_load_succeeds_under_budget() -> None:
    from myrm_agent_harness.agent._factory.builder import create_skill_agent

    light_tool = _light_openapi_tool("svc_list_items")
    mock_bridge = MagicMock()
    mock_bridge.get_tools = AsyncMock(return_value=[light_tool])

    spec = AgentRuntimeSpec(
        agent_id="agent-openapi-success",
        name="openapi-success",
        system_prompt="test",
        openapi_services=[
            {
                "name": "svc",
                "enabled": True,
                "spec_url": "https://example.com/openapi.json",
            }
        ],
    )

    with patch(
        "myrm_agent_harness.toolkits.openapi_bridge.OpenAPIBridge",
        return_value=mock_bridge,
    ), patch(
        "myrm_agent_harness.agent.skill_agent.SkillAgent",
    ) as mock_skill_agent_cls:
        mock_skill_agent_cls.return_value = MagicMock()
        await create_skill_agent(
            spec=spec,
            llm=MagicMock(),
            executor=MagicMock(),
        )

    call_kwargs = mock_skill_agent_cls.call_args.kwargs
    bound_tools = call_kwargs.get("tools") or []
    assert any(getattr(tool, "name", None) == light_tool.name for tool in bound_tools)


def _heavy_openapi_tool(name: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = "x" * 800
    schema = MagicMock()
    schema.model_json_schema.return_value = {
        "type": "object",
        "properties": {
            f"field_{i}": {"type": "string", "description": "y" * 200}
            for i in range(8)
        },
    }
    tool.get_input_schema = MagicMock(return_value=schema)
    return tool


@pytest.mark.asyncio
async def test_create_skill_agent_allows_openapi_over_budget_in_direct_fc_mode() -> None:
    from myrm_agent_harness.agent._factory.builder import create_skill_agent

    heavy_tools = [_heavy_openapi_tool(f"svc_op_{i}") for i in range(8)]
    mock_bridge = MagicMock()
    mock_bridge.get_tools = AsyncMock(return_value=heavy_tools)

    spec = AgentRuntimeSpec(
        agent_id="agent-openapi-direct-fc",
        name="openapi-direct-fc",
        system_prompt="test",
        mcp_surface_mode="direct_fc",
        openapi_services=[
            {"name": "svc", "enabled": True, "spec_url": "https://example.com/openapi.json"}
        ],
    )

    with patch(
        "myrm_agent_harness.toolkits.openapi_bridge.OpenAPIBridge",
        return_value=mock_bridge,
    ), patch(
        "myrm_agent_harness.agent.skill_agent.SkillAgent",
    ) as mock_skill_agent_cls:
        mock_skill_agent_cls.return_value = MagicMock()
        await create_skill_agent(
            spec=spec,
            llm=MagicMock(),
            executor=MagicMock(),
        )

    call_kwargs = mock_skill_agent_cls.call_args.kwargs
    bound_tools = call_kwargs.get("tools") or []
    assert len(bound_tools) == len(heavy_tools)
