from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context import (
    CommunicationInteractionKind,
    CrossAgentCommunicationGraphEngine,
    MessageDurability,
)


def test_cross_agent_communication_recording_and_causal_dag_tracing() -> None:
    """Test recording directed edges between 3 agents and tracing full ancestor causal chain."""
    engine = CrossAgentCommunicationGraphEngine()

    # Step 1: Leader delegates task to Coder
    e1 = engine.record_communication(
        sender_agent_id="leader_agent",
        receiver_agent_id="coder_agent",
        content="Please implement Auth Middleware with token validation.",
        interaction_kind=CommunicationInteractionKind.DELEGATION,
        durability=MessageDurability.DURABLE,
        phase_tag="auth_phase_1",
    )

    # Step 2: Coder asks Reviewer for peer critique (caused by e1)
    e2 = engine.record_communication(
        sender_agent_id="coder_agent",
        receiver_agent_id="reviewer_agent",
        content="Here is the initial PR draft for Auth Middleware.",
        interaction_kind=CommunicationInteractionKind.PEER_CRITIQUE,
        durability=MessageDurability.EPHEMERAL,
        phase_tag="auth_phase_1",
        causal_parent_edge_id=e1.edge_id,
    )

    # Step 3: Reviewer responds with review suggestions (caused by e2)
    e3 = engine.record_communication(
        sender_agent_id="reviewer_agent",
        receiver_agent_id="coder_agent",
        content="Please add JWT expiration check and clock skew tolerance of 5 seconds.",
        interaction_kind=CommunicationInteractionKind.NEGOTIATION,
        durability=MessageDurability.EPHEMERAL,
        phase_tag="auth_phase_1",
        causal_parent_edge_id=e2.edge_id,
    )

    # Step 4: Coder amends code and replies (caused by e3)
    e4 = engine.record_communication(
        sender_agent_id="coder_agent",
        receiver_agent_id="reviewer_agent",
        content="Added JWT expiration check and 5s clock skew tolerance.",
        interaction_kind=CommunicationInteractionKind.NEGOTIATION,
        durability=MessageDurability.EPHEMERAL,
        phase_tag="auth_phase_1",
        causal_parent_edge_id=e3.edge_id,
    )

    # Step 5: Reviewer approves (caused by e4)
    e5 = engine.record_communication(
        sender_agent_id="reviewer_agent",
        receiver_agent_id="coder_agent",
        content="Code verified. LGTM, approved for merge.",
        interaction_kind=CommunicationInteractionKind.NEGOTIATION,
        durability=MessageDurability.DURABLE,
        phase_tag="auth_phase_1",
        causal_parent_edge_id=e4.edge_id,
    )

    # Trace backward from e5 to discover full ancestor causal DAG
    causal_chain = engine.get_causal_chain(e5.edge_id)
    assert len(causal_chain) == 5
    assert [edge.edge_id for edge in causal_chain] == [
        e1.edge_id,
        e2.edge_id,
        e3.edge_id,
        e4.edge_id,
        e5.edge_id,
    ]


def test_phase_end_ephemeral_pruning_and_token_reduction() -> None:
    """Test pruning temporary negotiation chatter upon phase completion and checking token reduction."""
    engine = CrossAgentCommunicationGraphEngine()

    # Create 5 ephemeral negotiation messages with extensive verbose text
    verbose_filler = "This is a detailed technical review explaining why line 45 needs refactoring with ABC XYZ. " * 5
    engine.record_communication(
        sender_agent_id="coder",
        receiver_agent_id="reviewer",
        content=f"Initial draft: {verbose_filler}",
        durability=MessageDurability.EPHEMERAL,
        phase_tag="refactor_phase",
    )
    for i in range(1, 5):
        engine.record_communication(
            sender_agent_id="reviewer" if i % 2 == 1 else "coder",
            receiver_agent_id="coder" if i % 2 == 1 else "reviewer",
            content=f"Round {i} negotiation discussion: {verbose_filler}",
            durability=MessageDurability.EPHEMERAL,
            phase_tag="refactor_phase",
        )

    # Conclude phase with pruning
    prune_result = engine.prune_phase_communication(
        phase_tag="refactor_phase",
        decision_conclusion="Refactoring approved: replaced nested loop with O(N) hash map.",
        durable_artifacts=["src/pipeline/hasher.py"],
    )

    # 1. Ephemeral edges count pruned
    assert prune_result.pruned_edges_count == 5

    # 2. Token reduction rate exceeds 70%
    assert prune_result.token_reduction_rate >= 0.70

    # 3. Decision conclusion and deliverable present in rendered block
    block = prune_result.rendered_causal_summary_block
    assert '<system_causal_collaboration_summary phase="refactor_phase">' in block
    assert "Refactoring approved" in block
    assert "src/pipeline/hasher.py" in block
    assert "5 temporary discussion turns safely pruned" in block


def test_active_context_rendering_with_pruned_and_unpruned_phases() -> None:
    """Test render_active_context seamlessly combines folded summaries and active phase chatter."""
    engine = CrossAgentCommunicationGraphEngine()

    # Phase 1: Completed and pruned
    engine.record_communication(
        sender_agent_id="agent_a",
        receiver_agent_id="agent_b",
        content="Chatter round 1 in phase 1",
        durability=MessageDurability.EPHEMERAL,
        phase_tag="phase_1",
    )
    engine.record_communication(
        sender_agent_id="agent_b",
        receiver_agent_id="agent_a",
        content="Key durable outcome: config finalized",
        durability=MessageDurability.DURABLE,
        phase_tag="phase_1",
    )
    engine.prune_phase_communication("phase_1", decision_conclusion="Config finalized.")

    # Phase 2: Currently active and unpruned
    engine.record_communication(
        sender_agent_id="agent_c",
        receiver_agent_id="agent_d",
        content="Live deployment in progress...",
        durability=MessageDurability.EPHEMERAL,
        phase_tag="phase_2",
    )

    context = engine.render_active_context()

    # Phase 1 ephemeral message is NOT in context
    assert "Chatter round 1 in phase 1" not in context
    # Phase 1 summary and durable deliverable ARE in context
    assert '<system_causal_collaboration_summary phase="phase_1">' in context
    assert "Key durable outcome: config finalized" in context

    # Phase 2 live chatter IS in context
    assert "Live deployment in progress..." in context


def test_prune_unknown_phase_raises_error() -> None:
    """Test pruning non-existent phase raises ValueError."""
    engine = CrossAgentCommunicationGraphEngine()
    with pytest.raises(ValueError, match="has no recorded communication edges"):
        engine.prune_phase_communication("non_existent_phase")
