"""Unit tests for ACP host MCP configuration conversion and SkillAgentFactory."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.acp.skill_factory import SkillAgentFactory
from myrm_agent_harness.toolkits.acp.server.mcp_converter import convert_acp_mcp_servers
from myrm_agent_harness.toolkits.mcp.config import MCPConfig


class _FakeStdioMcp:
    def __init__(self, name: str, command: str, args: list[str], env: object) -> None:
        self.name = name
        self.command = command
        self.args = args
        self.env = env


class _FakeEnvEntry:
    def __init__(self, name: str, value: str) -> None:
        self.name = name
        self.value = value


class _FakeSseMcp:
    def __init__(self, name: str, url: str, headers: object = None) -> None:
        self.name = name
        self.url = url
        self.headers = headers


def test_convert_acp_mcp_servers_empty() -> None:
    assert convert_acp_mcp_servers(None) == []
    assert convert_acp_mcp_servers([]) == []


def test_convert_acp_mcp_servers_already_mcp_config() -> None:
    cfg = MCPConfig(name="test_direct", type="stdio", command="echo")
    res = convert_acp_mcp_servers([cfg])
    assert len(res) == 1
    assert res[0] is cfg


def test_convert_acp_mcp_servers_stdio_with_env_list() -> None:
    env_items = [_FakeEnvEntry("FOO", "BAR"), _FakeEnvEntry("BAZ", "QUX")]
    raw = _FakeStdioMcp("host_fs", "mcp-fs-tool", ["--root", "/workspace"], env_items)
    res = convert_acp_mcp_servers([raw])
    assert len(res) == 1
    cfg = res[0]
    assert cfg.name == "host_fs"
    assert cfg.type == "stdio"
    assert cfg.command == "mcp-fs-tool"
    assert cfg.args == ["--root", "/workspace"]
    assert cfg.extra_params == {"env": {"FOO": "BAR", "BAZ": "QUX"}}


def test_convert_acp_mcp_servers_stdio_with_env_dict() -> None:
    raw = {
        "name": "dict_tool",
        "command": "python",
        "args": ["-m", "tool"],
        "env": {"DEBUG": "1"},
    }
    res = convert_acp_mcp_servers([raw])
    assert len(res) == 1
    cfg = res[0]
    assert cfg.name == "dict_tool"
    assert cfg.type == "stdio"
    assert cfg.extra_params == {"env": {"DEBUG": "1"}}


def test_convert_acp_mcp_servers_sse_and_http() -> None:
    sse_item = _FakeSseMcp("remote_sse", "http://localhost:8000/sse")
    http_item = _FakeSseMcp("remote_stream", "http://localhost:8000/mcp/stream")

    res = convert_acp_mcp_servers([sse_item, http_item])
    assert len(res) == 2
    assert res[0].type == "sse"
    assert res[1].type == "streamable_http"


@pytest.mark.asyncio
async def test_skill_agent_factory_creates_agent_with_mcp() -> None:
    factory = SkillAgentFactory(
        system_prompt="Test system prompt",
        allowed_tools=["read_file"],
        skill_ids=["skill_a"],
    )

    fake_mcp = [MCPConfig(name="host_mcp", type="stdio", command="tool")]

    with patch(
        "myrm_agent_harness.agent._factory.builder.create_skill_agent",
        new_callable=AsyncMock,
    ) as mock_builder:
        mock_builder.return_value = MagicMock()
        agent = await factory.create_agent(
            session_id="session_12345678",
            cwd="/test/workspace",
            mcp_servers=fake_mcp,
        )

        assert agent is not None
        mock_builder.assert_awaited_once()
        _, kwargs = mock_builder.await_args
        spec = kwargs["spec"]
        assert spec.system_prompt == "Test system prompt"
        assert spec.allowed_tools == ["read_file"]
        assert spec.skill_ids == ["skill_a"]
        assert spec.workspace_binding.root_path == "/test/workspace"
        assert len(spec.mcp_servers) == 1
        assert spec.mcp_servers[0].name == "host_mcp"
