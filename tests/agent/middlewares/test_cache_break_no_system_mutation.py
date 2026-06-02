"""Regression tests: dynamic middleware injections must NOT mutate SystemMessages.

These tests verify that:
1. The system prompt hash is unaffected by HumanMessage injections (cache stability)
2. Middleware does NOT mutate message objects in-place (state isolation)
3. Budget boundary middleware idempotency works correctly
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.infra.cache_break_detector import (
    _compute_system_prompt_hash,
)


class TestSystemPromptHashStability:
    """Verify that _compute_system_prompt_hash only considers SystemMessages."""

    def test_system_hash_ignores_human_messages(self) -> None:
        base = [SystemMessage(content="core prompt"), HumanMessage(content="hello")]
        hash_before = _compute_system_prompt_hash(base)

        with_extra = [
            SystemMessage(content="core prompt"),
            HumanMessage(content="hello"),
            HumanMessage(content="[SYSTEM INSTRUCTION]\ndynamic content"),
        ]
        hash_after = _compute_system_prompt_hash(with_extra)

        assert hash_before == hash_after, (
            "Adding HumanMessage should not change system prompt hash"
        )

    def test_system_hash_changes_with_system_message(self) -> None:
        base = [SystemMessage(content="core prompt"), HumanMessage(content="hello")]
        hash_before = _compute_system_prompt_hash(base)

        with_system = [
            SystemMessage(content="core prompt"),
            HumanMessage(content="hello"),
            SystemMessage(content="dynamic injection"),
        ]
        hash_after = _compute_system_prompt_hash(with_system)

        assert hash_before != hash_after, (
            "Adding SystemMessage MUST change system prompt hash (this is the bug we fixed)"
        )

    def test_empty_messages(self) -> None:
        hash_val = _compute_system_prompt_hash([])
        assert isinstance(hash_val, str) and len(hash_val) == 64

    def test_multiple_human_messages_no_hash_change(self) -> None:
        """Simulate multiple middleware all injecting HumanMessage — hash stays stable."""
        base = [SystemMessage(content="frozen prompt")]
        hash_before = _compute_system_prompt_hash(base)

        with_injections = [
            SystemMessage(content="frozen prompt"),
            HumanMessage(content="[SYSTEM INSTRUCTION]\nblueprint..."),
            HumanMessage(content="[SYSTEM_ENFORCED]\nnetwork blocked"),
            HumanMessage(content="[SYSTEM INSTRUCTION]\nbudget low"),
            HumanMessage(content="[SYSTEM INSTRUCTION]\ncitation rules"),
        ]
        hash_after = _compute_system_prompt_hash(with_injections)

        assert hash_before == hash_after


class TestPlannerMiddlewareNoMutation:
    """Verify planner middleware does NOT mutate original messages in-place."""

    @pytest.mark.asyncio
    async def test_planner_does_not_mutate_original_message(self) -> None:
        from myrm_agent_harness.agent.middlewares.planner_middleware import (
            planner_middleware,
        )
        from myrm_agent_harness.agent.sub_agents.planner.schemas import (
            Plan,
            PlanStep,
        )

        plan = Plan(
            goal="test goal",
            reasoning="test reasoning",
            steps=[
                PlanStep(
                    step_id="s1",
                    description="step 1",
                    expected_output="output 1",
                )
            ],
        )

        async def mock_get_plan(_workspace: str | None) -> Plan:
            return plan

        middleware = planner_middleware(mock_get_plan)

        original_content = "user question"
        original_msg = HumanMessage(content=original_content, id="test-id")

        from langchain.agents.middleware import ModelRequest

        mock_handler = AsyncMock()
        mock_handler.return_value = AsyncMock()

        request = ModelRequest(
            model=AsyncMock(),
            messages=[SystemMessage(content="system"), original_msg],
        )

        await middleware.awrap_model_call(request, mock_handler)

        assert original_msg.content == original_content, (
            "planner middleware must NOT mutate the original HumanMessage in-place"
        )

        handler_call_args = mock_handler.call_args[0][0]
        override_messages = handler_call_args.messages
        injected_msg = override_messages[1]
        assert "[SYSTEM INSTRUCTION]" in str(injected_msg.content)
        assert injected_msg.id == "test-id"


class TestSecurityGuardrailCircuitBreaker:
    """Verify circuit breaker uses request.override and does not persist."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_injects_human_message(self) -> None:
        from myrm_agent_harness.agent.middlewares.security_guardrail_middleware import (
            SecurityGuardrailMiddleware,
        )

        mw = SecurityGuardrailMiddleware()

        from langchain.agents.middleware import ModelRequest

        mock_handler = AsyncMock()
        mock_handler.return_value = AsyncMock()

        original_messages = [
            SystemMessage(content="system"),
            HumanMessage(content="hello"),
        ]

        request = ModelRequest(
            model=AsyncMock(),
            messages=list(original_messages),
        )

        with patch(
            "myrm_agent_harness.agent.middlewares.security_guardrail_middleware.get_terminal_errors"
        ) as mock_errors:
            mock_registry = MagicMock()
            mock_registry.get_all.return_value = {"network_blocked"}
            mock_errors.return_value = mock_registry

            await mw.awrap_model_call(request, mock_handler)

        handler_call_args = mock_handler.call_args[0][0]
        override_messages = handler_call_args.messages

        assert len(override_messages) == 3
        injected = override_messages[-1]
        assert isinstance(injected, HumanMessage)
        assert "[SYSTEM_ENFORCED]" in str(injected.content)
        for msg in override_messages:
            if isinstance(msg, SystemMessage):
                assert "network" not in msg.content.lower()

    @pytest.mark.asyncio
    async def test_circuit_breaker_noop_when_no_errors(self) -> None:
        from myrm_agent_harness.agent.middlewares.security_guardrail_middleware import (
            SecurityGuardrailMiddleware,
        )

        mw = SecurityGuardrailMiddleware()

        from langchain.agents.middleware import ModelRequest

        mock_handler = AsyncMock()
        mock_handler.return_value = AsyncMock()

        request = ModelRequest(
            model=AsyncMock(),
            messages=[SystemMessage(content="system"), HumanMessage(content="hello")],
        )

        with patch(
            "myrm_agent_harness.agent.middlewares.security_guardrail_middleware.get_terminal_errors"
        ) as mock_errors:
            mock_registry = MagicMock()
            mock_registry.get_all.return_value = set()
            mock_errors.return_value = mock_registry

            await mw.awrap_model_call(request, mock_handler)

        called_request = mock_handler.call_args[0][0]
        assert called_request is request


class TestBudgetBoundaryIdempotency:
    """Verify budget hints use HumanMessage and are idempotent."""

    def test_has_budget_hint_detects_existing(self) -> None:
        from myrm_agent_harness.utils.token_economics.budget_boundary_middleware import (
            BudgetBoundaryMiddleware,
        )

        messages: list[Any] = [
            SystemMessage(content="system"),
            HumanMessage(content="user msg"),
            HumanMessage(content="[SYSTEM INSTRUCTION]\n Budget is running low. Prioritize..."),
        ]

        assert BudgetBoundaryMiddleware._has_budget_hint(messages) is True

    def test_has_budget_hint_no_false_positive(self) -> None:
        from myrm_agent_harness.utils.token_economics.budget_boundary_middleware import (
            BudgetBoundaryMiddleware,
        )

        messages: list[Any] = [
            SystemMessage(content="system"),
            HumanMessage(content="user question about budget"),
        ]

        assert BudgetBoundaryMiddleware._has_budget_hint(messages) is False


