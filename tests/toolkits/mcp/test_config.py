"""Tests for MCPConfig model validation (transport + TLS cross-field rules)."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.mcp.config import (
    MCPConfig,
    sanitize_mcp_name_component,
    should_register_mcp_tool,
)


class TestTransportValidation:
    def test_sse_requires_url(self) -> None:
        with pytest.raises(ValueError, match="requires 'url'"):
            MCPConfig(name="s", type="sse")

    def test_streamable_http_requires_url(self) -> None:
        with pytest.raises(ValueError, match="requires 'url'"):
            MCPConfig(name="s", type="streamable_http")

    def test_stdio_requires_command(self) -> None:
        with pytest.raises(ValueError, match="requires 'command'"):
            MCPConfig(name="s", type="stdio")

    def test_valid_stdio(self) -> None:
        cfg = MCPConfig(name="fs", type="stdio", command="npx", args=["-y", "x"])
        assert cfg.command == "npx"


class TestTLSValidation:
    def test_client_key_requires_cert(self) -> None:
        with pytest.raises(ValueError, match=r"client_key.*requires.*client_cert"):
            MCPConfig(name="s", type="sse", url="https://x", client_key="/k.pem")

    def test_password_requires_cert(self) -> None:
        with pytest.raises(ValueError, match=r"client_key_password.*requires.*client_cert"):
            MCPConfig(name="s", type="sse", url="https://x", client_key_password="pw")

    def test_full_mtls_config_ok(self) -> None:
        cfg = MCPConfig(
            name="s",
            type="streamable_http",
            url="https://x",
            client_cert="/c.pem",
            client_key="/k.pem",
            client_key_password="pw",
            ssl_verify="/ca.pem",
        )
        assert cfg.client_cert == "/c.pem"
        assert cfg.client_key_password == "pw"

    def test_cert_only_ok(self) -> None:
        cfg = MCPConfig(name="s", type="sse", url="https://x", client_cert="/bundle.pem")
        assert cfg.client_key is None
        assert cfg.client_key_password is None

    def test_no_tls_ok(self) -> None:
        cfg = MCPConfig(name="s", type="sse", url="https://x")
        assert cfg.ssl_verify is None
        assert cfg.client_cert is None


class TestHeadersField:
    def test_headers_default_none(self) -> None:
        cfg = MCPConfig(name="s", type="sse", url="https://x")
        assert cfg.headers is None

    def test_headers_with_secret_ref(self) -> None:
        cfg = MCPConfig(
            name="s",
            type="sse",
            url="https://x",
            headers={"Authorization": "Bearer {{secret:TOKEN}}"},
        )
        assert cfg.headers == {"Authorization": "Bearer {{secret:TOKEN}}"}

    def test_headers_multiple_entries(self) -> None:
        cfg = MCPConfig(
            name="s",
            type="streamable_http",
            url="https://x",
            headers={"X-API-Key": "key", "Accept": "application/json"},
        )
        assert len(cfg.headers) == 2
        assert cfg.headers["X-API-Key"] == "key"

    def test_headers_excluded_from_serialization_when_none(self) -> None:
        cfg = MCPConfig(name="s", type="stdio", command="npx")
        data = cfg.model_dump(exclude_none=True)
        assert "headers" not in data


class TestToolIncludeExcludeFields:
    def test_defaults_none(self) -> None:
        cfg = MCPConfig(name="s", type="stdio", command="npx")
        assert cfg.tool_include is None
        assert cfg.tool_exclude is None
        assert cfg.host_serial is False
        assert cfg.keepalive_interval is None

    def test_include_set(self) -> None:
        cfg = MCPConfig(name="s", type="stdio", command="npx", tool_include=["read", "write"])
        assert cfg.tool_include == ["read", "write"]
        assert cfg.tool_exclude is None

    def test_exclude_set(self) -> None:
        cfg = MCPConfig(name="s", type="stdio", command="npx", tool_exclude=["delete"])
        assert cfg.tool_include is None
        assert cfg.tool_exclude == ["delete"]

    def test_both_set(self) -> None:
        cfg = MCPConfig(
            name="s",
            type="stdio",
            command="npx",
            tool_include=["read"],
            tool_exclude=["delete"],
        )
        assert cfg.tool_include == ["read"]
        assert cfg.tool_exclude == ["delete"]

    def test_host_serial_set(self) -> None:
        cfg = MCPConfig(name="s", type="stdio", command="npx", host_serial=True)
        assert cfg.host_serial is True

    def test_keepalive_interval_set(self) -> None:
        cfg = MCPConfig(name="s", type="sse", url="https://example.com/sse", keepalive_interval=45)
        assert cfg.keepalive_interval == 45


class TestShouldRegisterMcpTool:
    def test_both_none_registers_all(self) -> None:
        assert should_register_mcp_tool("any_tool", None, None) is True

    def test_both_empty_registers_all(self) -> None:
        assert should_register_mcp_tool("any_tool", [], []) is True

    def test_include_match(self) -> None:
        assert should_register_mcp_tool("read", ["read", "write"], None) is True

    def test_include_no_match(self) -> None:
        assert should_register_mcp_tool("delete", ["read", "write"], None) is False

    def test_exclude_match_blocks(self) -> None:
        assert should_register_mcp_tool("delete", None, ["delete"]) is False

    def test_exclude_no_match_allows(self) -> None:
        assert should_register_mcp_tool("read", None, ["delete"]) is True

    def test_include_takes_precedence_over_exclude(self) -> None:
        assert should_register_mcp_tool("read", ["read"], ["read"]) is True
        assert should_register_mcp_tool("write", ["read"], ["delete"]) is False

    def test_empty_include_falls_through_to_exclude(self) -> None:
        assert should_register_mcp_tool("delete", [], ["delete"]) is False

    def test_include_none_exclude_empty_registers_all(self) -> None:
        assert should_register_mcp_tool("any", None, []) is True


class TestSanitizeMcpNameComponent:
    def test_alphanumeric_unchanged(self) -> None:
        assert sanitize_mcp_name_component("github") == "github"

    def test_hyphen_replaced(self) -> None:
        assert sanitize_mcp_name_component("my-server") == "my_server"

    def test_dots_replaced(self) -> None:
        assert sanitize_mcp_name_component("v2.api") == "v2_api"

    def test_spaces_replaced(self) -> None:
        assert sanitize_mcp_name_component("my server") == "my_server"

    def test_mixed_special_chars(self) -> None:
        assert sanitize_mcp_name_component("a@b#c$d") == "a_b_c_d"

    def test_empty_string(self) -> None:
        assert sanitize_mcp_name_component("") == "unnamed"

    def test_underscores_preserved(self) -> None:
        assert sanitize_mcp_name_component("my_server_2") == "my_server_2"

    def test_consecutive_special_chars_collapsed(self) -> None:
        assert sanitize_mcp_name_component("a--b") == "a_b"

    def test_leading_trailing_special_chars(self) -> None:
        assert sanitize_mcp_name_component("-server-") == "server"

    def test_unicode_replaced(self) -> None:
        assert sanitize_mcp_name_component("飞书mcp") == "mcp"

    def test_numbers_preserved(self) -> None:
        assert sanitize_mcp_name_component("v2_server_3") == "v2_server_3"

    def test_consecutive_underscores_collapsed(self) -> None:
        assert sanitize_mcp_name_component("my__server") == "my_server"

    def test_double_space_collapsed(self) -> None:
        assert sanitize_mcp_name_component("my  server") == "my_server"

    def test_double_hyphen_collapsed(self) -> None:
        assert sanitize_mcp_name_component("my--mcp--tool") == "my_mcp_tool"

    def test_pure_special_chars_fallback(self) -> None:
        assert sanitize_mcp_name_component("-") == "unnamed"

    def test_multi_special_chars_fallback(self) -> None:
        assert sanitize_mcp_name_component("---") == "unnamed"


class TestMaxOutputCharsValidation:
    """Verify max_output_chars Pydantic constraints (ge=1000, le=10_000_000)."""

    def test_default_value(self) -> None:
        cfg = MCPConfig(name="s", type="stdio", command="echo")
        assert cfg.max_output_chars == 100_000

    def test_custom_value(self) -> None:
        cfg = MCPConfig(name="s", type="stdio", command="echo", max_output_chars=5000)
        assert cfg.max_output_chars == 5000

    def test_minimum_boundary(self) -> None:
        cfg = MCPConfig(name="s", type="stdio", command="echo", max_output_chars=1000)
        assert cfg.max_output_chars == 1000

    def test_maximum_boundary(self) -> None:
        cfg = MCPConfig(name="s", type="stdio", command="echo", max_output_chars=10_000_000)
        assert cfg.max_output_chars == 10_000_000

    def test_below_minimum_rejected(self) -> None:
        with pytest.raises(ValueError):
            MCPConfig(name="s", type="stdio", command="echo", max_output_chars=999)

    def test_above_maximum_rejected(self) -> None:
        with pytest.raises(ValueError):
            MCPConfig(name="s", type="stdio", command="echo", max_output_chars=10_000_001)


class TestTypeAutoInference:
    """Verify type is auto-inferred from command/url when omitted."""

    def test_command_infers_stdio(self) -> None:
        cfg = MCPConfig(name="fs", command="npx", args=["-y", "server"])
        assert cfg.type == "stdio"

    def test_url_infers_sse(self) -> None:
        cfg = MCPConfig(name="remote", url="https://example.com/sse")
        assert cfg.type == "sse"

    def test_url_with_mcp_path_infers_streamable_http(self) -> None:
        cfg = MCPConfig(name="remote", url="https://example.com/mcp")
        assert cfg.type == "streamable_http"

    def test_explicit_type_not_overridden(self) -> None:
        cfg = MCPConfig(name="remote", type="sse", url="https://example.com/mcp")
        assert cfg.type == "sse"

    def test_no_type_no_hints_raises(self) -> None:
        with pytest.raises(ValueError):
            MCPConfig(name="bare")


class TestMcpConfigToRuntimeDictAndSecurityWiring:
    """Verify mcp_config_to_runtime_dict SSOT, OSV cache, TrustGate root fallback, backoff, and IPC cache."""

    def test_mcp_config_to_runtime_dict_preserves_all_fields_and_merges_auth_headers(self) -> None:
        from myrm_agent_harness.toolkits.mcp.config import mcp_config_to_runtime_dict

        def dummy_oversized(server: str, tool: str, text: str) -> str:
            return text

        cfg = MCPConfig(
            name="mtls_srv",
            type="streamable_http",
            url="https://mcp.internal.example/mcp",
            headers={"X-Custom": "1"},
            ssl_verify="/etc/ssl/ca.pem",
            client_cert="/etc/ssl/client.pem",
            client_key="/etc/ssl/client.key",
            tool_include=["slow_op"],
            tool_exclude=["fast_op"],
            oversized_result_handler=dummy_oversized,
            extra_params={"cwd": "/tmp"},
        )
        cfg._injected_auth_headers = {"Authorization": "Bearer tok_123"}  # type: ignore[attr-defined]

        runtime_dict = mcp_config_to_runtime_dict(cfg)
        assert runtime_dict["name"] == "mtls_srv"
        assert runtime_dict["ssl_verify"] == "/etc/ssl/ca.pem"
        assert runtime_dict["client_cert"] == "/etc/ssl/client.pem"
        assert runtime_dict["client_key"] == "/etc/ssl/client.key"
        assert runtime_dict["tool_include"] == ["slow_op"]
        assert runtime_dict["tool_exclude"] == ["fast_op"]
        assert runtime_dict["oversized_result_handler"] is dummy_oversized
        assert runtime_dict["extra_params"] == {"cwd": "/tmp"}
        assert runtime_dict["_injected_auth_headers"] == {"Authorization": "Bearer tok_123"}

    @pytest.mark.asyncio
    async def test_osv_malware_cache_avoids_duplicate_http_queries(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from myrm_agent_harness.toolkits.mcp.security import (
            check_osv_malware,
            clear_osv_malware_cache,
        )

        clear_osv_malware_cache()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"vulns": []}

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = mock_resp

        with patch(
            "myrm_agent_harness.toolkits.mcp.security.create_httpx_client",
            return_value=mock_client,
        ):
            r1 = await check_osv_malware("npx", ["-y", "cached-pkg-test"], use_cache=True)
            r2 = await check_osv_malware("npx", ["-y", "cached-pkg-test"], use_cache=True)
            assert r1 is None
            assert r2 is None
            assert mock_client.post.call_count == 1
        clear_osv_malware_cache()

    def test_workspace_trust_gate_falls_back_to_context_workspace_root(self, tmp_path: object) -> None:
        from pathlib import Path

        from myrm_agent_harness.agent.security.workspace_trust import (
            WorkspaceTrustBlockedError,
            WorkspaceTrustLevel,
        )
        from myrm_agent_harness.agent.security.workspace_trust.context import (
            clear_workspace_trust_context,
            set_workspace_root,
            set_workspace_trust_level,
        )
        from myrm_agent_harness.toolkits.mcp.transport import get_workspace_trust_gate

        root = str(Path(str(tmp_path)).resolve())
        try:
            set_workspace_trust_level(WorkspaceTrustLevel.TRUSTED)
            set_workspace_root(root)
            gate = get_workspace_trust_gate()
            assert gate is not None
            # Trusted workspace allows spawn with workspace_root=None (resolved from context)
            gate.assert_mcp_spawn_allowed(
                workspace_root=None,
                cwd=root,
                plugin_root=None,
                trust_level=gate.get_trust_level(),
            )
            # Restricted workspace with workspace_root=None resolves root from context and blocks repo-local cwd
            set_workspace_trust_level(WorkspaceTrustLevel.RESTRICTED)
            with pytest.raises(WorkspaceTrustBlockedError):
                gate.assert_mcp_spawn_allowed(
                    workspace_root=None,
                    cwd=root,
                    plugin_root=None,
                    trust_level=gate.get_trust_level(),
                )
        finally:
            clear_workspace_trust_context()

    @pytest.mark.asyncio
    async def test_proxy_tool_cross_ttl_self_healing_and_security_lockout(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from myrm_agent_harness.toolkits.mcp.errors import MCPRuntimePostureError
        from myrm_agent_harness.toolkits.mcp.session_actor_tools import make_actor_proxy_tool

        stale_actor = MagicMock()
        stale_actor.is_healthy.return_value = False
        stale_actor._security_terminated = False
        stale_actor.server_name = "srv"
        stale_actor.call = AsyncMock(side_effect=MCPRuntimePostureError("terminated", server_name="srv"))

        fresh_actor = MagicMock()
        fresh_actor.is_healthy.return_value = True
        fresh_actor._security_terminated = False
        fresh_actor.server_name = "srv"
        fresh_actor.call = AsyncMock(return_value="healed_ok")

        resolver = AsyncMock(return_value=fresh_actor)
        stale_actor._actor_resolver = resolver

        base_tool = MagicMock()
        base_tool.name = "mcp__srv__ping"
        base_tool.description = "ping"
        base_tool.args_schema = {"type": "object", "properties": {}}
        base_tool.metadata = None

        proxy = make_actor_proxy_tool(stale_actor, base_tool)
        assert proxy.coroutine is not None
        result = await proxy.coroutine(x=1)
        assert result == "healed_ok"
        resolver.assert_awaited_once()
        fresh_actor.call.assert_awaited_once_with("mcp__srv__ping", {"x": 1})

        # When security terminated, self-healing must be refused
        resolver.reset_mock()
        stale_actor._security_terminated = True
        proxy_blocked = make_actor_proxy_tool(stale_actor, base_tool)
        assert proxy_blocked.coroutine is not None
        with pytest.raises(MCPRuntimePostureError):
            await proxy_blocked.coroutine(x=1)
        resolver.assert_not_awaited()

    def test_startup_backoff_and_ipc_skill_cache(self) -> None:
        from myrm_agent_harness.agent.skills.runtime.registry import SkillRegistry
        from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata
        from myrm_agent_harness.toolkits.mcp.connection_pool_types import MCPStartupBackoff

        backoff = MCPStartupBackoff()
        d1 = backoff.record_failure("h1", "boom", ("demo",))
        d2 = backoff.record_failure("h1", "boom2", ("demo",))
        assert d1 == 1.0
        assert d2 == 5.0
        with pytest.raises(RuntimeError, match="startup backoff cooldown"):
            backoff.check_allowed("h1")
        backoff.record_success("h1")
        backoff.check_allowed("h1")

        reg = SkillRegistry()
        mcp_skill = SkillMetadata(
            name="mcp-demo",
            description="demo",
            mcp=MCPSkillData(
                server="demo",
                tools=["ping"],
                config={"name": "demo", "type": "stdio", "command": "echo"},
            ),
        )
        reg.register(mcp_skill)
        assert reg.get_skill("mcp-demo") is mcp_skill
        reg.clear_mcp_skills()
        assert reg.get_skill("mcp-demo") is None
        assert reg.get_mcp_skill_for_ipc("mcp-demo") is mcp_skill
