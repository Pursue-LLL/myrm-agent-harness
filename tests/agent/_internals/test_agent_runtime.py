"""Tests for agent._internals.agent_runtime helper functions."""

from __future__ import annotations

from unittest.mock import MagicMock

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


class TestApplyBoundSkillCatalogForStream:
    """Integration tests for SkillAgent stream catalog hook."""

    @pytest.mark.asyncio
    async def test_skill_agent_injects_bound_skills_on_first_human_message(self) -> None:
        from unittest.mock import AsyncMock

        from langchain_core.messages import HumanMessage

        from myrm_agent_harness.agent._internals.agent_runtime import (
            apply_bound_skill_catalog_for_stream,
        )
        from myrm_agent_harness.agent.skill_agent import SkillAgent
        from myrm_agent_harness.backends.skills.types import SkillMetadata

        skill = SkillMetadata(
            name="alpha_skill",
            description="alpha",
            model_invocable=True,
            available=True,
        )
        mock_backend = AsyncMock()
        mock_backend.list_skills = AsyncMock(return_value=[skill])
        agent = SkillAgent(llm=AsyncMock(), skill_backend=mock_backend)

        messages = [HumanMessage(content="hello")]
        await apply_bound_skill_catalog_for_stream(messages, agent)

        first = messages[0]
        assert isinstance(first.content, str)
        assert first.content.startswith("<bound_skills")
        assert "alpha_skill" in first.content
        assert "hello" in first.content

    @pytest.mark.asyncio
    async def test_non_skill_agent_leaves_messages_unchanged(self) -> None:
        from unittest.mock import MagicMock

        from langchain_core.messages import HumanMessage

        from myrm_agent_harness.agent._internals.agent_runtime import (
            apply_bound_skill_catalog_for_stream,
        )
        from myrm_agent_harness.agent.base_agent import BaseAgent

        agent = MagicMock(spec=BaseAgent)
        messages = [HumanMessage(content="hello")]
        await apply_bound_skill_catalog_for_stream(messages, agent)
        assert messages[0].content == "hello"

    @pytest.mark.asyncio
    async def test_skill_agent_without_backend_leaves_messages_unchanged(self) -> None:
        from unittest.mock import AsyncMock

        from langchain_core.messages import HumanMessage

        from myrm_agent_harness.agent._internals.agent_runtime import (
            apply_bound_skill_catalog_for_stream,
        )
        from myrm_agent_harness.agent.skill_agent import SkillAgent

        agent = SkillAgent(llm=AsyncMock(), skill_backend=None)
        messages = [HumanMessage(content="hello")]
        await apply_bound_skill_catalog_for_stream(messages, agent)
        assert messages[0].content == "hello"

    def test_run_agent_loop_wires_catalog_helper_after_datetime_inject(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "src/myrm_agent_harness/agent/_internals/agent_runtime.py"
        ).read_text(encoding="utf-8")
        inject_idx = source.index("inject_datetime_tags(messages, chat_history, query)")
        hook_idx = source.index(
            "await apply_bound_skill_catalog_for_stream(messages, agent_state)",
            inject_idx,
        )
        assert hook_idx > inject_idx
        assert hook_idx - inject_idx < 200


class TestApplyBoundSkillCatalogForResume:
    """Resume path must refresh stale checkpoint catalog before LangGraph continue."""

    @pytest.mark.asyncio
    async def test_resume_updates_command_when_skill_bind_changes(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from langchain_core.messages import HumanMessage
        from langgraph.types import Command

        from myrm_agent_harness.agent._internals.agent_runtime import (
            apply_bound_skill_catalog_for_resume,
        )
        from myrm_agent_harness.agent.skill_agent import SkillAgent
        from myrm_agent_harness.agent.skills.runtime.skill_catalog_delivery import (
            build_bound_skills_block,
        )
        from myrm_agent_harness.backends.skills.types import SkillMetadata

        old_skill = SkillMetadata(
            name="old_skill",
            description="old",
            model_invocable=True,
            available=True,
        )
        new_skill = SkillMetadata(
            name="new_skill",
            description="new",
            model_invocable=True,
            available=True,
        )
        stale_block = build_bound_skills_block([old_skill])
        messages = [HumanMessage(content=f"{stale_block}\n\nfirst question")]

        mock_backend = AsyncMock()
        mock_backend.load_skills = AsyncMock(return_value=[new_skill])

        agent = SkillAgent(llm=AsyncMock(), skill_backend=mock_backend)
        agent._desired_skill_ids = ["new_skill"]

        state_snapshot = MagicMock()
        state_snapshot.values = {"messages": messages}

        mock_graph = AsyncMock()
        mock_graph.aget_state = AsyncMock(return_value=state_snapshot)
        agent._agent = mock_graph

        command = Command(resume={"decision": "approve"})
        refreshed = await apply_bound_skill_catalog_for_resume(agent, command, thread_id="thread-1")

        assert refreshed is not command
        assert refreshed.update is not None
        updated_messages = refreshed.update.get("messages")
        assert isinstance(updated_messages, list)
        first = updated_messages[0]
        assert isinstance(first.content, str)
        assert "new_skill" in first.content
        assert "old_skill" not in first.content
        assert refreshed.resume == {"decision": "approve"}

    @pytest.mark.asyncio
    async def test_resume_no_op_when_catalog_already_current(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from langchain_core.messages import HumanMessage
        from langgraph.types import Command

        from myrm_agent_harness.agent._internals.agent_runtime import (
            apply_bound_skill_catalog_for_resume,
        )
        from myrm_agent_harness.agent.skill_agent import SkillAgent
        from myrm_agent_harness.agent.skills.runtime.skill_catalog_delivery import (
            build_bound_skills_block,
        )
        from myrm_agent_harness.backends.skills.types import SkillMetadata

        skill = SkillMetadata(
            name="alpha_skill",
            description="alpha",
            model_invocable=True,
            available=True,
        )
        block = build_bound_skills_block([skill])
        messages = [HumanMessage(content=f"{block}\n\nhello")]

        mock_backend = AsyncMock()
        mock_backend.list_skills = AsyncMock(return_value=[skill])

        agent = SkillAgent(llm=AsyncMock(), skill_backend=mock_backend)

        state_snapshot = MagicMock()
        state_snapshot.values = {"messages": messages}

        mock_graph = AsyncMock()
        mock_graph.aget_state = AsyncMock(return_value=state_snapshot)
        agent._agent = mock_graph

        command = Command(resume="continue")
        refreshed = await apply_bound_skill_catalog_for_resume(agent, command, thread_id="thread-2")

        assert refreshed is command
        assert refreshed.update is None

    @pytest.mark.asyncio
    async def test_resume_updates_multimodal_human_message_content(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from langchain_core.messages import HumanMessage
        from langgraph.types import Command

        from myrm_agent_harness.agent._internals.agent_runtime import (
            apply_bound_skill_catalog_for_resume,
        )
        from myrm_agent_harness.agent.skill_agent import SkillAgent
        from myrm_agent_harness.agent.skills.runtime.skill_catalog_delivery import (
            build_bound_skills_block,
        )
        from myrm_agent_harness.backends.skills.types import SkillMetadata

        stale_skill = SkillMetadata(
            name="stale_skill",
            description="stale",
            model_invocable=True,
            available=True,
        )
        fresh_skill = SkillMetadata(
            name="fresh_skill",
            description="fresh",
            model_invocable=True,
            available=True,
        )
        stale_block = build_bound_skills_block([stale_skill])
        messages = [
            HumanMessage(
                content=[
                    {"type": "text", "text": f"{stale_block}\n\nquestion with image"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
                ]
            )
        ]

        mock_backend = AsyncMock()
        mock_backend.list_skills = AsyncMock(return_value=[fresh_skill])
        agent = SkillAgent(llm=AsyncMock(), skill_backend=mock_backend)

        state_snapshot = MagicMock()
        state_snapshot.values = {"messages": messages}

        mock_graph = AsyncMock()
        mock_graph.aget_state = AsyncMock(return_value=state_snapshot)
        agent._agent = mock_graph

        command = Command(resume={"decision": "approve"})
        refreshed = await apply_bound_skill_catalog_for_resume(agent, command, thread_id="thread-multimodal")

        assert refreshed is not command
        updated_messages = refreshed.update.get("messages")
        first_content = updated_messages[0].content
        assert isinstance(first_content, list)
        text_part = next(part for part in first_content if part.get("type") == "text")
        assert "fresh_skill" in text_part["text"]
        assert "stale_skill" not in text_part["text"]

    @pytest.mark.asyncio
    async def test_resume_no_op_when_skill_backend_missing(self) -> None:
        from unittest.mock import AsyncMock

        from langgraph.types import Command

        from myrm_agent_harness.agent._internals.agent_runtime import (
            apply_bound_skill_catalog_for_resume,
        )
        from myrm_agent_harness.agent.skill_agent import SkillAgent

        agent = SkillAgent(llm=AsyncMock(), skill_backend=None)
        command = Command(resume="continue")
        refreshed = await apply_bound_skill_catalog_for_resume(agent, command, thread_id="t-no-backend")
        assert refreshed is command

    @pytest.mark.asyncio
    async def test_resume_no_op_for_non_skill_agent(self) -> None:
        from unittest.mock import MagicMock

        from langgraph.types import Command

        from myrm_agent_harness.agent._internals.agent_runtime import (
            apply_bound_skill_catalog_for_resume,
        )
        from myrm_agent_harness.agent.base_agent import BaseAgent

        agent = MagicMock(spec=BaseAgent)
        command = Command(resume="continue")
        refreshed = await apply_bound_skill_catalog_for_resume(agent, command, thread_id="t-non-skill")
        assert refreshed is command

    @pytest.mark.asyncio
    async def test_resume_no_op_when_agent_graph_missing(self) -> None:
        from unittest.mock import AsyncMock

        from langgraph.types import Command

        from myrm_agent_harness.agent._internals.agent_runtime import (
            apply_bound_skill_catalog_for_resume,
        )
        from myrm_agent_harness.agent.skill_agent import SkillAgent

        agent = SkillAgent(llm=AsyncMock(), skill_backend=AsyncMock())
        agent._agent = None
        command = Command(resume="continue")
        refreshed = await apply_bound_skill_catalog_for_resume(agent, command, thread_id="t-no-graph")
        assert refreshed is command

    @pytest.mark.asyncio
    async def test_resume_no_op_when_aget_state_fails(self) -> None:
        from unittest.mock import AsyncMock

        from langgraph.types import Command

        from myrm_agent_harness.agent._internals.agent_runtime import (
            apply_bound_skill_catalog_for_resume,
        )
        from myrm_agent_harness.agent.skill_agent import SkillAgent

        agent = SkillAgent(llm=AsyncMock(), skill_backend=AsyncMock())
        mock_graph = AsyncMock()
        mock_graph.aget_state = AsyncMock(side_effect=RuntimeError("checkpoint down"))
        agent._agent = mock_graph

        command = Command(resume="continue")
        refreshed = await apply_bound_skill_catalog_for_resume(agent, command, thread_id="t-fail-state")
        assert refreshed is command

    @pytest.mark.asyncio
    async def test_resume_no_op_when_checkpoint_has_no_messages(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from langgraph.types import Command

        from myrm_agent_harness.agent._internals.agent_runtime import (
            apply_bound_skill_catalog_for_resume,
        )
        from myrm_agent_harness.agent.skill_agent import SkillAgent

        agent = SkillAgent(llm=AsyncMock(), skill_backend=AsyncMock())
        state_snapshot = MagicMock()
        state_snapshot.values = {"messages": []}
        mock_graph = AsyncMock()
        mock_graph.aget_state = AsyncMock(return_value=state_snapshot)
        agent._agent = mock_graph

        command = Command(resume="continue")
        refreshed = await apply_bound_skill_catalog_for_resume(agent, command, thread_id="t-empty-msgs")
        assert refreshed is command

    @pytest.mark.asyncio
    async def test_resume_no_op_when_checkpoint_values_empty(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from langgraph.types import Command

        from myrm_agent_harness.agent._internals.agent_runtime import (
            apply_bound_skill_catalog_for_resume,
        )
        from myrm_agent_harness.agent.skill_agent import SkillAgent

        agent = SkillAgent(llm=AsyncMock(), skill_backend=AsyncMock())
        state_snapshot = MagicMock()
        state_snapshot.values = {}
        mock_graph = AsyncMock()
        mock_graph.aget_state = AsyncMock(return_value=state_snapshot)
        agent._agent = mock_graph

        command = Command(resume="continue")
        refreshed = await apply_bound_skill_catalog_for_resume(agent, command, thread_id="t-empty-values")
        assert refreshed is command

    @pytest.mark.asyncio
    async def test_first_human_content_returns_none_without_human_message(self) -> None:
        from langchain_core.messages import AIMessage

        from myrm_agent_harness.agent._internals.agent_runtime import (
            _first_human_content,
        )

        assert _first_human_content([AIMessage(content="assistant only")]) is None

    def test_run_agent_loop_wires_resume_catalog_helper(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "src/myrm_agent_harness/agent/_internals/agent_runtime.py"
        ).read_text(encoding="utf-8")
        assert "await apply_bound_skill_catalog_for_resume(" in source


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
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "src/myrm_agent_harness/agent/_internals/agent_runtime.py"
        ).read_text(encoding="utf-8")
        assert 'parse_litellm_model(llm_model or "")' in source
        assert 'getattr(agent_state.llm, "model_name", None)' in source
        assert "agent_state.config.llm" not in source


class TestRunAgentLoopOuterErrorFaultSide:
    """Regression: the outer-loop error_event must carry deterministic fault
    side + recovery actions so the GUI's trace timeline shows who owns the
    failure even when the executor loop itself raises (measurement decay guard
    — this branch previously dropped fault_side/recovery_actions)."""

    def test_outer_error_event_attributes_fault_side(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "src/myrm_agent_harness/agent/_internals/agent_runtime.py"
        ).read_text(encoding="utf-8")
        # fault_side must be computed via the pure-rules classifier, not guessed.
        assert 'classify_fault_side(error_kind=error_kind.value)' in source
        # recovery_actions must be generated when a diagnostic payload exists.
        assert "LLMErrorDiagnostic.get_recovery_actions" in source
        # The outer-loop error_event must be persisted to the event journal
        # (transport-only fields stripped) so trace reconstruction sees fatal
        # errors raised outside the executor.
        assert 'event_logger.log(AgentEventType.ERROR.value, persisted)' in source
        assert 'persisted.pop("type", None)' in source
        assert 'persisted.pop("messageId", None)' in source
