"""Tests for agent._internals.agent_runtime helper functions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.tools import tool

from myrm_agent_harness.agent.tool_management.types import ToolBindMode, ToolSource


def _unwrap_middleware(middleware: object) -> object:
    from myrm_agent_harness.agent.middlewares.sync_hook_parity import SyncHookParityAdapter

    if isinstance(middleware, SyncHookParityAdapter):
        return object.__getattribute__(middleware, "_inner")
    return middleware


def _middleware_class_names(middlewares: list[object]) -> list[str]:
    return [type(_unwrap_middleware(middleware)).__name__ for middleware in middlewares]


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
        assert _unwrap_middleware(result[-1]) is debug_logger_middleware

    def test_deferred_normalizer_runs_before_after_model_policies(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            build_middlewares,
            create_registry,
        )

        result = build_middlewares(create_registry(), [])
        class_names = _middleware_class_names(result)
        assert class_names[-2] == "SkillAttenuationMiddleware"
        assert class_names.index("SkillAttenuationMiddleware") > class_names.index("ToolApprovalMiddleware")

    def test_contains_core_middlewares(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            build_middlewares,
            create_registry,
        )

        result = build_middlewares(create_registry(), [])
        class_names = {type(_unwrap_middleware(mw)).__name__ for mw in result}
        assert "ToolHistoryHygieneMiddleware" in class_names
        assert "DanglingToolCallMiddleware" in class_names
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


class TestBuildTools:
    """Tests for build_tools — resolves user-supplied Turn1 tools."""

    @pytest.mark.asyncio
    async def test_build_tools_resolves_user_tools(self) -> None:
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

    def test_emit_excludes_runtime_only_hooks(self) -> None:
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
            """Runtime-only cron hook."""
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

    def test_resets_context_budget_cumulative_usage(self):
        """Per-run budget must start clean, else predictive truncation stays pinned."""
        from myrm_agent_harness.agent._internals.agent_runtime import reset_all_guards
        from myrm_agent_harness.agent.security.guards.context_budget import (
            get_context_budget_guard,
            reset_context_budget_guard,
        )

        guard = get_context_budget_guard()
        try:
            for i in range(45):
                guard.check_and_truncate("x" * 20_000, f"tool_{i}")

            exhausted = guard.check_and_truncate("y" * 20_000, "probe_before_reset")
            assert len(exhausted.content) < 20_000, "fixture failed to exhaust the budget"

            reset_all_guards()

            fresh = guard.check_and_truncate("z" * 20_000, "probe_after_reset")
            assert len(fresh.content) == 20_000
        finally:
            reset_context_budget_guard()

    def test_preserves_context_budget_on_approval_resume(self):
        """An approval resume continues the same run, so its usage must carry over."""
        from myrm_agent_harness.agent._internals.agent_runtime import reset_all_guards
        from myrm_agent_harness.agent.security.guards.context_budget import (
            get_context_budget_guard,
            reset_context_budget_guard,
        )

        guard = get_context_budget_guard()
        try:
            for i in range(45):
                guard.check_and_truncate("x" * 20_000, f"pre_approval_{i}")
            exhausted = guard.check_and_truncate("y" * 20_000, "probe_before_resume")
            assert len(exhausted.content) < 20_000, "fixture failed to exhaust the budget"

            reset_all_guards(is_resume=True)

            carried = guard.check_and_truncate("z" * 20_000, "probe_after_resume")
            assert len(carried.content) < 20_000
        finally:
            reset_context_budget_guard()


class TestSchedulePostRunIdleTasks:
    """Tests for schedule_post_run_idle_tasks — enqueues background work."""

    @pytest.mark.parametrize(
        "context",
        [{"workspaces_storage_root": "/tmp"}, {"session_id": "abc"}],
        ids=["missing-session-id", "missing-storage-root"],
    )
    def test_incomplete_context_never_touches_the_registry(self, context):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            schedule_post_run_idle_tasks,
        )

        with patch("myrm_agent_harness.agent.background_worker.registry.get_idle_task_registry") as get_registry:
            schedule_post_run_idle_tasks(context)

        get_registry.assert_not_called()

    def test_empty_context_is_noop(self):
        from myrm_agent_harness.agent._internals.agent_runtime import (
            schedule_post_run_idle_tasks,
        )

        schedule_post_run_idle_tasks({})


class TestRunAgentLoopCatalogWiring:
    """The catalog and history seams sit where the turn is assembled; behavior lives in their own test files."""

    @staticmethod
    def _awaited_calls() -> list[str]:
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "src/myrm_agent_harness/agent/_internals/agent_runtime.py"
        ).read_text(encoding="utf-8")
        return [ast.unparse(n.value) for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Await)]

    def test_new_message_turn_resolves_history_before_it_delivers_the_catalog(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "src/myrm_agent_harness/agent/_internals/agent_runtime.py"
        ).read_text(encoding="utf-8")
        history_idx = source.index("await resolve_turn_history(")
        build_idx = source.index("build_messages(query, fed_history)", history_idx)
        inject_idx = source.index("inject_datetime_tags(messages, fed_history, query)", build_idx)
        catalog_idx = source.index("await deliver_bound_skills_catalog(messages, agent_state, history)", inject_idx)
        assert history_idx < build_idx < inject_idx < catalog_idx
        assert catalog_idx - inject_idx < 200

    def test_resume_syncs_the_skill_index_without_rewriting_the_checkpoint(self) -> None:
        awaits = self._awaited_calls()
        assert any("sync_bound_skills_for_resume(" in awaited for awaited in awaits)
        assert not any("update_state" in awaited for awaited in awaits)

    def test_resume_reports_itself_without_resolving_history(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "src/myrm_agent_harness/agent/_internals/agent_runtime.py"
        ).read_text(encoding="utf-8")
        resume_idx = source.index("record_turn_context(resumed_turn_facts())")
        assert source.index("await sync_bound_skills_for_resume(") < resume_idx
        assert resume_idx < source.index("await resolve_turn_history(")

    def test_history_mode_declaration_is_consumed_before_the_context_reaches_middleware(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "src/myrm_agent_harness/agent/_internals/agent_runtime.py"
        ).read_text(encoding="utf-8")
        assert "merged_context.pop(HISTORY_MODE_CONTEXT_KEY, None)" in source


class TestPopCheckpointIncompatibleMergedContext:
    """Regression: callables must not remain in merged_context for LangGraph checkpoint."""

    def test_file_content_reader_stripped_from_merged_context(self) -> None:
        from myrm_agent_harness.agent._internals._agent_helpers import (
            pop_checkpoint_incompatible_merged_context,
        )

        async def reader(_file_id: str) -> bytes:
            return b""

        merged: dict[str, object] = {
            "workspace_root": "/tmp",
            "session_id": "sess-1",
            "file_content_reader": reader,
        }

        stripped = pop_checkpoint_incompatible_merged_context(merged)

        assert "file_content_reader" not in merged
        assert callable(stripped["file_content_reader"])
        assert merged == {"workspace_root": "/tmp", "session_id": "sess-1"}

    def test_all_checkpoint_callbacks_stripped(self) -> None:
        from myrm_agent_harness.agent._internals._agent_helpers import (
            pop_checkpoint_incompatible_merged_context,
        )

        goal_provider = MagicMock()
        on_terminal = MagicMock()
        on_restart = MagicMock()

        merged: dict[str, object] = {
            "goal_provider": goal_provider,
            "on_goal_terminal": on_terminal,
            "on_loop_restart": on_restart,
            "file_content_reader": lambda _fid: b"",
            "keep": "value",
        }

        stripped = pop_checkpoint_incompatible_merged_context(merged)

        assert set(stripped.keys()) == {
            "goal_provider",
            "on_goal_terminal",
            "on_loop_restart",
            "file_content_reader",
        }
        assert merged == {"keep": "value"}
        assert stripped["goal_provider"] is goal_provider


class TestRunAgentLoopModelSlugSource:
    """Regression: run_agent_loop must resolve the primary model slug from the agent LLM.

    AgentRuntimeConfig has no ``llm`` field; reading ``agent_state.config.llm.model``
    raised AttributeError on every agent run before this regression test was added.
    The access is via ``getattr`` so custom LLM objects that omit ``model_name``
    (e.g. test fakes) degrade gracefully instead of raising.
    """

    def test_model_slug_reads_from_agent_llm_not_config(self) -> None:
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "src/myrm_agent_harness/agent/_internals/agent_runtime.py"
        ).read_text(encoding="utf-8")
        # Compare signatures rebuilt from the AST so quote style and line wrapping
        # in the module under test cannot invalidate this regression guard.
        tree = ast.parse(source)
        calls = {ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        attributes = {ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert "parse_litellm_model(llm_model or '')" in calls
        assert "getattr(agent_state.llm, 'model_name', None)" in calls
        assert "agent_state.config.llm" not in attributes


class TestRunAgentLoopOuterErrorFaultSide:
    """Regression: the outer-loop error_event must carry deterministic fault
    side + recovery actions so the GUI's trace timeline shows who owns the
    failure even when the executor loop itself raises (measurement decay guard
    — this branch previously dropped fault_side/recovery_actions)."""

    def test_outer_error_event_attributes_fault_side(self) -> None:
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "src/myrm_agent_harness/agent/_internals/agent_runtime.py"
        ).read_text(encoding="utf-8")

        def calls() -> set[str]:
            """Call signatures rebuilt from the AST, so line wrapping is irrelevant."""
            return {ast.unparse(node) for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)}

        signatures = calls()
        # fault_side must be computed via the pure-rules classifier, not guessed.
        assert "classify_fault_side(error_kind=error_kind.value)" in signatures
        # When error_kind is UNKNOWN, the diagnostic error_type refines the
        # attribution (unified classifier falls back error_kind → error_type).
        refined = [sig for sig in signatures if sig.startswith("classify_fault_side(") and "error_type" in sig]
        assert refined, "no classify_fault_side call passes error_type for diagnostic refinement"
        assert any("error_type=diagnostic_type" in sig for sig in refined)
        # recovery_actions must be generated when a diagnostic payload exists.
        assert any(sig.startswith("LLMErrorDiagnostic.get_recovery_actions(") for sig in signatures)
        # The outer-loop error_event must be persisted to the event journal
        # (transport-only fields stripped) so trace reconstruction sees fatal
        # errors raised outside the executor.
        assert "event_logger.log(AgentEventType.ERROR.value, persisted)" in signatures
        assert "persisted.pop('type', None)" in signatures
        assert "persisted.pop('messageId', None)" in signatures
