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
            name="s", type="stdio", command="npx",
            tool_include=["read"], tool_exclude=["delete"],
        )
        assert cfg.tool_include == ["read"]
        assert cfg.tool_exclude == ["delete"]


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
