"""Tests for workspace rules injection middleware."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
        from langchain_core.messages import SystemMessage

        messages = [
            SystemMessage(content="System prompt"),
            SystemMessage(content='<workspace_context source="project_rules">rules</workspace_context>'),
        ]
        assert _has_workspace_context(messages) is True

    def test_returns_false_when_no_marker(self) -> None:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content="System prompt"),
            HumanMessage(content="Hello"),
        ]
        assert _has_workspace_context(messages) is False

    def test_empty_messages(self) -> None:
        assert _has_workspace_context([]) is False


class TestFindInsertIdx:
    def test_inserts_after_system_messages(self) -> None:
        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content="System"),
            SystemMessage(content="User instructions"),
            HumanMessage(content="Hello"),
        ]
        assert _find_workspace_insert_idx(messages) == 2

    def test_inserts_at_start_when_no_system(self) -> None:
        from langchain_core.messages import HumanMessage

        messages = [HumanMessage(content="Hello")]
        assert _find_workspace_insert_idx(messages) == 0

    def test_empty_messages(self) -> None:
        assert _find_workspace_insert_idx([]) == 0


class TestFormatRulesContent:
    def test_formats_single_rule(self) -> None:
        rules = [RuleFile(path="/project/AGENTS.md", content="# Rules", source="AGENTS.md")]
        result = _format_rules_content(rules)
        assert WORKSPACE_CONTEXT_MARKER in result
        assert "AGENTS.md" in result
        assert "# Rules" in result
        assert "</workspace_context>" in result

    def test_formats_multiple_rules(self) -> None:
        rules = [
            RuleFile(path="/project/AGENTS.md", content="# Agent Rules", source="AGENTS.md"),
            RuleFile(path="/project/.cursor/rules/style.mdc", content="Style config", source=".cursor/rules"),
        ]
        result = _format_rules_content(rules)
        assert "Agent Rules" in result
        assert "Style config" in result


class TestWorkspaceRulesMiddleware:
    @pytest.fixture()
    def middleware(self) -> WorkspaceRulesMiddleware:
        return WorkspaceRulesMiddleware()

    @pytest.fixture()
    def workspace_with_rules(self, tmp_path: Path) -> Path:
        (tmp_path / ".git").mkdir()
        (tmp_path / "AGENTS.md").write_text("# Follow project conventions")
        return tmp_path

    @pytest.mark.asyncio()
    async def test_injects_rules_on_first_call(
        self, middleware: WorkspaceRulesMiddleware, workspace_with_rules: Path
    ) -> None:
        from langchain_core.messages import HumanMessage, SystemMessage

        captured_request: list[object] = []

        async def capture_handler(req: object) -> MagicMock:
            captured_request.append(req)
            return MagicMock()

        request = MagicMock()
        request.messages = [
            SystemMessage(content="System prompt"),
            HumanMessage(content="Hello"),
        ]
        request.state = {"messages": []}
        request.runtime = MagicMock()
        request.runtime.context = {"workspace_path": str(workspace_with_rules)}

        overridden_messages: list[object] = []

        def override_side_effect(**kwargs: object) -> MagicMock:
            nonlocal overridden_messages
            msgs = kwargs.get("messages", request.messages)
            if isinstance(msgs, list):
                overridden_messages = msgs
            new_req = MagicMock()
            new_req.messages = msgs
            new_req.state = request.state
            new_req.runtime = request.runtime
            return new_req

        request.override = MagicMock(side_effect=override_side_effect)

        await middleware.awrap_model_call(request, capture_handler)

        assert len(captured_request) == 1
        passed_request = captured_request[0]
        injected_messages = passed_request.messages
        has_workspace = any(
            isinstance(m, SystemMessage) and WORKSPACE_CONTEXT_MARKER in (m.content or "")
            for m in injected_messages
        )
        assert has_workspace

    @pytest.mark.asyncio()
    async def test_skips_when_already_injected(
        self, middleware: WorkspaceRulesMiddleware, workspace_with_rules: Path
    ) -> None:
        from langchain_core.messages import HumanMessage, SystemMessage

        handler = AsyncMock(return_value=MagicMock())
        request = MagicMock()
        request.messages = [
            SystemMessage(content="System prompt"),
            SystemMessage(content=f'{WORKSPACE_CONTEXT_MARKER} source="test">rules</workspace_context>'),
            HumanMessage(content="Hello"),
        ]
        request.state = {"messages": []}

        await middleware.awrap_model_call(request, handler)

        handler.assert_called_once_with(request)

    @pytest.mark.asyncio()
    async def test_skips_when_no_workspace_root(
        self, middleware: WorkspaceRulesMiddleware
    ) -> None:
        from langchain_core.messages import HumanMessage, SystemMessage

        handler = AsyncMock(return_value=MagicMock())
        request = MagicMock()
        request.messages = [
            SystemMessage(content="System prompt"),
            HumanMessage(content="Hello"),
        ]
        request.state = {"messages": []}
        request.runtime = None

        with patch(
            "myrm_agent_harness.agent.workspace_rules.middleware.WorkspaceRulesMiddleware._resolve_workspace_root",
            return_value="",
        ):
            await middleware.awrap_model_call(request, handler)

        handler.assert_called_once_with(request)

    @pytest.mark.asyncio()
    async def test_skips_when_no_rules_found(
        self, middleware: WorkspaceRulesMiddleware, tmp_path: Path
    ) -> None:
        from langchain_core.messages import HumanMessage, SystemMessage

        (tmp_path / ".git").mkdir()

        handler = AsyncMock(return_value=MagicMock())
        request = MagicMock()
        request.messages = [
            SystemMessage(content="System prompt"),
            HumanMessage(content="Hello"),
        ]
        request.state = {"messages": []}
        request.runtime = MagicMock()
        request.runtime.context = {"workspace_path": str(tmp_path)}

        await middleware.awrap_model_call(request, handler)

        handler.assert_called_once_with(request)
