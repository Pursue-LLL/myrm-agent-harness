"""Runtime-dict serialization of an MCP server config.

``mcp_config_to_runtime_dict`` is the single source of truth ``mcp_routing`` and
``core_generator`` use when persisting MCP configs, so the fields that decide the
connection-pool hash, the credentials, the TLS material and the runtime callbacks
must all survive the round-trip into ``MCPSkillData.config``.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.mcp.config import MCPConfig, mcp_config_to_runtime_dict


def test_stdio_defaults_are_serialized() -> None:
    runtime = mcp_config_to_runtime_dict(MCPConfig(name="files", command="npx", args=["-y", "files-mcp"]))

    assert runtime["name"] == "files"
    assert runtime["type"] == "stdio"
    assert runtime["command"] == "npx"
    assert runtime["args"] == ["-y", "files-mcp"]
    assert runtime["connect_timeout"] == 15.0
    assert runtime["execute_timeout"] == 120.0
    assert runtime["max_output_chars"] == 100_000
    assert runtime["host_serial"] is False


def test_http_tls_filters_and_callbacks_are_preserved() -> None:
    def oversized(server: str, tool: str, text: str) -> str:
        return text

    async def elicit(server: str, message: str) -> dict[str, object]:
        return {}

    cfg = MCPConfig(
        name="mtls_srv",
        type="streamable_http",
        url="https://mcp.internal.example/mcp",
        headers={"X-Custom": "1"},
        ssl_verify="/etc/ssl/ca.pem",
        client_cert="/etc/ssl/client.pem",
        client_key="/etc/ssl/client.key",
        client_key_password="key-pass",
        keepalive_interval=30.0,
        tool_include=["slow_op"],
        tool_exclude=["fast_op"],
        oversized_result_handler=oversized,
        elicitation_handler=elicit,
        extra_params={"cwd": "/tmp"},
    )

    runtime = mcp_config_to_runtime_dict(cfg)

    assert runtime["url"] == "https://mcp.internal.example/mcp"
    assert runtime["headers"] == {"X-Custom": "1"}
    assert runtime["ssl_verify"] == "/etc/ssl/ca.pem"
    assert runtime["client_cert"] == "/etc/ssl/client.pem"
    assert runtime["client_key"] == "/etc/ssl/client.key"
    assert runtime["client_key_password"] == "key-pass"
    assert runtime["keepalive_interval"] == 30.0
    assert runtime["tool_include"] == ["slow_op"]
    assert runtime["tool_exclude"] == ["fast_op"]
    assert runtime["oversized_result_handler"] is oversized
    assert runtime["elicitation_handler"] is elicit
    assert runtime["extra_params"] == {"cwd": "/tmp"}


def test_injected_auth_headers_only_appear_when_resolved() -> None:
    cfg = MCPConfig(name="auth_srv", type="sse", url="https://mcp.example/sse")

    assert "_injected_auth_headers" not in mcp_config_to_runtime_dict(cfg)

    cfg._injected_auth_headers = {"Authorization": "Bearer tok_123"}  # type: ignore[attr-defined]
    runtime = mcp_config_to_runtime_dict(cfg)

    assert runtime["_injected_auth_headers"] == {"Authorization": "Bearer tok_123"}
