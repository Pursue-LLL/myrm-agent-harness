"""get_meta_tools mounts read-only file_read when enable_evicted_read is set."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools import get_meta_tools
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry


def test_evicted_read_mounts_file_read_only() -> None:
    registry = ToolRegistry()
    tools = get_meta_tools(
        [],
        skill_backend=None,
        registry=registry,
        enable_file_tools=False,
        enable_evicted_read=True,
        enable_shell_tools=False,
    )
    names = {t.name for t in tools}
    assert names == {"file_read_tool"}


def test_full_file_tools_do_not_use_evicted_read_flag() -> None:
    registry = ToolRegistry()
    tools = get_meta_tools(
        [],
        skill_backend=None,
        registry=registry,
        enable_file_tools=True,
        enable_evicted_read=True,
        enable_shell_tools=False,
    )
    names = {t.name for t in tools}
    assert "file_read_tool" in names
    assert "file_write_tool" in names
    assert "glob_tool" in names


def test_neither_file_tools_nor_evicted_read_skips_file_meta_tools() -> None:
    registry = ToolRegistry()
    tools = get_meta_tools(
        [],
        skill_backend=None,
        registry=registry,
        enable_file_tools=False,
        enable_evicted_read=False,
        enable_shell_tools=False,
    )
    names = {t.name for t in tools}
    assert "file_read_tool" not in names
    assert "file_write_tool" not in names
    assert "glob_tool" not in names
