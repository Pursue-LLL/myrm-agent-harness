"""Unit tests for AppendOnlySessionEventSourcingAndContextReplayerSuite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    AppendOnlyEventLog,
    AppendOnlySessionEventSourcingAndContextReplayerSuite,
    DeterministicContextProjector,
    SessionEventKind,
)


def test_append_only_monotonic_sequence_and_hash_integrity() -> None:
    """Test append-only event stream maintaining monotonic sequence numbers and hash chain integrity."""
    suite = AppendOnlySessionEventSourcingAndContextReplayerSuite()
    session_id = "sess-audit-001"

    # Append sequential events
    evt1 = suite.record_user_prompt(session_id, "Optimize database index")
    evt2 = suite.record_assistant_reply(session_id, "I will inspect pg_stat_activity")
    evt3 = suite.record_tool_result(session_id, "sql_query", "10 slow queries found")

    assert evt1.sequence_number == 1
    assert evt2.sequence_number == 2
    assert evt3.sequence_number == 3

    assert len(evt1.event_digest) == 16
    assert len(evt2.event_digest) == 16
    assert len(evt3.event_digest) == 16

    # Verify cryptographic chain integrity
    assert suite.event_log.verify_chain_integrity(session_id) is True


def test_pure_functional_context_projection_at_exact_step() -> None:
    """Test that context at step K is a pure deterministic projection without future event leakage."""
    suite = AppendOnlySessionEventSourcingAndContextReplayerSuite()
    session_id = "sess-projection-002"

    # Sequence of events
    suite.record_system_directive(session_id, "RULE: Never delete production data.")
    suite.record_user_prompt(session_id, "Please review PR #42")
    suite.record_assistant_reply(session_id, "Reviewing PR #42 now...")
    suite.record_context_compaction(session_id, "PR #42 reviewed, 2 suggestions made.")
    suite.record_user_prompt(session_id, "What suggestions were made?")

    # 1. Project at step 2 (system directive + user prompt only)
    proj_step_2 = suite.replay_context_at_step(session_id, target_sequence=2)
    assert proj_step_2.target_sequence == 2
    assert "Never delete production data" in proj_step_2.effective_system_prompt
    assert len(proj_step_2.visible_messages) == 1
    assert proj_step_2.visible_messages[0].content == "Please review PR #42"
    assert proj_step_2.compaction_applied is False

    # 2. Project at step 3 (system directive + user prompt + assistant reply)
    proj_step_3 = suite.replay_context_at_step(session_id, target_sequence=3)
    assert len(proj_step_3.visible_messages) == 2
    assert proj_step_3.visible_messages[1].role == "assistant"

    # 3. Project at step 4 (after compaction)
    proj_step_4 = suite.replay_context_at_step(session_id, target_sequence=4)
    assert proj_step_4.compaction_applied is True
    assert len(proj_step_4.visible_messages) == 1
    assert "[Context Summary]" in proj_step_4.visible_messages[0].content

    # 4. Project at step 5 (after compaction + new user prompt)
    proj_step_5 = suite.replay_context_at_step(session_id, target_sequence=5)
    assert len(proj_step_5.visible_messages) == 2
    assert proj_step_5.visible_messages[1].content == "What suggestions were made?"


def test_replay_determinism_and_audit_certificate() -> None:
    """Test that replay double-projection verifies 100% determinism and issues audit certificate."""
    suite = AppendOnlySessionEventSourcingAndContextReplayerSuite()
    session_id = "sess-cert-003"

    suite.record_user_prompt(session_id, "Calculate Euler path")
    suite.record_assistant_reply(session_id, "Euler path exists if all vertices have even degree.")

    cert = suite.generate_replay_certificate(session_id, target_sequence=2)

    assert cert.session_id == session_id
    assert cert.target_sequence == 2
    assert cert.events_replayed_count == 2
    assert cert.is_deterministic is True
    assert len(cert.projection_digest) == 16


def test_diff_context_between_steps() -> None:
    """Test computing structural diff between historical steps."""
    suite = AppendOnlySessionEventSourcingAndContextReplayerSuite()
    session_id = "sess-diff-004"

    suite.record_user_prompt(session_id, "First prompt")
    suite.record_assistant_reply(session_id, "First reply")
    suite.record_context_compaction(session_id, "Compacted conversation")

    diff = suite.diff_context_between_steps(session_id, seq_a=2, seq_b=3)

    assert diff["step_a"] == 2
    assert diff["step_b"] == 3
    assert diff["messages_count_a"] == 2
    assert diff["messages_count_b"] == 1
    assert diff["compaction_triggered"] is True
    assert diff["digest_a"] != diff["digest_b"]
