"""Tests for agent._internals.agent_runtime helper functions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.tools import tool

from myrm_agent_harness.agent.tool_management.types import ToolBindMode, ToolSource


class TestExtractQueryText:
    """Tests for extract_query_text — converts various input types to readable strings."""

    def test_string_input(self):
        from myrm_agent_harness.agent._internals.agent_runtime import extract_query_text

        assert extract_query_text("hello world") == "hello world"

    def test_empty_string(self):
        from myrm_agent_harness.agent._internals.agent_runtime import extract_query_text

        assert extract_query_text("") == ""

    def test_list_with_text_part(self):
        from myrm_agent_harness.agent._internals.agent_runtime import extract_query_text

        parts = [{"type": "text", "text": "What is 2+2?"}]
        assert extract_query_text(parts) == "What is 2+2?"

    def test_list_without_text_part(self):
        from myrm_agent_harness.agent._internals.agent_runtime import extract_query_text

        parts = [{"type": "image", "url": "http://example.com/img.png"}]
        assert extract_query_text(parts) == ""

    def test_list_multiple_parts(self):
        from myrm_agent_harness.agent._internals.agent_runtime import extract_query_text

        parts = [
            {"type": "image", "url": "http://example.com/img.png"},
            {"type": "text", "text": "Describe this image"},
        ]
        assert extract_query_text(parts) == "Describe this image"

    def test_command_input(self):
        from langgraph.types import Command

        from myrm_agent_harness.agent._internals.agent_runtime import extract_query_text

        cmd = Command(resume="user approved")
        result = extract_query_text(cmd)
        assert "Resume:" in result
        assert "user approved" in result

    def test_unknown_type_fallback(self):
        from myrm_agent_harness.agent._internals.agent_runtime import extract_query_text

        assert extract_query_text(42) == "42"
        assert extract_query_text(None) == "None"


class TestBuildMiddlewares:
    """Tests for build_middlewares — assembles the full middleware chain."""

    def test_returns_list(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            build_middlewares,
            create_registry,
        )

        result = build_middlewares(create_registry(), [])
        assert isinstance(result, list)
        assert len(result) > 0

    def test_user_middlewares_included(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            build_middlewares,
            create_registry,
        )

        sentinel = MagicMock()
        result = build_middlewares(create_registry(), [sentinel])
        assert sentinel in result

    def test_debug_logger_is_last(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            build_middlewares,
            create_registry,
        )
        from myrm_agent_harness.agent.middlewares import debug_logger_middleware

        result = build_middlewares(create_registry(), [])
        assert result[-1] is debug_logger_middleware

    def test_deferred_normalizer_runs_before_after_model_policies(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            build_middlewares,
            create_registry,
        )

        result = build_middlewares(create_registry(), [])
        class_names = [type(middleware).__name__ for middleware in result]
        assert class_names[-2] == "SkillAttenuationMiddleware"
        assert class_names.index("SkillAttenuationMiddleware") > class_names.index("ToolApprovalMiddleware")

    def test_contains_core_middlewares(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            build_middlewares,
            create_registry,
        )

        result = build_middlewares(create_registry(), [])
        class_names = {type(mw).__name__ for mw in result}
        assert "ToolApprovalMiddleware" in class_names
        assert "CompletionGuard" in class_names
        assert "SecurityBoundaryMiddleware" in class_names
        assert "SecurityGuardrailMiddleware" in class_names

    def test_goal_focus_middleware_in_chain(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            build_middlewares,
            create_registry,
        )

        result = build_middlewares(create_registry(), [])
        names = {mw.name for mw in result}
        assert "progress_middleware" in names
        assert "goal_focus_middleware" in names

    """Tests for build_tools — resolves user and discoverable tools."""

    @pytest.mark.asyncio
    async def test_build_tools_merges_discoverable_into_user(self) -> None:
        from myrm_agent_harness.agent._internals.agent_runtime import (
            build_tools,
            create_registry,
        )

        registry = create_registry()

        @tool("web_search_tool")
        def web_search_tool(query: str) -> str:
            """Search the web."""
            return query

        @tool("bash_process_tool")
        def bash_process_tool(command: str) -> str:
            """Run bash commands."""
            return command

        tools = await build_tools(registry, [web_search_tool, bash_process_tool], [])
        names = [t.name for t in tools]

        assert "web_search_tool" in names
        assert "bash_process_tool" in names


class TestCreateRegistry:
    """Tests for create_registry — factory for ToolRegistry."""

    def test_returns_tool_registry(self):
        from myrm_agent_harness.agent._internals.agent_runtime import create_registry
        from myrm_agent_harness.agent.tool_management import ToolRegistry

        registry = create_registry()
        assert isinstance(registry, ToolRegistry)


class TestEmitToolsSnapshot:
    """Tests for emit_tools_snapshot — serializes tool snapshots."""

    def test_returns_none_when_no_snapshot(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            create_registry,
            emit_tools_snapshot,
        )

        assert emit_tools_snapshot(create_registry()) is None

    def test_returns_none_when_no_method(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            emit_tools_snapshot,
        )

        assert emit_tools_snapshot(object()) is None

    def test_serializes_snapshots(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            create_registry,
            emit_tools_snapshot,
        )

        @tool("bash_code_execute_tool")
        def bash_code_execute_tool(command: str) -> str:
            """Execute bash commands."""
            return command

        registry = create_registry()
        registry.register(bash_code_execute_tool, source=ToolSource.META)

        result = emit_tools_snapshot(registry)
        assert result is not None
        assert len(result) == 1
        assert result[0]["name"] == "bash_code_execute_tool"
        assert result[0]["source"] == "meta"
        assert result[0]["builtin_tool_id"] is None

    def test_emit_includes_builtin_tool_id_for_togglable_tools(self) -> None:
        from myrm_agent_harness.agent._internals.agent_runtime import (
            create_registry,
            emit_tools_snapshot,
        )

        @tool("cron_manage_tool")
        def cron_manage_tool(expr: str) -> str:
            """Manage scheduled tasks."""
            return expr

        registry = create_registry()
        registry.register(cron_manage_tool, source=ToolSource.USER)

        result = emit_tools_snapshot(registry)
        assert result is not None
        assert result[0]["builtin_tool_id"] == "cron"

    def test_emit_excludes_discoverable_and_runtime_only(self) -> None:
        from myrm_agent_harness.agent._internals.agent_runtime import (
            create_registry,
            emit_tools_snapshot,
        )

        @tool("visible_turn1_tool")
        def visible_turn1_tool(query: str) -> str:
            """Turn1 visible tool."""
            return query

        @tool("cron_manage_tool")
        def cron_manage_tool(expr: str) -> str:
            """Discoverable cron tool."""
            return expr

        registry = create_registry()
        registry.register(visible_turn1_tool, source=ToolSource.META)
        hook = MagicMock()
        hook.name = "_completion_check"
        hook.description = "Internal completion hook"
        registry.register(
            hook,
            source=ToolSource.MIDDLEWARE,
            bind_mode=ToolBindMode.RUNTIME_ONLY,
        )

        result = emit_tools_snapshot(registry)
        assert result is not None
        names = {row["name"] for row in result}
        assert names == {"visible_turn1_tool"}


class TestInitUsageLedger:
    """Tests for init_usage_ledger — attaches UsageLedger to request scope."""

    def test_none_context_is_noop(self):
        from myrm_agent_harness.agent._internals.agent_runtime import init_usage_ledger

        init_usage_ledger(None)

    def test_empty_context_is_noop(self):
        from myrm_agent_harness.agent._internals.agent_runtime import init_usage_ledger

        init_usage_ledger({})

    def test_no_workspace_path_is_noop(self):
        from myrm_agent_harness.agent._internals.agent_runtime import init_usage_ledger

        init_usage_ledger({"other_key": "value"})


class TestResetAllGuards:
    """Tests for reset_all_guards — resets per-request middleware state."""

    def test_does_not_raise(self):
        from myrm_agent_harness.agent._internals.agent_runtime import reset_all_guards

        reset_all_guards()

    def test_idempotent(self):
        from myrm_agent_harness.agent._internals.agent_runtime import reset_all_guards

        reset_all_guards()
        reset_all_guards()


class TestSchedulePostRunIdleTasks:
    """Tests for schedule_post_run_idle_tasks — enqueues background work."""

    def test_missing_session_id_is_noop(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            schedule_post_run_idle_tasks,
        )

        schedule_post_run_idle_tasks({"workspace_root": "/tmp"})

    def test_missing_workspace_root_is_noop(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            schedule_post_run_idle_tasks,
        )

        schedule_post_run_idle_tasks({"session_id": "abc"})

    def test_empty_context_is_noop(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            schedule_post_run_idle_tasks,
        )

        schedule_post_run_idle_tasks({})
