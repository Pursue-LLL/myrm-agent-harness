"""Unit tests for Multi-Bot Mention Focus Tracker and Anti-Thrash Compactor (Item 42).

[INPUT]
- myrm_agent_harness.agent.coordination.multi_bot_focus::{
    BotFocusSnapshot,
    CompactionEvaluation,
    CompactionPolicy,
    MultiBotFocusAndCompactionGuard,
    MultiBotFocusError,
    StreamCardHeartbeat,
    StreamCardState,
  }

[OUTPUT]
- Pytest cases verifying viewport-based focus resolution for @mention,
  anti-thrash hysteresis and cooldown window compaction suppression,
  and dead stream card abandonment detection.

[POS]
- myrm-agent-harness/tests/agent/coordination/test_multi_bot_focus.py
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.agent.coordination.multi_bot_focus import (
    CompactionPolicy,
    MultiBotFocusAndCompactionGuard,
    MultiBotFocusError,
    StreamCardState,
)


@pytest.fixture
def guard() -> MultiBotFocusAndCompactionGuard:
    return MultiBotFocusAndCompactionGuard()


def test_update_and_get_focused_bot(guard: MultiBotFocusAndCompactionGuard) -> None:
    session_id = "sess_group_chat"

    # Bot A is viewport active at turn 1 (score = 100 + 1 = 101)
    guard.update_bot_focus(
        session_id=session_id,
        bot_id="bot_writer",
        is_viewport_active=True,
        turn_index=1,
    )
    # Bot B is background active at turn 5 (score = 0 + 5 = 5)
    guard.update_bot_focus(
        session_id=session_id,
        bot_id="bot_reviewer",
        is_viewport_active=False,
        turn_index=5,
    )

    # Active viewport bot wins
    focused = guard.get_focused_bot(session_id)
    assert focused == "bot_writer"

    # Now Bot B becomes viewport active at turn 6 (score = 100 + 6 = 106)
    guard.update_bot_focus(
        session_id=session_id,
        bot_id="bot_reviewer",
        is_viewport_active=True,
        turn_index=6,
    )
    assert guard.get_focused_bot(session_id) == "bot_reviewer"

    snapshots = guard.get_all_focus_snapshots(session_id)
    assert len(snapshots) == 2


def test_bot_focus_validation_errors(guard: MultiBotFocusAndCompactionGuard) -> None:
    with pytest.raises(MultiBotFocusError, match="Session ID cannot be empty"):
        guard.update_bot_focus("", "bot_1", True, 1)

    with pytest.raises(MultiBotFocusError, match="Bot ID cannot be empty"):
        guard.update_bot_focus("sess_1", "  ", True, 1)

    assert guard.get_focused_bot("unknown_session") is None


def test_evaluate_compaction_below_threshold(
    guard: MultiBotFocusAndCompactionGuard,
) -> None:
    policy = CompactionPolicy(trigger_threshold_ratio=0.90)
    decision = guard.evaluate_compaction(
        session_id="sess_token_test",
        current_tokens=7000,
        max_context_tokens=10000,
        current_turn=5,
        policy=policy,
    )
    assert decision.should_compact is False
    assert "below trigger threshold" in decision.reason
    assert decision.cooldown_remaining == 0


def test_evaluate_compaction_triggered_and_cooldown(
    guard: MultiBotFocusAndCompactionGuard,
) -> None:
    policy = CompactionPolicy(
        trigger_threshold_ratio=0.90, cooldown_turns=3, min_token_delta=500
    )
    session_id = "sess_thrash_test"

    # 1. Triggered initially (9500 >= 9000)
    decision_1 = guard.evaluate_compaction(
        session_id=session_id,
        current_tokens=9500,
        max_context_tokens=10000,
        current_turn=5,
        policy=policy,
    )
    assert decision_1.should_compact is True

    # 2. Record execution at turn 5, reduced to 6000 tokens
    guard.record_compaction_executed(
        session_id=session_id, executed_turn=5, tokens_after=6000
    )

    # 3. Fast tool loops pump tokens to 9200 at turn 6 (within 3 turns cooldown)
    decision_cooldown = guard.evaluate_compaction(
        session_id=session_id,
        current_tokens=9200,
        max_context_tokens=10000,
        current_turn=6,
        policy=policy,
    )
    assert decision_cooldown.should_compact is False
    assert decision_cooldown.cooldown_remaining == 2
    assert "Within cooldown" in decision_cooldown.reason or "suppressed by cooldown" in decision_cooldown.reason

    # 4. At turn 8 (turns_since = 3 >= cooldown_turns), tokens 9200 (delta 3200 >= 500)
    decision_after_cooldown = guard.evaluate_compaction(
        session_id=session_id,
        current_tokens=9200,
        max_context_tokens=10000,
        current_turn=8,
        policy=policy,
    )
    assert decision_after_cooldown.should_compact is True


def test_evaluate_compaction_hysteresis_token_delta(
    guard: MultiBotFocusAndCompactionGuard,
) -> None:
    policy = CompactionPolicy(
        trigger_threshold_ratio=0.90, cooldown_turns=1, min_token_delta=1000
    )
    session_id = "sess_delta_test"

    # Compaction executed at turn 1, tokens after = 8800
    guard.record_compaction_executed(session_id, executed_turn=1, tokens_after=8800)

    # At turn 3, tokens = 9100 (> 9000 trigger threshold, cooldown passed, but delta 300 < 1000)
    decision = guard.evaluate_compaction(
        session_id=session_id,
        current_tokens=9100,
        max_context_tokens=10000,
        current_turn=3,
        policy=policy,
    )
    assert decision.should_compact is False
    assert "below minimum hysteresis delta" in decision.reason


def test_stream_card_heartbeat_and_abandonment(
    guard: MultiBotFocusAndCompactionGuard,
) -> None:
    session_id = "sess_stream_test"

    card_alive = guard.record_card_heartbeat(
        card_id="card_live_1",
        session_id=session_id,
        bot_id="bot_active",
        state=StreamCardState.STREAMING,
    )
    assert card_alive.state == StreamCardState.STREAMING

    card_dead = guard.record_card_heartbeat(
        card_id="card_dead_2",
        session_id=session_id,
        bot_id="bot_abandoned",
        state=StreamCardState.STREAMING,
    )
    assert card_dead.state == StreamCardState.STREAMING

    # Artificially age card_dead heartbeat past timeout
    ancient_time = datetime.now(tz=UTC) - timedelta(seconds=60)
    guard._cards["card_dead_2"] = guard._cards["card_dead_2"].__class__(
        card_id="card_dead_2",
        session_id=session_id,
        bot_id="bot_abandoned",
        state=StreamCardState.STREAMING,
        last_heartbeat_at=ancient_time,
    )

    abandoned = guard.detect_and_prune_abandoned_streams(
        session_id=session_id, timeout_seconds=30.0
    )
    assert abandoned == ["card_dead_2"]

    # Verify state transition
    dead_record = guard.get_card("card_dead_2")
    assert dead_record is not None
    assert dead_record.state == StreamCardState.ABANDONED

    # Alive card is untouched
    live_record = guard.get_card("card_live_1")
    assert live_record is not None
    assert live_record.state == StreamCardState.STREAMING

    # Mark completed
    assert guard.mark_card_completed("card_live_1") is True
    assert guard.get_card("card_live_1").state == StreamCardState.COMPLETED
