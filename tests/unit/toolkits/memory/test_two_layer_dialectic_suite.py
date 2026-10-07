# [POS]: tests.unit.toolkits.memory.test_two_layer_dialectic_suite
# [INPUT]: myrm_agent_harness.toolkits.memory (two_layer_dialectic models & engines)
# [OUTPUT]: Pytest test cases validating dual-layer injection and multi-pass dialectic reconciliation

"""Unit tests for Two-Layer Context Injection and Multi-Pass Dialectic Reconciliation Suite.

Validates cadence control, Prompt Cache preservation, and contradiction harmonization.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory import (
    DialecticPassKind,
    DialecticReconciliationConfig,
    MultiPassDialecticReconciler,
    TwoLayerContextInjector,
)


def test_reconciler_conflict_inspection_and_multi_pass():
    """Verify inspection and 3-pass dialectic resolution over mutually exclusive statements."""
    config = DialecticReconciliationConfig(dialectic_depth=3, conflict_similarity_cutoff=0.4)
    reconciler = MultiPassDialecticReconciler(config)

    statements = [
        "Project uses PostgreSQL for persistent relational storage.",
        "Project switched from PostgreSQL to SQLite for local embedded storage.",
    ]

    conflicts = reconciler.inspect_conflicts(statements)
    assert len(conflicts) >= 1
    candidate = conflicts[0]
    assert "postgresql" in candidate.statement_a.lower()
    assert "sqlite" in candidate.statement_b.lower()

    # Pass 1: Depth 1 Inspection only
    res_depth_1 = reconciler.reconcile_conflict(candidate, depth=1)
    assert len(res_depth_1.passes_executed) == 1
    assert res_depth_1.passes_executed[0] == DialecticPassKind.INSPECTION
    assert res_depth_1.confidence == 0.5

    # Pass 2: Depth 2 Synthesis
    res_depth_2 = reconciler.reconcile_conflict(candidate, depth=2)
    assert len(res_depth_2.passes_executed) == 2
    assert res_depth_2.passes_executed[1] == DialecticPassKind.SYNTHESIS
    assert res_depth_2.confidence == 0.8

    # Pass 3: Depth 3 Full Reconciliation
    res_depth_3 = reconciler.reconcile_conflict(candidate, depth=3)
    assert len(res_depth_3.passes_executed) == 3
    assert res_depth_3.passes_executed[2] == DialecticPassKind.RECONCILIATION
    assert res_depth_3.confidence >= 0.9
    assert "sqlite" in res_depth_3.resolved_statement.lower()
    assert len(res_depth_3.superseded_statements) == 1
    assert "postgresql" in res_depth_3.superseded_statements[0].lower()


def test_reconciler_no_conflict_scenario():
    """Verify reconciler cleanly ignores non-overlapping statements."""
    reconciler = MultiPassDialecticReconciler()
    statements = [
        "User prefers dark mode UI theme.",
        "Backend server runs on port 8000.",
    ]
    conflicts = reconciler.inspect_conflicts(statements)
    assert len(conflicts) == 0

    results = reconciler.reconcile_all(statements)
    assert len(results) == 0


def test_injector_layer1_cadence_and_cache_hash():
    """Verify Layer 1 cadence preserves hash stability across turns."""
    config = DialecticReconciliationConfig(context_cadence=5)
    injector = TwoLayerContextInjector(config)
    session_id = "session-cadence-001"

    summary_v1 = "Initial user goal: build web app."
    peers = ["PeerAlice (Researcher)", "PeerBob (Coder)"]

    # Turn 0: initial build
    payload_0, refreshed_0 = injector.build_base_context(
        session_id=session_id, turn=0, session_summary=summary_v1, peer_cards=peers
    )
    assert refreshed_0 is True
    initial_hash = payload_0.cache_control_hash
    assert len(initial_hash) == 16
    assert payload_0.refreshed_at_turn == 0

    # Turn 2 (< cadence=5): should hit cache without refresh
    payload_2, refreshed_2 = injector.build_base_context(
        session_id=session_id, turn=2, session_summary="Updated goal with slight drift", peer_cards=peers
    )
    assert refreshed_2 is False
    assert payload_2.cache_control_hash == initial_hash
    assert payload_2.refreshed_at_turn == 0

    # Turn 5 (>= cadence=5): should refresh with new content
    payload_5, refreshed_5 = injector.build_base_context(
        session_id=session_id, turn=5, session_summary="New major milestone achieved", peer_cards=peers
    )
    assert refreshed_5 is True
    assert payload_5.refreshed_at_turn == 5
    assert payload_5.cache_control_hash != initial_hash


def test_injector_layer2_dialectic_cadence_and_assembly():
    """Verify Layer 2 is conditionally synthesized and placed at user_message_tail."""
    config = DialecticReconciliationConfig(context_cadence=5, dialectic_cadence=3)
    injector = TwoLayerContextInjector(config)
    session_id = "session-dialectic-002"

    candidate_memories = [
        "Deployment target is AWS ECS Fargate.",
        "Deployment target migrated from AWS ECS to Cloudflare Workers.",
    ]

    # Turn 0: Dialectic cadence triggers resolution
    res_0 = injector.assemble_injection(
        session_id=session_id,
        turn=0,
        session_summary="Deploying service",
        candidate_memories=candidate_memories,
    )
    assert "<base_context cache_hash=" in res_0.layer1_base_context
    assert "<dialectic_reconciliation>" in res_0.layer2_dialectic_block
    assert res_0.injected_position == "user_message_tail"
    assert res_0.is_cache_safe is True
    assert res_0.token_overhead > 0

    # Turn 1 (< dialectic_cadence=3): Dialectic block should be omitted to save tokens
    res_1 = injector.assemble_injection(
        session_id=session_id,
        turn=1,
        session_summary="Deploying service",
        candidate_memories=candidate_memories,
    )
    assert res_1.layer2_dialectic_block == ""

    # Force dialectic: overrides cadence
    res_forced = injector.assemble_injection(
        session_id=session_id,
        turn=1,
        session_summary="Deploying service",
        candidate_memories=candidate_memories,
        force_dialectic=True,
    )
    assert "<dialectic_reconciliation>" in res_forced.layer2_dialectic_block

    # Reset session evicts cache
    injector.reset_session(session_id)
    assert injector.get_cached_base_context(session_id) is None
