"""Unit tests for LayeredLoopTerminationAndDebtInboxSuite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    DebtInboxManager,
    DebtKind,
    LayeredLoopTerminationAndDebtInboxSuite,
    LoopHierarchyTier,
    LoopTerminationReason,
)


def test_pair_guaranteed_lifecycle_events_and_unclosed_tracking() -> None:
    """Test start-end pairing across loop tiers and strict unclosed start detection."""
    suite = LayeredLoopTerminationAndDebtInboxSuite()

    # 1. Start a turn and step
    evt_turn_start = suite.start_loop(tier=LoopHierarchyTier.TURN, turn_id=1)
    evt_step_start = suite.start_loop(tier=LoopHierarchyTier.STEP, turn_id=1, step_id=1)

    assert evt_turn_start.is_start is True
    assert evt_step_start.is_start is True
    assert suite.has_unclosed_starts() is True

    # 2. Close step
    evt_step_end = suite.end_loop(
        tier=LoopHierarchyTier.STEP,
        turn_id=1,
        step_id=1,
        reason=LoopTerminationReason.NATURAL_COMPLETION,
    )
    assert evt_step_end.is_start is False
    assert suite.has_unclosed_starts() is True  # Turn still open

    # 3. Close turn even on simulated abort/error
    evt_turn_end = suite.end_loop(
        tier=LoopHierarchyTier.TURN,
        turn_id=1,
        reason=LoopTerminationReason.ERROR_ABORTED,
        error_message="Simulation early exit",
    )
    assert evt_turn_end.reason == LoopTerminationReason.ERROR_ABORTED
    assert suite.has_unclosed_starts() is False

    events = suite.get_events()
    assert len(events) == 4


def test_dual_condition_termination_model_and_message_debts() -> None:
    """Test termination blocking by model debt (tool done, awaiting model) and message debt (inbox queue)."""
    suite = LayeredLoopTerminationAndDebtInboxSuite()

    # Initially debt-free
    dec_init = suite.evaluate_turn_termination(turn_id=1)
    assert dec_init.can_terminate is True
    assert dec_init.model_debt_count == 0
    assert dec_init.message_debt_count == 0

    # 1. Tool execution completes -> model owes a response
    suite.inbox.record_model_debt_incurred()
    dec_model_debt = suite.evaluate_turn_termination(turn_id=1)
    assert dec_model_debt.can_terminate is False
    assert dec_model_debt.model_debt_count == 1
    assert "Model debt unpaid" in str(dec_model_debt.blocking_reason)

    # Model finishes turn -> satisfies debt
    suite.inbox.record_model_debt_satisfied()
    assert suite.evaluate_turn_termination(turn_id=1).can_terminate is True

    # 2. Steering or plugin enqueues a message debt into next-step inbox
    suite.inbox.enqueue_message_debt(
        kind=DebtKind.STEERING_MESSAGE_OWED,
        source="plugin-code-linter",
        payload_text="Found 2 style violations, please refactor.",
    )
    dec_msg_debt = suite.evaluate_turn_termination(turn_id=1)
    assert dec_msg_debt.can_terminate is False
    assert dec_msg_debt.message_debt_count == 1
    assert "Message debt pending" in str(dec_msg_debt.blocking_reason)

    # Consume the item from inbox
    consumed_item = suite.inbox.dequeue_next_debt()
    assert consumed_item is not None
    assert consumed_item.source == "plugin-code-linter"
    assert consumed_item.consumed is True

    # After consumption, loop is free to terminate
    dec_cleared = suite.evaluate_turn_termination(turn_id=1)
    assert dec_cleared.can_terminate is True
    assert dec_cleared.message_debt_count == 0


def test_stop_hook_data_driven_recheck_revival() -> None:
    """Test stop hooks injecting debt items into inbox, reviving execution via data-driven recheck."""
    suite = LayeredLoopTerminationAndDebtInboxSuite()

    # Define a stop hook that detects missing documentation and forces continuation
    def doc_audit_stop_hook(inbox: DebtInboxManager) -> None:
        inbox.enqueue_message_debt(
            kind=DebtKind.CORRECTION_PROMPT_OWED,
            source="audit-hook-stop",
            payload_text="Post-stop sanity: ensure API docstrings exist before finalizing.",
        )

    suite.register_stop_hook(doc_audit_stop_hook)

    # Initially ready to terminate
    assert suite.evaluate_turn_termination(turn_id=2).can_terminate is True

    # Triggering stop hooks causes data-driven recheck
    decision = suite.trigger_stop_hooks_and_recheck(turn_id=2)
    assert decision.can_terminate is False
    assert decision.message_debt_count == 1
    assert len(decision.pending_debts) == 1
    assert decision.pending_debts[0].source == "audit-hook-stop"
