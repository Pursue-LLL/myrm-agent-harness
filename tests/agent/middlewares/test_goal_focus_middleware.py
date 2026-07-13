"""Tests for goal_focus_middleware — active goal injection and cache safety."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.infra.cache_break_detector import (
    _compute_system_prompt_hash,
)
from myrm_agent_harness.agent.goals.types import Goal, GoalBudget, GoalStatus
from myrm_agent_harness.agent.middlewares._session_context import set_goal_provider
from myrm_agent_harness.agent.middlewares.goal_focus_middleware import (
    _build_goal_focus_line,
    _has_goal_continuation_prompt,
    goal_focus_middleware,
)


@pytest.fixture
def mock_goal_provider():
    provider = AsyncMock()
    return provider


def _make_request(messages: list, context: dict[str, str] | None = None) -> ModelRequest:
    runtime = MagicMock()
    runtime.context = context or {}
    return ModelRequest(model=AsyncMock(), messages=messages, runtime=runtime)


class TestGoalFocusHelpers:
    def test_build_goal_focus_line_with_budget(self) -> None:
        goal = Goal(
            goal_id="g-1",
            session_id="s1",
            objective="Ship the feature",
            status=GoalStatus.ACTIVE,
            budget=GoalBudget(max_tokens=1000, max_turns=10),
            tokens_used=200,
            turns_used=2,
        )
        line = _build_goal_focus_line(goal)
        assert "Active goal: Ship the feature" in line
        assert "tokens 200/1000" in line
        assert "turns 2/10" in line
        assert "update_goal_status_tool" in line

    def test_has_goal_continuation_prompt_detects_prefix(self) -> None:
        messages = [
            HumanMessage(content="[Continuing toward your standing goal]\nObjective: test"),
        ]
        assert _has_goal_continuation_prompt(messages) is True

    def test_has_goal_continuation_prompt_detects_wrap_up(self) -> None:
        messages = [HumanMessage(content="[Budget reached — wrap-up turn]\nFinish now")]
        assert _has_goal_continuation_prompt(messages) is True


class TestGoalFocusMiddleware:
    @pytest.mark.asyncio
    async def test_injects_active_goal_into_last_human_message(
        self, mock_goal_provider
    ) -> None:
        goal = Goal(
            goal_id="g-1",
            session_id="chat-1",
            objective="Refactor auth module",
            status=GoalStatus.ACTIVE,
            tokens_used=0,
        )
        mock_goal_provider.get_active_goal.return_value = goal
        set_goal_provider(mock_goal_provider)

        middleware = goal_focus_middleware()
        original_msg = HumanMessage(content="please continue", id="hm-1")
        request = _make_request(
            [SystemMessage(content="system"), original_msg],
            {"chat_id": "chat-1"},
        )

        mock_handler = AsyncMock(return_value=AsyncMock())
        await middleware.awrap_model_call(request, mock_handler)

        assert original_msg.content == "please continue"
        override_messages = mock_handler.call_args[0][0].messages
        injected = override_messages[1]
        assert "Active goal: Refactor auth module" in str(injected.content)
        assert injected.id == "hm-1"

    @pytest.mark.asyncio
    async def test_skips_when_no_goal_provider(self) -> None:
        set_goal_provider(None)
        middleware = goal_focus_middleware()
        request = _make_request([HumanMessage(content="hello")], {"chat_id": "chat-1"})

        mock_handler = AsyncMock(return_value=AsyncMock())
        await middleware.awrap_model_call(request, mock_handler)
        mock_handler.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_skips_on_continuation_turn(self, mock_goal_provider) -> None:
        set_goal_provider(mock_goal_provider)
        middleware = goal_focus_middleware()
        request = _make_request(
            [
                HumanMessage(
                    content="[Continuing toward your standing goal]\nObjective: ship it"
                ),
            ],
            {"chat_id": "chat-1"},
        )

        mock_handler = AsyncMock(return_value=AsyncMock())
        await middleware.awrap_model_call(request, mock_handler)
        mock_handler.assert_called_once_with(request)
        mock_goal_provider.get_active_goal.assert_not_called()

    @pytest.mark.asyncio
    async def test_system_prompt_hash_unchanged_after_injection(
        self, mock_goal_provider
    ) -> None:
        goal = Goal(
            goal_id="g-1",
            session_id="chat-1",
            objective="Cache-safe injection",
            status=GoalStatus.ACTIVE,
        )
        mock_goal_provider.get_active_goal.return_value = goal
        set_goal_provider(mock_goal_provider)

        middleware = goal_focus_middleware()
        base_messages = [
            SystemMessage(content="frozen prompt"),
            HumanMessage(content="user turn"),
        ]
        hash_before = _compute_system_prompt_hash(base_messages)

        request = _make_request(list(base_messages), {"session_id": "chat-1"})

        mock_handler = AsyncMock(return_value=AsyncMock())
        await middleware.awrap_model_call(request, mock_handler)

        override_messages = mock_handler.call_args[0][0].messages
        hash_after = _compute_system_prompt_hash(override_messages)
        assert hash_before == hash_after
