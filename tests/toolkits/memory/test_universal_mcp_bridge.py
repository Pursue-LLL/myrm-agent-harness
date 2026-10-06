# [POS] tests/toolkits/memory/test_universal_mcp_bridge.py
# [INPUT] pytest, json, myrm_agent_harness.toolkits.memory.universal_mcp_bridge
# [OUTPUT] test_client_config_generator_claude_code_and_cursor, test_client_config_generator_hermes_yaml_and_sse, test_client_config_generator_all_clients_coverage, test_bridge_runner_tools_and_command_construction

import json

from myrm_agent_harness.toolkits.memory.universal_mcp_bridge import (
    ClientConfigSnippet,
    ExternalClientConfigGenerator,
    ExternalClientKind,
    McpTransportKind,
    UniversalMcpMemoryBridge,
    UniversalMemoryBridgeOptions,
)


def test_client_config_generator_claude_code_and_cursor() -> None:
    """Verify configuration generator produces valid MCP snippets for Claude Code and Cursor."""
    opts = UniversalMemoryBridgeOptions(
        user_id="alice_dev",
        server_binary_path="/usr/local/bin/python3",
    )

    # 1. Claude Code
    claude_snippet: ClientConfigSnippet = ExternalClientConfigGenerator.generate(
        ExternalClientKind.CLAUDE_CODE,
        opts,
    )
    assert claude_snippet.client_kind == ExternalClientKind.CLAUDE_CODE
    assert claude_snippet.config_format == "json"
    assert ".claude.json" in claude_snippet.target_config_file_path

    payload = json.loads(claude_snippet.raw_content)
    assert "mcpServers" in payload
    assert "myrm-memory" in payload["mcpServers"]
    server_entry = payload["mcpServers"]["myrm-memory"]
    assert server_entry["command"] == "/usr/local/bin/python3"
    assert "--user-id" in server_entry["args"]
    assert "alice_dev" in server_entry["args"]

    # 2. Cursor
    cursor_snippet: ClientConfigSnippet = ExternalClientConfigGenerator.generate(
        ExternalClientKind.CURSOR,
        opts,
    )
    assert cursor_snippet.client_kind == ExternalClientKind.CURSOR
    assert cursor_snippet.target_config_file_path == ".cursor/mcp.json"
    cursor_payload = json.loads(cursor_snippet.raw_content)
    assert "myrm-memory" in cursor_payload["mcpServers"]


def test_client_config_generator_hermes_yaml_and_sse() -> None:
    """Verify Hermes YAML generation and SSE transport configuration URL generation."""
    # Stdio Hermes
    hermes_stdio = ExternalClientConfigGenerator.generate(
        ExternalClientKind.HERMES,
        UniversalMemoryBridgeOptions(user_id="bob_lead", transport=McpTransportKind.STDIO),
    )
    assert hermes_stdio.config_format == "yaml"
    assert "mcp:" in hermes_stdio.raw_content
    assert "myrm_memory:" in hermes_stdio.raw_content
    assert "--user-id" in hermes_stdio.raw_content
    assert "bob_lead" in hermes_stdio.raw_content

    # SSE Mode
    sse_opts = UniversalMemoryBridgeOptions(
        user_id="bob_lead",
        transport=McpTransportKind.SSE,
        host="127.0.0.1",
        port=9090,
    )
    hermes_sse = ExternalClientConfigGenerator.generate(
        ExternalClientKind.HERMES,
        sse_opts,
    )
    assert "http://127.0.0.1:9090/api/memory/mcp/sse?user_id=bob_lead" in hermes_sse.raw_content


def test_client_config_generator_all_clients_coverage() -> None:
    """Verify generate_all covers every supported external AI assistant client without errors."""
    all_snippets = ExternalClientConfigGenerator.generate_all()
    kinds = {s.client_kind for s in all_snippets}
    assert kinds == set(ExternalClientKind)
    assert len(all_snippets) == 5


def test_bridge_runner_tools_and_command_construction() -> None:
    """Verify UniversalMcpMemoryBridge tool definitions and CLI command builder."""
    bridge = UniversalMcpMemoryBridge(
        UniversalMemoryBridgeOptions(user_id="test_user_777"),
    )

    tools = bridge.get_tool_definitions()
    tool_names = [t["name"] for t in tools]
    assert "memory_recall" in tool_names
    assert "memory_store" in tool_names
    assert "memory_list" in tool_names
    assert "memory_manage" in tool_names

    # CLI command construction
    cmd = bridge.build_client_bridge_command(ExternalClientKind.CLAUDE_CODE)
    assert any("myrm_agent_harness.toolkits.memory.agent_surface.mcp_server" in arg for arg in cmd)
    assert "--user-id" in cmd
    assert "test_user_777" in cmd
    assert "--client-origin" in cmd
    assert "claude_code" in cmd
