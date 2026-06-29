"""Tests for workspace rules injection middleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.workspace_rules.middleware import (
    WORKSPACE_CONTEXT_MARKER,
    WorkspaceRulesMiddleware,
    _find_workspace_insert_idx,
    _format_rules_content,
    _has_workspace_context,
)
from myrm_agent_harness.agent.workspace_rules.scanner import RuleFile


class TestHasWorkspaceContext:
    def test_detects_marker_in_system_message(self) -> None:
        messages = [
            SystemMessage(content='<workspace_context source="project_rules">\nrules\n</workspace_context>'),
        ]
        assert _has_workspace_context(messages) is True

    def test_no_marker(self) -> None:
        messages = [
            SystemMessage(content="System prompt"),
            HumanMessage(content="Hello"),
        ]
        assert _has_workspace_context(messages) is False

    def test_empty_messages(self) -> None:
        assert _has_workspace_context([]) is False

    def test_ignores_marker_in_non_system_messages(self) -> None:
        messages = [
            HumanMessage(content=f"User said {WORKSPACE_CONTEXT_MARKER}"),
        ]
        assert _has_workspace_context(messages) is False

    def test_only_scans_first_8_messages(self) -> None:
        messages = [HumanMessage(content="msg")] * 8
        messages.append(SystemMessage(content=f"{WORKSPACE_CONTEXT_MARKER} rules"))
        assert _has_workspace_context(messages) is False


class TestFindWorkspaceInsertIdx:
    def test_after_system_messages(self) -> None:
        messages = [
            SystemMessage(content="System prompt"),
            SystemMessage(content="User instructions"),
            HumanMessage(content="Hello"),
        ]
        assert _find_workspace_insert_idx(messages) == 2

    def test_no_system_messages(self) -> None:
        messages = [HumanMessage(content="Hello")]
        assert _find_workspace_insert_idx(messages) == 0

    def test_all_system_messages(self) -> None:
        messages = [
            SystemMessage(content="A"),
            SystemMessage(content="B"),
            SystemMessage(content="C"),
        ]
        assert _find_workspace_insert_idx(messages) == 3

    def test_empty_messages(self) -> None:
        assert _find_workspace_insert_idx([]) == 0


class TestFormatRulesContent:
    def test_formats_single_rule(self) -> None:
        rules = [RuleFile(path="/project/AGENTS.md", content="# Rules\nDo X.", source="AGENTS.md")]
        result = _format_rules_content(rules)
        assert "<workspace_context" in result
        assert "AGENTS.md" in result
        assert "# Rules" in result
        assert "</workspace_context>" in result

    def test_formats_multiple_rules(self) -> None:
        rules = [
            RuleFile(path="/project/.myrm/rules/a.md", content="Rule A", source=".myrm/rules"),
            RuleFile(path="/project/SOUL.md", content="Rule B", source="SOUL.md"),
        ]
        result = _format_rules_content(rules)
        assert "a.md" in result
        assert "SOUL.md" in result
        assert "Rule A" in result
        assert "Rule B" in result

    def test_skips_non_rulefile_objects(self) -> None:
        rules = [MagicMock(), RuleFile(path="/project/X.md", content="Valid", source="X.md")]
        result = _format_rules_content(rules)
        assert "Valid" in result

    def test_empty_rules(self) -> None:
        result = _format_rules_content([])
        assert "<workspace_context" in result
        assert "</workspace_context>" in result


class TestWorkspaceRulesMiddleware:
    def test_sync_wrap_raises(self) -> None:
        mw = WorkspaceRulesMiddleware()
        with pytest.raises(NotImplementedError):
            mw.wrap_model_call(MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_skips_when_already_injected(self) -> None:
        mw = WorkspaceRulesMiddleware()
        handler = AsyncMock()

        request = MagicMock()
        request.messages = [
            SystemMessage(content=f'{WORKSPACE_CONTEXT_MARKER} source="project_rules">\nrules\n</workspace_context>'),
            HumanMessage(content="Hello"),
        ]
        request.state = {"messages": []}

        await mw.awrap_model_call(request, handler)
        handler.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_skips_when_no_workspace_root(self) -> None:
        mw = WorkspaceRulesMiddleware()
        handler = AsyncMock()

        request = MagicMock()
        request.messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Hello"),
        ]
        request.state = {"messages": []}
        request.runtime = MagicMock()
        request.runtime.context = {}

        with patch(
            "myrm_agent_harness.agent.workspace_rules.middleware.WorkspaceRulesMiddleware._resolve_workspace_root",
            return_value="",
        ):
            await mw.awrap_model_call(request, handler)

        handler.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_skips_when_no_rules_found(self, tmp_path) -> None:
        mw = WorkspaceRulesMiddleware()
        handler = AsyncMock()

        (tmp_path / ".git").mkdir()

        request = MagicMock()
        request.messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Hello"),
        ]
        request.state = {"messages": []}
        request.override = MagicMock(return_value=request)

        with patch(
            "myrm_agent_harness.agent.workspace_rules.middleware.WorkspaceRulesMiddleware._resolve_workspace_root",
            return_value=str(tmp_path),
        ):
            await mw.awrap_model_call(request, handler)

        handler.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_injects_rules_on_first_call(self, tmp_path) -> None:
        mw = WorkspaceRulesMiddleware()
        handler = AsyncMock()

        (tmp_path / ".git").mkdir()
        (tmp_path / "AGENTS.md").write_text("# Project Rules\nUse type hints.")

        request = MagicMock()
        request.messages = [
            SystemMessage(content="System prompt"),
            HumanMessage(content="Hello"),
        ]
        request.state = {"messages": []}
        request.override = MagicMock(return_value=request)

        with patch(
            "myrm_agent_harness.agent.workspace_rules.middleware.WorkspaceRulesMiddleware._resolve_workspace_root",
            return_value=str(tmp_path),
        ):
            await mw.awrap_model_call(request, handler)

        request.override.assert_called_once()
        injected = request.override.call_args[1]["messages"]
        workspace_msgs = [
            m for m in injected if isinstance(m, SystemMessage) and WORKSPACE_CONTEXT_MARKER in m.content
        ]
        assert len(workspace_msgs) == 1
        assert "Project Rules" in workspace_msgs[0].content

    @pytest.mark.asyncio
    async def test_idempotent_on_state_marker(self) -> None:
        mw = WorkspaceRulesMiddleware()
        handler = AsyncMock()

        request = MagicMock()
        request.messages = [
            SystemMessage(content="System"),
            HumanMessage(content="Hello"),
        ]
        request.state = {
            "messages": [
                SystemMessage(content=f'{WORKSPACE_CONTEXT_MARKER} source="project_rules">rules</workspace_context>'),
            ]
        }

        await mw.awrap_model_call(request, handler)
        handler.assert_called_once_with(request)


class TestResolveWorkspaceRoot:
    def test_from_runtime_context(self) -> None:
        request = MagicMock()
        request.runtime.context = {"workspace_path": "/project/root"}
        assert WorkspaceRulesMiddleware._resolve_workspace_root(request) == "/project/root"

    def test_falls_back_to_session_context(self) -> None:
        request = MagicMock()
        request.runtime.context = {}
        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_workspace_root",
            return_value="/fallback/root",
        ):
            result = WorkspaceRulesMiddleware._resolve_workspace_root(request)
        assert result == "/fallback/root"

    def test_none_runtime(self) -> None:
        request = MagicMock()
        request.runtime = None
        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_workspace_root",
            return_value="",
        ):
            result = WorkspaceRulesMiddleware._resolve_workspace_root(request)
        assert result == ""

    def test_non_dict_context(self) -> None:
        request = MagicMock()
        request.runtime.context = "not_a_dict"
        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_workspace_root",
            return_value="/session/root",
        ):
            result = WorkspaceRulesMiddleware._resolve_workspace_root(request)
        assert result == "/session/root"

    def test_empty_workspace_path(self) -> None:
        request = MagicMock()
        request.runtime.context = {"workspace_path": ""}
        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_workspace_root",
            return_value="/session/root",
        ):
            result = WorkspaceRulesMiddleware._resolve_workspace_root(request)
        assert result == "/session/root"
