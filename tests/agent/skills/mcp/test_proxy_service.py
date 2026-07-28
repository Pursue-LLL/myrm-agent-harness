"""Unit tests for MCPSkillProxyService validation, parsing, and invoke paths."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.skills.mcp.proxy_service import (
    MCPSkillProxyService,
    _resolve_mcp_input_schema,
    _validate_required_mcp_params,
    get_mcp_skill_proxy_service,
    handle_mcp_invoke,
)
from myrm_agent_harness.agent.skills.runtime.registry import skill_registry
from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata
from myrm_agent_harness.toolkits.mcp.config import MCPConfig


@pytest.fixture(autouse=True)
def _clear_skill_registry() -> None:
    skill_registry.clear()
    yield
    skill_registry.clear()


@pytest.fixture
def mcp_skill_meta() -> SkillMetadata:
    return SkillMetadata(
        name="mcp_test_skill",
        description="Test MCP skill",
        mcp=MCPSkillData(
            server="test-server",
            tools=["create_issue", "ping"],
            config=[{"name": "test-server", "type": "stdio", "command": "echo"}],
            tool_schemas={
                "create_issue": {
                    "description": "Create issue",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                        "required": ["title"],
                    },
                },
                "ping": {"description": "Ping", "inputSchema": {"type": "object", "properties": {}}},
            },
        ),
    )


class TestResolveMcpInputSchema:
    def test_missing_input_schema_returns_empty(self) -> None:
        assert _resolve_mcp_input_schema({}) == {}

    def test_dict_input_schema(self) -> None:
        schema = {"type": "object", "properties": {"q": {"type": "string"}}}
        assert _resolve_mcp_input_schema({"inputSchema": schema}) == schema

    def test_pydantic_model_input_schema(self) -> None:
        model = MagicMock()
        model.model_json_schema.return_value = {"type": "object"}
        assert _resolve_mcp_input_schema({"inputSchema": model}) == {"type": "object"}


class TestValidateRequiredMcpParamsExtended:
    def test_no_schema_entry_returns_none(self) -> None:
        assert _validate_required_mcp_params("ping", {}, None) is None

    def test_malformed_schema_returns_none(self) -> None:
        assert _validate_required_mcp_params("ping", {}, {"inputSchema": object()}) is None


class TestMCPSkillProxyServiceParse:
    def test_parse_text_dict_extracts_json(self) -> None:
        service = MCPSkillProxyService()
        raw = {"type": "text", "text": '{"ok": true}'}
        assert service.parse_mcp_result(raw) == {"ok": True}

    def test_parse_tuple_content(self) -> None:
        service = MCPSkillProxyService()
        raw = ([{"type": "text", "text": "hello"}], None)
        assert service.parse_mcp_result(raw) == "hello"

    def test_parse_string_list(self) -> None:
        service = MCPSkillProxyService()
        assert service.parse_mcp_result(['{"a": 1}']) == {"a": 1}

    def test_parse_plain_string(self) -> None:
        service = MCPSkillProxyService()
        assert service.parse_mcp_result("plain") == "plain"

    def test_extract_non_dict_passthrough(self) -> None:
        service = MCPSkillProxyService()
        assert service._extract_text_content(42) == 42


class TestMCPSkillProxyServiceInvoke:
    def test_make_cache_key_stable(self) -> None:
        service = MCPSkillProxyService()
        key_a = service._make_cache_key("skill", "tool", {"a": 1})
        key_b = service._make_cache_key("skill", "tool", {"a": 1})
        assert key_a == key_b

    @pytest.mark.asyncio
    async def test_invoke_tool_cache_hit(self, mcp_skill_meta: SkillMetadata) -> None:
        service = MCPSkillProxyService()
        skill_registry.register(mcp_skill_meta)
        cache_key = service._make_cache_key("mcp_test_skill", "ping", {})
        service._cache.set(cache_key, "cached-value")

        result = await service.invoke_tool("mcp_test_skill", "ping", {})
        assert result == "cached-value"

    @pytest.mark.asyncio
    async def test_invoke_tool_cache_hit_canonical_tool_name(self, mcp_skill_meta: SkillMetadata) -> None:
        service = MCPSkillProxyService()
        skill_registry.register(mcp_skill_meta)
        cache_key = service._make_cache_key("mcp_test_skill", "create_issue", {"title": "bug"})
        service._cache.set(cache_key, "cached-issue")

        result = await service.invoke_tool("mcp_test_skill", "create-issue", {"title": "bug"})
        assert result == "cached-issue"

    @pytest.mark.asyncio
    async def test_invoke_tool_validation_short_circuit(self, mcp_skill_meta: SkillMetadata) -> None:
        service = MCPSkillProxyService()
        skill_registry.register(mcp_skill_meta)

        result = await service.invoke_tool("mcp_test_skill", "create_issue", {})
        assert isinstance(result, dict)
        assert "missing required argument" in str(result.get("error"))

    @pytest.mark.asyncio
    async def test_invoke_tool_success_path(self, mcp_skill_meta: SkillMetadata) -> None:
        service = MCPSkillProxyService()
        skill_registry.register(mcp_skill_meta)

        mock_conn = MagicMock()
        mock_conn.call = AsyncMock(return_value=({"type": "text", "text": "pong"}, None))
        mock_manager = MagicMock()
        mock_manager.get_connection = AsyncMock(return_value=mock_conn)

        with patch(
            "myrm_agent_harness.toolkits.mcp.connection_manager.get_mcp_connection_manager",
            AsyncMock(return_value=mock_manager),
        ):
            result = await service.invoke_tool("mcp_test_skill", "ping", {})

        assert result == "pong"

    @pytest.mark.asyncio
    async def test_invoke_tool_skill_not_found(self) -> None:
        service = MCPSkillProxyService()
        with pytest.raises(RuntimeError, match="Skill not found"):
            await service.invoke_tool("missing_skill", "ping", {})

    @pytest.mark.asyncio
    async def test_invoke_tool_not_mcp_skill(self) -> None:
        service = MCPSkillProxyService()
        skill_registry.register(SkillMetadata(name="plain_skill", description="Not MCP"))
        with pytest.raises(RuntimeError, match="not an MCP skill"):
            await service.invoke_tool("plain_skill", "ping", {})

    @pytest.mark.asyncio
    async def test_invoke_tool_tool_not_found(self, mcp_skill_meta: SkillMetadata) -> None:
        service = MCPSkillProxyService()
        skill_registry.register(mcp_skill_meta)
        with pytest.raises(RuntimeError, match="Tool 'missing' not found"):
            await service.invoke_tool("mcp_test_skill", "missing", {})

    def test_convert_skill_meta_config_dict_and_model(self, mcp_skill_meta: SkillMetadata) -> None:
        service = MCPSkillProxyService()
        configs = service._convert_skill_meta_config(mcp_skill_meta)
        assert len(configs) == 1
        assert isinstance(configs[0], MCPConfig)

        mcp_skill_meta.mcp.config = [MCPConfig(name="test-server", type="stdio", command="echo")]
        configs_model = service._convert_skill_meta_config(mcp_skill_meta)
        assert configs_model[0].command == "echo"

    def test_convert_skill_meta_config_missing_raises(self) -> None:
        service = MCPSkillProxyService()
        skill = SkillMetadata(
            name="bad",
            description="bad",
            mcp=MCPSkillData(server="s", tools=[], config=[]),
        )
        with pytest.raises(RuntimeError, match="mcp_config not found"):
            service._convert_skill_meta_config(skill)


class TestProxyServiceSingleton:
    def test_get_mcp_skill_proxy_service_singleton(self) -> None:
        import myrm_agent_harness.agent.skills.mcp.proxy_service as mod

        mod._service = None
        first = get_mcp_skill_proxy_service()
        second = get_mcp_skill_proxy_service()
        assert first is second
        mod._service = None

    @pytest.mark.asyncio
    async def test_handle_mcp_invoke_success(self, mcp_skill_meta: SkillMetadata) -> None:
        skill_registry.register(mcp_skill_meta)
        service = get_mcp_skill_proxy_service()
        service._cache.clear()

        with patch.object(service, "invoke_tool", AsyncMock(return_value="ok")):
            result = await handle_mcp_invoke("mcp_test_skill", "ping", {})

        assert result["success"] is True
        assert result["result"] == "ok"

    @pytest.mark.asyncio
    async def test_handle_mcp_invoke_failure(self) -> None:
        service = get_mcp_skill_proxy_service()
        with patch.object(service, "invoke_tool", AsyncMock(side_effect=RuntimeError("boom"))):
            result = await handle_mcp_invoke("missing", "ping", {})
        assert result["success"] is False
        assert "RuntimeError" in str(result.get("error"))
