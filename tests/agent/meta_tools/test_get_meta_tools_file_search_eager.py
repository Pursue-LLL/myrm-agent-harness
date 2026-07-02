"""Tests that glob_tool/grep_tool stay eager when file_ops is enabled.

Roadmap P1 verdict (2026-07-02): glob/grep deferred-only is rejected; they must
mount with file_read/write/edit via enable_file_tools, not discover deferred pool.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools import get_meta_tools
from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
    sync_discover_capability_tool,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.backends.skills.types import SkillMetadata


@pytest.fixture
def skill_backend() -> MagicMock:
    backend = MagicMock()
    backend.load_skill = MagicMock()
    return backend


class TestFileSearchEager:
    def test_glob_grep_in_resolved_tools_when_file_ops_enabled(
        self,
        skill_backend: MagicMock,
    ) -> None:
        registry = ToolRegistry()
        tools = get_meta_tools(
            [],
            skill_backend,
            registry=registry,
            enable_file_tools=True,
            enable_bash=False,
            enable_answer_tool=False,
        )

        returned_names = {t.name for t in tools}
        assert {"glob_tool", "grep_tool"}.issubset(returned_names)
        assert {"file_read_tool", "file_write_tool", "file_edit_tool"}.issubset(returned_names)

    def test_glob_grep_not_in_deferred_registry(
        self,
        skill_backend: MagicMock,
    ) -> None:
        registry = ToolRegistry()
        get_meta_tools(
            [],
            skill_backend,
            registry=registry,
            enable_file_tools=True,
            enable_bash=False,
            enable_answer_tool=False,
        )

        deferred_names = {t.name for t in registry.get_deferred_tools()}
        assert "glob_tool" not in deferred_names
        assert "grep_tool" not in deferred_names

    def test_glob_grep_absent_when_file_ops_disabled(
        self,
        skill_backend: MagicMock,
    ) -> None:
        registry = ToolRegistry()
        tools = get_meta_tools(
            [],
            skill_backend,
            registry=registry,
            enable_file_tools=False,
            enable_bash=False,
            enable_answer_tool=False,
        )

        returned_names = {t.name for t in tools}
        assert "glob_tool" not in returned_names
        assert "grep_tool" not in returned_names

    def test_discover_does_not_list_glob_grep_as_deferred_native(
        self,
        skill_backend: MagicMock,
    ) -> None:
        sample_skill = SkillMetadata(
            name="demo_skill",
            description="Demo skill for testing",
            model_invocable=True,
            available=True,
        )
        registry = ToolRegistry()
        get_meta_tools(
            [sample_skill],
            skill_backend,
            registry=registry,
            enable_file_tools=True,
            enable_bash=False,
            enable_answer_tool=False,
        )
        sync_discover_capability_tool(registry, skills=[sample_skill])
        discover = next(
            t for t in registry.resolve() if t.name == "discover_capability_tool"
        )
        description = discover.description or ""
        assert "glob_tool" not in description
        assert "grep_tool" not in description
        assert "skill_analyze_tool" in description

    def test_bash_process_tools_deferred_when_bash_enabled(
        self,
        skill_backend: MagicMock,
    ) -> None:
        registry = ToolRegistry()
        tools = get_meta_tools(
            [],
            skill_backend,
            registry=registry,
            enable_file_tools=False,
            enable_bash=True,
            enable_answer_tool=False,
        )

        returned_names = {t.name for t in tools}
        assert "bash_code_execute_tool" in returned_names
        assert "bash_process_list_tool" not in returned_names

        deferred_names = {t.name for t in registry.get_deferred_tools()}
        assert {
            "bash_process_list_tool",
            "bash_process_output_tool",
            "bash_process_kill_tool",
        }.issubset(deferred_names)

    def test_answer_tool_eager_when_enabled(
        self,
        skill_backend: MagicMock,
    ) -> None:
        tools = get_meta_tools(
            [],
            skill_backend,
            registry=ToolRegistry(),
            enable_file_tools=False,
            enable_bash=False,
            enable_answer_tool=True,
        )

        returned_names = {t.name for t in tools}
        assert "request_answer_user_tool" in returned_names
