"""Tests for MCPFileSystemStrategy (virtual /mcp/ path read strategy).

Covers read_file / write_file / delete_file / replace_text / is_directory /
list_directory / exists / get_file_size / get_actual_path / _read_mcp_function_doc /
_get_mcp_call_rules across MCP-skill and non-MCP-skill paths.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.strategies.mcp_strategy import (
    MCPFileSystemStrategy,
)
from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata


def _mcp_skill_meta(name: str = "mcp_12306_mcp_skill") -> SkillMetadata:
    """MCP skill metadata with one function doc generation path."""
    mcp = MCPSkillData(
        server="12306-mcp",
        tools=["get-tickets"],
        config=[],
        tool_schemas={
            "get-tickets": {
                "description": "Query train tickets by date and route",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "Departure date",
                            "format": "date",
                        }
                    },
                    "required": ["date"],
                },
            }
        },
    )
    return SkillMetadata(name=name, description="Train tickets", mcp=mcp)


@pytest.fixture
def strategy() -> MCPFileSystemStrategy:
    return MCPFileSystemStrategy([_mcp_skill_meta()])


@pytest.fixture
def local_strategy() -> MCPFileSystemStrategy:
    return MCPFileSystemStrategy([SkillMetadata(name="local_skill", description="Local")])


class TestReadAndExists:
    async def test_read_file_returns_doc_lines(self, strategy) -> None:
        lines = await strategy.read_file("/mcp/mcp_12306_mcp_skill/get-tickets.md")
        assert isinstance(lines, list)
        assert any("Query train tickets" in line for line in lines)

    async def test_read_file_appends_call_rules(self, strategy) -> None:
        lines = await strategy.read_file("/mcp/mcp_12306_mcp_skill/get-tickets.md")
        joined = "\n".join(lines)
        assert "MCP Function Call Rules" in joined
        assert "get_tickets" in joined

    async def test_get_file_size_positive(self, strategy) -> None:
        size = await strategy.get_file_size("/mcp/mcp_12306_mcp_skill/get-tickets.md")
        assert isinstance(size, int)
        assert size > 0

    async def test_exists_directory(self, strategy) -> None:
        assert await strategy.exists("/mcp/mcp_12306_mcp_skill") is True

    async def test_exists_file(self, strategy) -> None:
        assert await strategy.exists("/mcp/mcp_12306_mcp_skill/get-tickets.md") is True

    async def test_exists_unknown_skill_false(self, strategy) -> None:
        assert await strategy.exists("/mcp/unknown_skill") is False

    async def test_exists_unknown_function_false(self, strategy) -> None:
        assert await strategy.exists("/mcp/mcp_12306_mcp_skill/missing.md") is False

    async def test_get_actual_path_returns_self(self, strategy) -> None:
        path = "/mcp/mcp_12306_mcp_skill/get-tickets.md"
        assert strategy.get_actual_path(path) == path


class TestIsDirectory:
    async def test_skill_dir(self, strategy) -> None:
        assert await strategy.is_directory("/mcp/mcp_12306_mcp_skill") is True

    async def test_function_file_not_dir(self, strategy) -> None:
        assert await strategy.is_directory("/mcp/mcp_12306_mcp_skill/get-tickets.md") is False

    async def test_unknown_skill_not_dir(self, strategy) -> None:
        assert await strategy.is_directory("/mcp/unknown_skill") is False

    async def test_non_mcp_skill_not_dir(self, local_strategy) -> None:
        assert await local_strategy.is_directory("/mcp/local_skill") is False


class TestListDirectory:
    async def test_lists_function_docs(self, strategy) -> None:
        entries = await strategy.list_directory("/mcp/mcp_12306_mcp_skill")
        assert len(entries) == 1
        assert entries[0][0] == "get_tickets.md"
        assert entries[0][1] is False
        assert entries[0][2] == 1024

    async def test_invalid_path_raises(self, strategy) -> None:
        with pytest.raises(NotADirectoryError):
            await strategy.list_directory("/mcp/a/b/c")

    async def test_unknown_skill_raises(self, strategy) -> None:
        with pytest.raises(FileNotFoundError):
            await strategy.list_directory("/mcp/unknown_skill")

    async def test_non_mcp_skill_raises(self, local_strategy) -> None:
        with pytest.raises(ValueError, match="not an MCP skill"):
            await local_strategy.list_directory("/mcp/local_skill")


class TestWriteDenied:
    async def test_write_file_denied(self, strategy) -> None:
        with pytest.raises(PermissionError):
            await strategy.write_file("/mcp/x/y.md", "content")

    async def test_delete_file_denied(self, strategy) -> None:
        with pytest.raises(PermissionError):
            await strategy.delete_file("/mcp/x/y.md")

    async def test_replace_text_denied(self, strategy) -> None:
        with pytest.raises(PermissionError):
            await strategy.replace_text("/mcp/x/y.md", "a", "b")


class TestReadDocErrors:
    async def test_invalid_path_format_raises(self, strategy) -> None:
        with pytest.raises(ValueError, match="Invalid MCP path"):
            strategy._read_mcp_function_doc("/mcp/only_two_parts")

    async def test_unknown_skill_raises(self, strategy) -> None:
        with pytest.raises(FileNotFoundError, match="Skill not found"):
            strategy._read_mcp_function_doc("/mcp/unknown_skill/get-tickets.md")

    async def test_non_mcp_skill_raises(self, local_strategy) -> None:
        with pytest.raises(ValueError, match="not an MCP skill"):
            local_strategy._read_mcp_function_doc("/mcp/local_skill/whatever.md")

    async def test_unknown_function_raises(self, strategy) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            strategy._read_mcp_function_doc("/mcp/mcp_12306_mcp_skill/missing.md")


class TestGetMcpCallRules:
    def test_example_code_block_has_no_undefined_variable(self) -> None:
        rules = MCPFileSystemStrategy._get_mcp_call_rules()
        example_block = rules.split("```python")[1].split("```")[0]
        assert "{variable}" not in example_block
        assert "{result}" in example_block

    def test_format_guidance_line_keeps_variable_placeholder(self) -> None:
        rules = MCPFileSystemStrategy._get_mcp_call_rules()
        assert 'print(f"[OBSERVATION] {variable}")' in rules
