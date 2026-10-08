# [INPUT]: CompactedTurnPartition, DecoupledDigestSynthesizer, TriFateCompactionConfig, TriFateDecisionMarker, TurnEvidence, TurnFate, TurnFateDecision, TurnLevelTriFateCompactionAndDecoupledDigestSynthesizerSuite, TurnLevelTriFateCompactionSuite, TurnLevelTriFateCompactor
# [OUTPUT]: test_tri_fate_compaction_suite.py
# [POS]: tests/agent/context_management/test_tri_fate_compaction_suite.py

"""Comprehensive unit tests for TurnLevelTriFateCompactionAndDecoupledDigestSynthesizerSuite.

Verifies:
1. Technical anchor extraction and hard KEEP enforcement for code paths, UUIDs, tracebacks, and commands.
2. Transient chatter detection and high-confidence DROP classification.
3. Irreversible drop confidence threshold gate (<0.7) and safe automatic escalation to SUMMARIZE.
4. Recent turn tail preservation guard unconditionally retaining latest N turns.
5. Decoupled digest synthesis exclusively condensing the SUMMARIZE partition.
6. End-to-end compaction pipeline: partitioning, digest reconstruction, and audit telemetry.
7. Full facade parity and alias identity.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.tri_fate_compaction import (
    CompactedTurnPartition,
    DecoupledDigestSynthesizer,
    TriFateCompactionConfig,
    TriFateDecisionMarker,
    TurnEvidence,
    TurnFate,
    TurnFateDecision,
    TurnLevelTriFateCompactionAndDecoupledDigestSynthesizerSuite,
    TurnLevelTriFateCompactionSuite,
    TurnLevelTriFateCompactor,
)


def test_technical_anchor_extraction_and_hard_keep() -> None:
    """Verifies that turns carrying concrete code paths, commands, or errors are hard-preserved as KEEP."""
    marker = TriFateDecisionMarker()

    # 1. Turn with file path and CLI command
    turn_cmd = TurnEvidence(
        turn_id="t1",
        role="assistant",
        content="Please run pytest src/auth/login.py to verify credentials.",
    )
    decision_cmd = marker.evaluate_turn(turn_cmd, turn_index=0, total_turns=10)
    assert decision_cmd.fate == TurnFate.KEEP
    assert decision_cmd.confidence >= 0.95
    assert any("src/auth/login.py" in a for a in decision_cmd.extracted_anchors)

    # 2. Turn with UUID and strict constraint
    turn_uuid = TurnEvidence(
        turn_id="t2",
        role="user",
        content="The target tenant id is 12345678-1234-1234-1234-123456789abc and you must never delete it.",
    )
    decision_uuid = marker.evaluate_turn(turn_uuid, turn_index=1, total_turns=10)
    assert decision_uuid.fate == TurnFate.KEEP
    assert len(decision_uuid.extracted_anchors) >= 1

    # 3. Turn with traceback
    turn_err = TurnEvidence(
        turn_id="t3",
        role="assistant",
        content="Traceback (most recent call last):\n  File 'app.py', line 12\nAssertionError",
    )
    decision_err = marker.evaluate_turn(turn_err, turn_index=2, total_turns=10)
    assert decision_err.fate == TurnFate.KEEP


def test_chatter_detection_and_high_confidence_drop() -> None:
    """Verifies that pure transient conversational chatter is safely categorized as DROP."""
    marker = TriFateDecisionMarker()

    chatter_turns = [
        TurnEvidence(turn_id="c1", role="user", content="ok"),
        TurnEvidence(turn_id="c2", role="assistant", content="Got it!"),
        TurnEvidence(turn_id="c3", role="user", content="好的"),
        TurnEvidence(turn_id="c4", role="assistant", content="Starting work now"),
    ]

    for idx, turn in enumerate(chatter_turns):
        decision = marker.evaluate_turn(turn, turn_index=idx, total_turns=12)
        assert decision.fate == TurnFate.DROP
        assert decision.confidence >= 0.7
        assert decision.was_escalated_from_drop is False


def test_irreversible_drop_confidence_gate_and_escalation() -> None:
    """Verifies that ambiguous short turns (<0.7 confidence) are automatically escalated to SUMMARIZE."""
    config = TriFateCompactionConfig(min_drop_confidence=0.7)
    marker = TriFateDecisionMarker(config)

    # Ambiguous short statement that is not hard chatter and carries no anchors
    ambiguous_turn = TurnEvidence(
        turn_id="amb-1",
        role="user",
        content="Maybe later we consider this",
    )

    decision = marker.evaluate_turn(ambiguous_turn, turn_index=0, total_turns=10)
    # Because drop confidence is ~0.55 < 0.70 threshold, it must be safely promoted to SUMMARIZE
    assert decision.fate == TurnFate.SUMMARIZE
    assert decision.was_escalated_from_drop is True
    assert "safely escalated from DROP to SUMMARIZE" in decision.rationale


def test_recent_turn_tail_preservation_guard() -> None:
    """Verifies that the most recent N turns are unconditionally preserved to maintain continuity."""
    config = TriFateCompactionConfig(preserve_last_n_turns=3)
    marker = TriFateDecisionMarker(config)

    total = 6
    # Turn at index 3 (total - 3 = 3 -> turns_from_end = 2 < 3) is within tail window
    tail_chatter = TurnEvidence(turn_id="tail-1", role="user", content="ok")

    decision = marker.evaluate_turn(tail_chatter, turn_index=4, total_turns=total)
    assert decision.fate == TurnFate.KEEP
    assert decision.confidence == 1.0
    assert "recent turn tail window" in decision.rationale


def test_decoupled_digest_synthesis() -> None:
    """Verifies that only turns partitioned under SUMMARIZE are distilled into Markdown digests."""
    synthesizer = DecoupledDigestSynthesizer()

    summarize_turns = [
        TurnEvidence(turn_id="s1", role="user", content="We need to build a distributed cache with Redis."),
        TurnEvidence(turn_id="s2", role="assistant", content="Understood, I will evaluate redis-py and aioredis."),
    ]

    digest = synthesizer.synthesize_digest(summarize_turns)
    assert "### [Compacted Context Digest: Turns s1 to s2]" in digest
    assert "**User**: We need to build a distributed cache with Redis." in digest
    assert "**Assistant**: Understood, I will evaluate redis-py and aioredis." in digest

    # Empty summarize partition returns empty string
    empty_digest = synthesizer.synthesize_digest([])
    assert empty_digest == ""


def test_compactor_end_to_end_reconstruction_and_audit() -> None:
    """Verifies full tripartite partitioning, decoupled synthesis, and reconstituted prompt assembly."""
    config = TriFateCompactionConfig(preserve_last_n_turns=2, min_drop_confidence=0.7)
    compactor = TurnLevelTriFateCompactor(config)

    turns = [
        # Turn 0: Technical Anchor -> KEEP
        TurnEvidence(turn_id="t0", role="system", content="Architecture requirement: deploy to src/cluster.py"),
        # Turn 1: Chatter -> DROP
        TurnEvidence(turn_id="t1", role="user", content="ok"),
        # Turn 2: Informative background -> SUMMARIZE
        TurnEvidence(turn_id="t2", role="user", content="The staging environment currently runs Postgres 16."),
        # Turn 3: Informative response -> SUMMARIZE
        TurnEvidence(turn_id="t3", role="assistant", content="Noted, ensuring backward compatibility with pg16."),
        # Turn 4: Recent turn -> KEEP (tail guard)
        TurnEvidence(turn_id="t4", role="user", content="What is the next deployment step?"),
        # Turn 5: Recent turn -> KEEP (tail guard)
        TurnEvidence(turn_id="t5", role="assistant", content="Running migrations now."),
    ]

    reconstructed, partition, telemetry = compactor.compact_and_reconstruct(turns)

    # Validate partition counts
    assert len(partition.kept_turns) == 3  # t0 (anchor), t4 (tail), t5 (tail)
    assert len(partition.summarized_turns) == 2  # t2, t3
    assert len(partition.dropped_turns) == 1  # t1 (chatter)

    # Validate reconstructed prompt structure
    assert "### [Compacted Context Digest: Turns t2 to t3]" in reconstructed
    assert "Postgres 16" in reconstructed
    assert "[SYSTEM]: Architecture requirement: deploy to src/cluster.py" in reconstructed
    assert "[USER]: What is the next deployment step?" in reconstructed
    assert "[ASSISTANT]: Running migrations now." in reconstructed
    # Dropped chatter turn must NOT appear anywhere in the reconstructed context
    assert "t1" not in reconstructed

    # Validate telemetry
    assert telemetry["total_turns"] == 6
    assert telemetry["kept_count"] == 3
    assert telemetry["summarized_count"] == 2
    assert telemetry["dropped_count"] == 1
    assert pytest.approx(telemetry["drop_ratio"], 0.01) == 0.1667


def test_facade_alias_parity_and_lifecycle() -> None:
    """Verifies facade instantiation, method delegation, and alias equality."""
    assert TurnLevelTriFateCompactionAndDecoupledDigestSynthesizerSuite is TurnLevelTriFateCompactionSuite

    suite = TurnLevelTriFateCompactionAndDecoupledDigestSynthesizerSuite()
    assert isinstance(suite.config, TriFateCompactionConfig)

    turn = TurnEvidence(turn_id="x1", role="assistant", content="Running cargo build --release")
    dec = suite.evaluate_single_turn(turn, turn_index=0, total_turns=5)
    assert dec.fate == TurnFate.KEEP

    digest = suite.synthesize_digest([TurnEvidence(turn_id="x2", role="user", content="Researching LLMs")])
    assert "Compacted Context Digest" in digest
