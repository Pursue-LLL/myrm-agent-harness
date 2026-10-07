"""Unit tests for Graceful Turn Interrupt and Queued Message Draft Preserver."""

import pytest

from myrm_agent_harness.agent.context_management.interrupt_preserver import (
    GracefulTurnInterruptPreserver,
    InterruptReason,
    SalvagedDraft,
)


def test_zero_pruning_context_freeze_without_queue() -> None:
    """Verify that interruption freezes the context without pruning any messages or tool results."""
    preserver = GracefulTurnInterruptPreserver()
    session_id = "sess-001"
    turn_id = "turn-101"

    context_messages = [
        {"role": "system", "content": "You are a software engineer."},
        {"role": "user", "content": "Please inspect database migrations and execute schema changes."},
        {"role": "assistant", "content": "Calling inspect_schema..."},
        {"role": "tool", "content": "Schema inspection result: table users exists."},
    ]

    result = preserver.handle_interrupt(
        session_id=session_id,
        turn_id=turn_id,
        current_context_messages=context_messages,
        reason=InterruptReason.USER_STOP,
    )

    assert result.session_id == session_id
    assert result.turn_id == turn_id
    assert result.turn_state.zero_pruning_verified is True
    assert result.turn_state.total_messages_preserved == 4
    assert result.turn_state.frozen_tool_results_count == 1
    assert result.turn_state.reason == InterruptReason.USER_STOP
    assert result.has_unconsumed_messages is False
    assert len(result.salvaged_drafts) == 0
    assert result.recommended_action == "AWAIT_NEXT_USER_PROMPT"


def test_in_flight_queued_message_salvage_to_draft() -> None:
    """Verify in-flight queued messages are atomically salvaged to editable drafts on interrupt."""
    preserver = GracefulTurnInterruptPreserver()
    session_id = "sess-002"
    turn_id = "turn-201"

    # User types a correction while agent is executing a tool
    user_correction = "Wait, do not use BeautifulSoup, use Playwright to scrape rendered DOM!"
    enqueued = preserver.enqueue_message(
        session_id=session_id,
        content=user_correction,
    )
    assert enqueued.message_id is not None
    assert len(preserver.get_unconsumed_queue(session_id)) == 1

    context_messages = [
        {"role": "system", "content": "Web scraping agent."},
        {"role": "user", "content": "Scrape product catalog."},
        {"role": "assistant", "content": "Running requests.get..."},
    ]

    # User clicks STOP
    result = preserver.handle_interrupt(
        session_id=session_id,
        turn_id=turn_id,
        current_context_messages=context_messages,
        reason=InterruptReason.USER_STOP,
    )

    assert result.has_unconsumed_messages is True
    assert len(result.salvaged_drafts) == 1
    draft = result.salvaged_drafts[0]
    assert draft.content == user_correction
    assert draft.cursor_position == len(user_correction)
    assert "任务已中断" in draft.hint_text
    assert result.recommended_action == "RESTORE_DRAFT_AND_AWAIT_INPUT"

    # Queue must be cleared atomically to prevent ghost consumption
    assert len(preserver.get_unconsumed_queue(session_id)) == 0


def test_resume_turn_with_draft_and_modifications() -> None:
    """Verify drafting can be resumed directly or with user modifications."""
    preserver = GracefulTurnInterruptPreserver()
    session_id = "sess-003"

    draft = SalvagedDraft(
        draft_id="draft-001",
        session_id=session_id,
        queued_message_id="msg-001",
        content="Original queued text",
        salvaged_at=1000.0,
        cursor_position=20,
        hint_text="hint",
    )

    # Resume directly
    resumed_msg = preserver.resume_turn_with_draft(session_id, draft)
    assert resumed_msg["role"] == "user"
    assert resumed_msg["content"] == "Original queued text"

    # Resume with user edits
    resumed_edited = preserver.resume_turn_with_draft(
        session_id, draft, modified_content="Modified text with new scope"
    )
    assert resumed_edited["content"] == "Modified text with new scope"

    # Reject empty resume content
    with pytest.raises(ValueError, match="cannot be empty"):
        preserver.resume_turn_with_draft(session_id, draft, modified_content="   ")


def test_multi_queue_management_and_history() -> None:
    """Verify normal queue consumption and multiple queued message recovery."""
    preserver = GracefulTurnInterruptPreserver()
    session_id = "sess-004"

    preserver.enqueue_message(session_id, "Msg 1")
    preserver.enqueue_message(session_id, "Msg 2")
    preserver.enqueue_message(session_id, "Msg 3")

    # Dequeue first message
    consumed = preserver.consume_next_message(session_id)
    assert consumed is not None
    assert consumed.content == "Msg 1"
    assert len(preserver.get_unconsumed_queue(session_id)) == 2

    # Interrupt with 2 remaining messages in queue
    result = preserver.handle_interrupt(
        session_id=session_id,
        turn_id="turn-401",
        current_context_messages=[{"role": "user", "content": "Initial prompt"}],
        reason=InterruptReason.TIMEOUT,
    )

    assert result.turn_state.reason == InterruptReason.TIMEOUT
    assert len(result.salvaged_drafts) == 2
    assert result.salvaged_drafts[0].content == "Msg 2"
    assert result.salvaged_drafts[1].content == "Msg 3"

    # Verify history query
    last_res = preserver.get_last_preservation_result(session_id)
    assert last_res is not None
    assert last_res.turn_id == "turn-401"
