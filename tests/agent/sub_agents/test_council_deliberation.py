"""Unit tests for Council of Agents Multi-Model Deliberation Protocol (Item 65).

[INPUT]
- CouncilDeliberationPipeline, ConsensusSynthesizer, CouncilProposal, CritiqueItem.

[OUTPUT]
- Pytest assertions verifying multi-model session lifecycle, blind proposals, cross-critiques,
  rebuttals, and confidence-weighted consensus synthesis.

[POS]
- myrm-agent-harness/tests/agent/sub_agents/test_council_deliberation.py
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.council import (
    ConsensusSynthesizer,
    CouncilDeliberationPipeline,
    CouncilProposal,
    CritiqueItem,
    CritiqueSeverity,
    DeliberationPhase,
)


@pytest.fixture
def pipeline() -> CouncilDeliberationPipeline:
    """Fixture providing a fresh CouncilDeliberationPipeline instance."""
    p = CouncilDeliberationPipeline()
    p.clear()
    return p


def test_council_pipeline_session_lifecycle(pipeline: CouncilDeliberationPipeline) -> None:
    """Verify session creation, retrieval, listing, and state reset."""
    session = pipeline.create_session("sess-council-01", "Database Sharding vs Partitioning")
    assert session.session_id == "sess-council-01"
    assert session.deliberation_topic == "Database Sharding vs Partitioning"
    assert session.phase == DeliberationPhase.BLIND_PROPOSAL
    assert len(session.proposals) == 0
    assert len(session.critiques) == 0
    assert session.consensus is None

    retrieved = pipeline.get_session("sess-council-01")
    assert retrieved is not None
    assert retrieved.session_id == "sess-council-01"

    sessions = pipeline.list_sessions()
    assert len(sessions) == 1

    pipeline.clear()
    assert pipeline.get_session("sess-council-01") is None
    assert len(pipeline.list_sessions()) == 0


def test_council_pipeline_blind_proposals(pipeline: CouncilDeliberationPipeline) -> None:
    """Verify multi-model blind proposal submission."""
    pipeline.create_session("sess-arch-eval", "Select Distributed Cache Architecture")

    prop1 = CouncilProposal(
        proposal_id="prop-claude",
        member_id="agent-01",
        model_name="Claude-3.5-Sonnet",
        title="Redis Cluster with Read-Replicas",
        reasoning_steps=["High throughput", "In-memory caching", "Sub-millisecond latency"],
        key_arguments=["Proven operational maturity", "Native cluster sharding"],
        confidence_score=0.92,
    )
    prop2 = CouncilProposal(
        proposal_id="prop-gpt4o",
        member_id="agent-02",
        model_name="GPT-4o",
        title="Dragonfly Multi-Threaded Redis-Compatible Cache",
        reasoning_steps=["Vertical scaling", "Low hardware footprint"],
        key_arguments=["Simpler single-node multi-core model", "Cost efficient"],
        confidence_score=0.88,
    )

    s1 = pipeline.submit_proposal("sess-arch-eval", prop1)
    assert len(s1.proposals) == 1
    assert "prop-claude" in s1.proposals

    s2 = pipeline.submit_proposal("sess-arch-eval", prop2)
    assert len(s2.proposals) == 2
    assert "prop-gpt4o" in s2.proposals


def test_council_pipeline_cross_critique_and_rebuttal(pipeline: CouncilDeliberationPipeline) -> None:
    """Verify cross-critique dispatch and subsequent rebuttal response."""
    pipeline.create_session("sess-critique", "Microservices vs Modular Monolith")
    prop = CouncilProposal(
        proposal_id="prop-mono",
        member_id="dev-01",
        model_name="DeepSeek-R1",
        title="Modular Monolith with Hexagonal Boundaries",
        confidence_score=0.90,
    )
    pipeline.submit_proposal("sess-critique", prop)

    # Advance to cross critique phase
    pipeline.advance_phase("sess-critique", DeliberationPhase.CROSS_CRITIQUE)
    session = pipeline.get_session("sess-critique")
    assert session is not None
    assert session.phase == DeliberationPhase.CROSS_CRITIQUE

    critique = CritiqueItem(
        critique_id="crit-01",
        source_member_id="dev-02",
        target_member_id="dev-01",
        target_proposal_id="prop-mono",
        critique_points=["Deployment blast radius is too large for 100+ developers."],
        severity=CritiqueSeverity.HIGH,
    )
    pipeline.submit_critique("sess-critique", critique)
    assert len(session.critiques) == 1

    # Advance to rebuttal
    pipeline.advance_phase("sess-critique", DeliberationPhase.REBUTTAL)
    assert session.phase == DeliberationPhase.REBUTTAL

    pipeline.submit_rebuttal(
        "sess-critique",
        "crit-01",
        "Isolated CI/CD sub-tree pipelines mitigate blast radius effectively.",
    )
    assert session.critiques[0].defense_rebuttal is not None
    assert "Isolated CI/CD" in (session.critiques[0].defense_rebuttal or "")


def test_council_pipeline_consensus_synthesis(pipeline: CouncilDeliberationPipeline) -> None:
    """Verify automatic consensus synthesis when advancing to synthesis phase."""
    pipeline.create_session("sess-consensus", "API Gateway Architecture")
    p1 = CouncilProposal(
        proposal_id="p-envoy",
        member_id="m1",
        model_name="Claude-3.5-Sonnet",
        title="Envoy Gateway with Kubernetes Operator",
        key_arguments=["Native k8s Gateway API support", "Dynamic Lua/Wasm filters"],
        confidence_score=0.95,
    )
    p2 = CouncilProposal(
        proposal_id="p-traefik",
        member_id="m2",
        model_name="GPT-4o",
        title="Traefik Mesh Router",
        key_arguments=["Simpler configuration", "Lightweight edge routing"],
        confidence_score=0.82,
    )
    pipeline.submit_proposal("sess-consensus", p1)
    pipeline.submit_proposal("sess-consensus", p2)

    # Advance automatically through phases to consensus synthesis
    pipeline.advance_phase("sess-consensus", DeliberationPhase.CONSENSUS_SYNTHESIS)
    session = pipeline.get_session("sess-consensus")
    assert session is not None
    assert session.phase == DeliberationPhase.CONSENSUS_SYNTHESIS
    assert session.consensus is not None
    verdict = session.consensus

    assert "Envoy Gateway" in verdict.final_decision
    assert verdict.confidence_rating > 0.8
    assert "Claude-3.5-Sonnet" in verdict.participating_models
    assert "GPT-4o" in verdict.participating_models
    assert len(verdict.key_tradeoffs) > 0


def test_consensus_synthesizer_zero_proposals() -> None:
    """Verify consensus synthesizer gracefully handles empty proposals."""
    verdict = ConsensusSynthesizer.synthesize("Empty Topic", [], [])
    assert verdict.confidence_rating == 0.0
    assert "zero proposals submitted" in verdict.final_decision
    assert len(verdict.participating_models) == 0


def test_consensus_synthesizer_severity_penalties_and_rebuttal() -> None:
    """Verify critique severity penalties and rebuttal mitigation in consensus ranking."""
    p1 = CouncilProposal(
        proposal_id="prop-1",
        member_id="m1",
        model_name="Model-A",
        title="Proposal 1",
        confidence_score=0.90,
    )
    p2 = CouncilProposal(
        proposal_id="prop-2",
        member_id="m2",
        model_name="Model-B",
        title="Proposal 2",
        confidence_score=0.89,
    )

    # Critique with BLOCKER on prop-1 without rebuttal
    c1 = CritiqueItem(
        critique_id="c1",
        source_member_id="m2",
        target_member_id="m1",
        target_proposal_id="prop-1",
        severity=CritiqueSeverity.BLOCKER,
        defense_rebuttal=None,
    )
    # Critique on prop-2 with defense rebuttal (penalty halved)
    c2 = CritiqueItem(
        critique_id="c2",
        source_member_id="m1",
        target_member_id="m2",
        target_proposal_id="prop-2",
        severity=CritiqueSeverity.MEDIUM,
        defense_rebuttal="Valid defense points",
    )

    verdict = ConsensusSynthesizer.synthesize(
        "Architecture arbitration",
        [p1, p2],
        [c1, c2],
    )

    # Proposal 2 should win because Proposal 1 suffered unrefuted BLOCKER penalty
    assert "Proposal 2" in verdict.final_decision
    assert len(verdict.dissenting_opinions) > 0


def test_council_pipeline_unknown_session_keyerror(pipeline: CouncilDeliberationPipeline) -> None:
    """Verify KeyError when querying operations on non-existent session."""
    with pytest.raises(KeyError, match="not found"):
        pipeline.submit_proposal(
            "unknown-sess",
            CouncilProposal("p", "m", "model", "title"),
        )

    with pytest.raises(KeyError, match="not found"):
        pipeline.advance_phase("unknown-sess")
