"""get_meta_tools mounts read-only file_read for SPILL_AND_UPLOADS mode."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools import get_meta_tools
from myrm_agent_harness.agent.meta_tools.mount_policy import FileAccessMode
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry


def test_spill_and_uploads_mounts_file_read_only() -> None:
    registry = ToolRegistry()
    tools = get_meta_tools(
        [],
        skill_backend=None,
        registry=registry,
        file_access_mode=FileAccessMode.SPILL_AND_UPLOADS,
        enable_shell_tools=False,
    )
    names = {t.name for t in tools}
    assert names == {"file_read_tool"}


def test_full_file_access_mounts_all_file_tools() -> None:
    registry = ToolRegistry()
    tools = get_meta_tools(
        [],
        skill_backend=None,
        registry=registry,
        file_access_mode=FileAccessMode.FULL,
        enable_shell_tools=False,
    )
    names = {t.name for t in tools}
    assert "file_read_tool" in names
    assert "file_write_tool" in names
    assert "glob_tool" in names


def test_none_file_access_skips_file_meta_tools() -> None:
    registry = ToolRegistry()
    tools = get_meta_tools(
        [],
        skill_backend=None,
        registry=registry,
        file_access_mode=FileAccessMode.NONE,
        enable_shell_tools=False,
    )
    names = {t.name for t in tools}
    assert "file_read_tool" not in names
    assert "file_write_tool" not in names
    assert "glob_tool" not in names
