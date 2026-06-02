"""Tests for BudgetBoundaryMiddleware."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.utils.token_economics.budget_boundary_middleware import (
    _BUDGET_LOW_HINT,
    BudgetBoundaryMiddleware,
)
from myrm_agent_harness.utils.token_economics.budget_guard import BudgetStatus


def _make_tracker(status: str = "ok") -> MagicMock:
    tracker = MagicMock()
    tracker.budget_checker = MagicMock()
    tracker.last_budget_status = status
    return tracker


class TestBeforeModel:
    def test_no_op_when_disabled(self) -> None:
        mw = BudgetBoundaryMiddleware(enabled=False)
        result = mw.before_model({"messages": []}, None)
        assert result is None

    def test_no_op_when_no_tracker(self) -> None:
        mw = BudgetBoundaryMiddleware()
        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=None,
        ):
            result = mw.before_model({"messages": []}, None)
            assert result is None

    def test_no_op_when_budget_ok(self) -> None:
        mw = BudgetBoundaryMiddleware()
        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=_make_tracker("ok"),
        ):
            result = mw.before_model({"messages": [HumanMessage(content="hi")]}, None)
            assert result is None

    def test_injects_warning_hint(self) -> None:
        """Hint is injected as HumanMessage (preserves SystemMessage hash for prompt cache)."""
        mw = BudgetBoundaryMiddleware()
        messages = [HumanMessage(content="hi")]
        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=_make_tracker(BudgetStatus.WARNING),
        ):
            result = mw.before_model({"messages": messages}, None)
            assert result is not None
            assert len(result["messages"]) == 2
            last = result["messages"][-1]
            assert isinstance(last, HumanMessage)
            assert "Budget is running low" in last.content

    def test_warning_hint_idempotent(self) -> None:
        """Re-injection is skipped when a HumanMessage hint is already present."""
        mw = BudgetBoundaryMiddleware()
        existing_hint = HumanMessage(content=f"[SYSTEM INSTRUCTION]\n{_BUDGET_LOW_HINT}")
        messages = [HumanMessage(content="hi"), existing_hint]
        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=_make_tracker(BudgetStatus.WARNING),
        ):
            result = mw.before_model({"messages": messages}, None)
            assert result is None

    def test_injects_finalization_hint_once(self) -> None:
        mw = BudgetBoundaryMiddleware()
        messages = [HumanMessage(content="hi")]
        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=_make_tracker(BudgetStatus.FINALIZATION),
        ):
            result = mw.before_model({"messages": messages}, None)
            assert result is not None
            assert "Budget limit reached" in result["messages"][-1].content

            result2 = mw.before_model({"messages": messages}, None)
            assert result2 is None


class TestAfterModel:
    def test_no_op_when_ok(self) -> None:
        mw = BudgetBoundaryMiddleware()
        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=_make_tracker("ok"),
        ):
            result = mw.after_model({"messages": [AIMessage(content="answer")]}, None)
            assert result is None

    def test_strips_tool_calls_on_finalization(self) -> None:
        mw = BudgetBoundaryMiddleware()
        ai_msg = AIMessage(content="thinking")
        ai_msg.tool_calls = [{"name": "search", "args": {}, "id": "tc1"}]  # type: ignore[assignment]

        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=_make_tracker(BudgetStatus.FINALIZATION),
        ):
            result = mw.after_model({"messages": [ai_msg]}, None)
            assert result is not None
            last = result["messages"][-1]
            assert isinstance(last, AIMessage)
            assert not last.tool_calls

    def test_no_strip_when_no_tool_calls(self) -> None:
        mw = BudgetBoundaryMiddleware()
        ai_msg = AIMessage(content="done")

        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=_make_tracker(BudgetStatus.EXCEEDED),
        ):
            result = mw.after_model({"messages": [ai_msg]}, None)
            assert result is None

    def test_no_op_when_disabled(self) -> None:
        mw = BudgetBoundaryMiddleware(enabled=False)
        ai_msg = AIMessage(content="x")
        ai_msg.tool_calls = [{"name": "t", "args": {}, "id": "tc"}]  # type: ignore[assignment]
        result = mw.after_model({"messages": [ai_msg]}, None)
        assert result is None

    def test_no_op_when_no_tracker_after_model(self) -> None:
        mw = BudgetBoundaryMiddleware()
        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=None,
        ):
            result = mw.after_model({"messages": [AIMessage(content="x")]}, None)
            assert result is None

    def test_no_op_when_empty_messages_after_model(self) -> None:
        mw = BudgetBoundaryMiddleware()
        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=_make_tracker(BudgetStatus.EXCEEDED),
        ):
            result = mw.after_model({"messages": []}, None)
            assert result is None

    def test_no_op_when_last_msg_not_ai(self) -> None:
        mw = BudgetBoundaryMiddleware()
        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=_make_tracker(BudgetStatus.EXCEEDED),
        ):
            result = mw.after_model({"messages": [HumanMessage(content="hi")]}, None)
            assert result is None
