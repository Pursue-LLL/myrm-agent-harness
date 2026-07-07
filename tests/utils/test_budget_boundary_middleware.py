"""Tests for BudgetBoundaryMiddleware."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.utils.token_economics.budget_boundary_middleware import (
    _HINT_PREFIX,
    _build_finalize_hint,
    _build_warning_hint,
    BudgetBoundaryMiddleware,
)
from myrm_agent_harness.utils.token_economics.budget_guard import BudgetStatus


def _make_tracker(status: str = "ok", remaining: float | None = 1.0) -> MagicMock:
    tracker = MagicMock()
    tracker.budget_checker = MagicMock()
    tracker.budget_checker.get_remaining_budget.return_value = remaining
    tracker.last_budget_status = status
    return tracker


class TestBuildHints:
    def test_warning_hint_with_remaining(self) -> None:
        hint = _build_warning_hint(0.80)
        assert "$0.80" in hint
        assert "Budget is running low" in hint

    def test_warning_hint_without_remaining(self) -> None:
        hint = _build_warning_hint(None)
        assert "$" not in hint
        assert "Budget is running low" in hint

    def test_finalize_hint_with_remaining(self) -> None:
        hint = _build_finalize_hint(0.12)
        assert "$0.12" in hint
        assert "Budget limit reached" in hint

    def test_finalize_hint_without_remaining(self) -> None:
        hint = _build_finalize_hint(None)
        assert "$" not in hint
        assert "Budget limit reached" in hint


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

    def test_injects_warning_hint_with_remaining(self) -> None:
        """Hint includes dynamic remaining budget and uses HumanMessage (preserves prompt cache)."""
        mw = BudgetBoundaryMiddleware()
        messages = [HumanMessage(content="hi")]
        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=_make_tracker(BudgetStatus.WARNING, remaining=0.80),
        ):
            result = mw.before_model({"messages": messages}, None)
            assert result is not None
            assert len(result["messages"]) == 2
            last = result["messages"][-1]
            assert isinstance(last, HumanMessage)
            assert "Budget is running low" in last.content
            assert "$0.80" in last.content
            assert _HINT_PREFIX in last.content

    def test_warning_hint_graceful_when_remaining_none(self) -> None:
        """Hint degrades gracefully when get_remaining_budget() returns None."""
        mw = BudgetBoundaryMiddleware()
        messages = [HumanMessage(content="hi")]
        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=_make_tracker(BudgetStatus.WARNING, remaining=None),
        ):
            result = mw.before_model({"messages": messages}, None)
            assert result is not None
            last = result["messages"][-1]
            assert "Budget is running low" in last.content
            assert "$" not in last.content

    def test_warning_hint_idempotent(self) -> None:
        """Re-injection is skipped when a budget hint is already present."""
        mw = BudgetBoundaryMiddleware()
        existing_hint = HumanMessage(
            content=f"[SYSTEM INSTRUCTION] {_HINT_PREFIX}\n{_build_warning_hint(0.80)}"
        )
        messages = [HumanMessage(content="hi"), existing_hint]
        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=_make_tracker(BudgetStatus.WARNING, remaining=0.50),
        ):
            result = mw.before_model({"messages": messages}, None)
            assert result is None

    def test_injects_finalization_hint_once(self) -> None:
        mw = BudgetBoundaryMiddleware()
        messages = [HumanMessage(content="hi")]
        with patch(
            "myrm_agent_harness.utils.token_economics.tracker.get_token_tracker",
            return_value=_make_tracker(BudgetStatus.FINALIZATION, remaining=0.12),
        ):
            result = mw.before_model({"messages": messages}, None)
            assert result is not None
            last_content = result["messages"][-1].content
            assert "Budget limit reached" in last_content
            assert "$0.12" in last_content

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
