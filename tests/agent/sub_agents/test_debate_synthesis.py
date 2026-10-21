"""[INPUT] None.
[OUTPUT] Unit test suite for Hierarchical Leader-Worker Debate & Synthesis Pattern.
[POS] Subagent debate synthesis pattern testing.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.debate.synthesis_pattern import (
    CandidateProposal,
    HierarchicalDebateSynthesisEngine,
    SynthesisPhase,
    SynthesisRole,
    TradeoffDimension,
)


@pytest.fixture
def synthesis_engine() -> HierarchicalDebateSynthesisEngine:
    return HierarchicalDebateSynthesisEngine()


def test_workflow_creation_and_panel_initialization(
    synthesis_engine: HierarchicalDebateSynthesisEngine,
) -> None:
    state = synthesis_engine.create_workflow(
        workflow_id="wf-test-01",
        chat_id="chat-101",
        topic="Database Sharding vs Distributed SQL Migration",
        leader_id="agt-codex-lead",
        researcher_id="agt-researcher",
        auditor_id="agt-auditor",
        max_rounds=2,
    )

    assert state.workflow_id == "wf-test-01"
    assert state.phase == SynthesisPhase.DECOMPOSITION
    assert len(state.participants) == 3
    assert state.round_index == 1
    assert state.max_rounds == 2

    roles = {p.role: p.agent_id for p in state.participants}
    assert roles[SynthesisRole.LEADER_COORDINATOR] == "agt-codex-lead"
    assert roles[SynthesisRole.RESEARCH_ANALYST] == "agt-researcher"
    assert roles[SynthesisRole.FEASIBILITY_AUDITOR] == "agt-auditor"


def test_auto_decomposition_with_dependency_dag(
    synthesis_engine: HierarchicalDebateSynthesisEngine,
) -> None:
    synthesis_engine.create_workflow(
        workflow_id="wf-decomp-01",
        chat_id="chat-102",
        topic="Adopt Micro-Frontends Architecture",
        leader_id="agt-lead",
        researcher_id="agt-res",
        auditor_id="agt-aud",
    )

    # Permission check: non-leader cannot decompose
    with pytest.raises(PermissionError):
        synthesis_engine.auto_decompose("wf-decomp-01", leader_agent_id="agt-res")

    # Leader decomposes
    state = synthesis_engine.auto_decompose("wf-decomp-01", leader_agent_id="agt-lead")
    assert state.phase == SynthesisPhase.RESEARCH_DISCOVERY
    assert len(state.subtasks) == 2

    task_res = state.subtasks[0]
    task_aud = state.subtasks[1]

    assert task_res.assigned_role == SynthesisRole.RESEARCH_ANALYST
    assert task_res.depends_on == []

    assert task_aud.assigned_role == SynthesisRole.FEASIBILITY_AUDITOR
    assert task_aud.depends_on == [task_res.task_id]


def test_proposal_submission_and_phase_progression(
    synthesis_engine: HierarchicalDebateSynthesisEngine,
) -> None:
    synthesis_engine.create_workflow(
        workflow_id="wf-prop-01",
        chat_id="chat-103",
        topic="Zero-Copy Serialization in IPC Pipeline",
        leader_id="agt-lead",
        researcher_id="agt-res",
        auditor_id="agt-aud",
    )
    synthesis_engine.auto_decompose("wf-prop-01", leader_agent_id="agt-lead")

    # 1. Researcher submits cutting-edge proposal
    prop_res = CandidateProposal(
        proposal_id="prop-arrow",
        title="Apache Arrow Shared Memory IPC",
        author_role=SynthesisRole.RESEARCH_ANALYST,
        author_agent_id="agt-res",
        summary="High-throughput columnar memory layout with direct memory mapping.",
        pros=["Near zero CPU serialization overhead", "Ecosystem standard across Python and Rust"],
        cons=["Strict schema alignment required"],
        dimension_scores={
            TradeoffDimension.PERFORMANCE: 0.95,
            TradeoffDimension.COST_EFFICIENCY: 0.85,
            TradeoffDimension.IMPLEMENTATION_COMPLEXITY: 0.60,
            TradeoffDimension.RELIABILITY: 0.90,
            TradeoffDimension.MAINTAINABILITY: 0.80,
        },
    )
    state = synthesis_engine.submit_proposal("wf-prop-01", prop_res)
    assert state.phase == SynthesisPhase.FEASIBILITY_CRITIQUE

    # 2. Feasibility auditor submits conservative critique proposal
    prop_aud = CandidateProposal(
        proposal_id="prop-proto",
        title="Protobuf over Unix Domain Sockets",
        author_role=SynthesisRole.FEASIBILITY_AUDITOR,
        author_agent_id="agt-aud",
        summary="Mature, low-risk RPC with battle-tested backward compatibility.",
        pros=["Minimal migration complexity", "Universal cross-language tooling"],
        cons=["Higher serialization memory copy overhead than Arrow"],
        dimension_scores={
            TradeoffDimension.PERFORMANCE: 0.70,
            TradeoffDimension.COST_EFFICIENCY: 0.75,
            TradeoffDimension.IMPLEMENTATION_COMPLEXITY: 0.90,
            TradeoffDimension.RELIABILITY: 0.95,
            TradeoffDimension.MAINTAINABILITY: 0.85,
        },
    )
    state = synthesis_engine.submit_proposal("wf-prop-01", prop_aud)
    assert state.phase == SynthesisPhase.CROSS_DEBATE


def test_cross_debate_advance_and_convergence_guard(
    synthesis_engine: HierarchicalDebateSynthesisEngine,
) -> None:
    synthesis_engine.create_workflow(
        workflow_id="wf-conv-01",
        chat_id="chat-104",
        topic="Service Mesh vs Gateway API",
        leader_id="agt-lead",
        researcher_id="agt-res",
        auditor_id="agt-aud",
        max_rounds=2,
    )
    synthesis_engine.auto_decompose("wf-conv-01", leader_agent_id="agt-lead")

    # Round 1 -> Round 2
    state = synthesis_engine.advance_cross_debate("wf-conv-01")
    assert state.round_index == 2
    assert state.phase == SynthesisPhase.CROSS_DEBATE

    # Round 2 meets max_rounds -> Forced convergence
    state = synthesis_engine.advance_cross_debate("wf-conv-01")
    assert state.phase == SynthesisPhase.SYNTHESIS_CONVERGENCE


def test_tradeoff_matrix_synthesis_and_winner_selection(
    synthesis_engine: HierarchicalDebateSynthesisEngine,
) -> None:
    synthesis_engine.create_workflow(
        workflow_id="wf-matrix-01",
        chat_id="chat-105",
        topic="Object Storage vs Distributed FS",
        leader_id="agt-lead",
        researcher_id="agt-res",
        auditor_id="agt-aud",
    )
    synthesis_engine.auto_decompose("wf-matrix-01", leader_agent_id="agt-lead")

    prop_s3 = CandidateProposal(
        proposal_id="opt-s3",
        title="Cloud Object Storage (S3-compatible)",
        author_role=SynthesisRole.RESEARCH_ANALYST,
        author_agent_id="agt-res",
        summary="Serverless infinite scale with built-in replication.",
        pros=["Infinite scalability", "Zero ops overhead"],
        cons=["Higher read latency than local block/posix FS"],
        dimension_scores={
            TradeoffDimension.PERFORMANCE: 0.75,
            TradeoffDimension.COST_EFFICIENCY: 0.95,
            TradeoffDimension.IMPLEMENTATION_COMPLEXITY: 0.85,
            TradeoffDimension.RELIABILITY: 0.98,
            TradeoffDimension.MAINTAINABILITY: 0.90,
        },
    )

    prop_ceph = CandidateProposal(
        proposal_id="opt-ceph",
        title="Self-hosted Ceph Clustered FS",
        author_role=SynthesisRole.FEASIBILITY_AUDITOR,
        author_agent_id="agt-aud",
        summary="High-performance low-latency POSIX cluster.",
        pros=["Sub-millisecond latency"],
        cons=["Huge operational burden and hardware cost"],
        dimension_scores={
            TradeoffDimension.PERFORMANCE: 0.92,
            TradeoffDimension.COST_EFFICIENCY: 0.40,
            TradeoffDimension.IMPLEMENTATION_COMPLEXITY: 0.30,
            TradeoffDimension.RELIABILITY: 0.80,
            TradeoffDimension.MAINTAINABILITY: 0.45,
        },
    )

    synthesis_engine.submit_proposal("wf-matrix-01", prop_s3)
    synthesis_engine.submit_proposal("wf-matrix-01", prop_ceph)

    # Leader synthesizes decision matrix
    matrix = synthesis_engine.synthesize_decision_matrix("wf-matrix-01")

    assert matrix.workflow_id == "wf-matrix-01"
    assert len(matrix.dimensions) == 5
    assert matrix.winner_proposal_id == "opt-s3"
    assert "optimal recommendation" in matrix.recommendation_rationale

    # Check updated workflow state
    wf = synthesis_engine.get_workflow("wf-matrix-01")
    assert wf is not None
    assert wf.phase == SynthesisPhase.COMPLETED
    assert wf.matrix is not None
    assert any(p.proposal_id == "opt-s3" and p.is_recommended for p in wf.proposals)
