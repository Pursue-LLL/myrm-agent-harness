"""Comprehensive test suite for ConclusionEvidenceSuite, causality DAG, and chat evidence."""

import pytest

from myrm_agent_harness.toolkits.memory import (
    AttributedConclusion,
    AttributionLevel,
    ChatEvidenceBundle,
    ChatEvidenceService,
    ConclusionDerivationGraphEngine,
    ConclusionEvidenceStats,
    ConclusionEvidenceSuite,
    DerivationCycleError,
    DerivationTraversalView,
    MessageEvidenceItem,
    ToolCallEvidenceItem,
)


def test_top_level_exports() -> None:
    """Verifies that all components are exported from the top-level memory namespace."""
    assert ConclusionEvidenceSuite is not None
    assert ConclusionDerivationGraphEngine is not None
    assert ChatEvidenceService is not None
    assert AttributedConclusion is not None
    assert AttributionLevel is not None
    assert ChatEvidenceBundle is not None
    assert MessageEvidenceItem is not None
    assert ToolCallEvidenceItem is not None
    assert DerivationTraversalView is not None
    assert ConclusionEvidenceStats is not None
    assert DerivationCycleError is not None


def test_conclusion_attribution_and_cycle_prevention() -> None:
    """Verifies DAG causal derivation registration and cycle rejection."""
    suite = ConclusionEvidenceSuite()

    # C1: Explicit user fact
    c1 = AttributedConclusion(
        conclusion_id="c_01",
        peer_id="alice",
        content="Alice prefers dark mode and concise output",
        level=AttributionLevel.EXPLICIT,
        source_ids=(),
    )
    suite.add_conclusion(c1)

    # C2: Deductive derivation from C1
    c2 = AttributedConclusion(
        conclusion_id="c_02",
        peer_id="alice",
        content="Editor theme should default to obsidian dark",
        level=AttributionLevel.DEDUCTIVE,
        source_ids=("c_01",),
    )
    suite.add_conclusion(c2)

    # C3: Inductive generalization from C2
    c3 = AttributedConclusion(
        conclusion_id="c_03",
        peer_id="alice",
        content="Alice prefers high contrast UI settings across all tools",
        level=AttributionLevel.INDUCTIVE,
        source_ids=("c_02",),
    )
    suite.add_conclusion(c3)

    # Attempt cycle: C4 derived from C3, but then C1 derived from C4
    c4 = AttributedConclusion(
        conclusion_id="c_04",
        peer_id="alice",
        content="Hypothetical cyclic belief",
        level=AttributionLevel.ABDUCTIVE,
        source_ids=("c_03",),
    )
    suite.add_conclusion(c4)

    # Cyclic attempt: adding a node that introduces a path back to an existing ancestor
    cyclic_node = AttributedConclusion(
        conclusion_id="c_cycle",
        peer_id="alice",
        content="Cycle breaker node",
        level=AttributionLevel.CONTRADICTION,
        source_ids=("c_04",),
    )
    suite.add_conclusion(cyclic_node)

    # Attempt self-cycle
    with pytest.raises(DerivationCycleError):
        suite.add_conclusion(
            AttributedConclusion(
                conclusion_id="c_self",
                peer_id="alice",
                content="Self cycle",
                source_ids=("c_self",),
            )
        )


def test_two_way_causal_traversal_and_invalidation() -> None:
    """Verifies two-way graph traversal and cascade invalidation analysis."""
    suite = ConclusionEvidenceSuite()

    suite.add_conclusion(
        AttributedConclusion(
            conclusion_id="node_a",
            peer_id="user_1",
            content="Base premise A",
            level=AttributionLevel.EXPLICIT,
        )
    )
    suite.add_conclusion(
        AttributedConclusion(
            conclusion_id="node_b",
            peer_id="user_1",
            content="Intermediate deduction B",
            level=AttributionLevel.DEDUCTIVE,
            source_ids=("node_a",),
        )
    )
    suite.add_conclusion(
        AttributedConclusion(
            conclusion_id="node_c",
            peer_id="user_1",
            content="Leaf inference C",
            level=AttributionLevel.INDUCTIVE,
            source_ids=("node_b",),
        )
    )

    # Downstream from node_a
    downstream = suite.get_derived_conclusions("node_a")
    downstream_ids = {c.conclusion_id for c in downstream}
    assert downstream_ids == {"node_b", "node_c"}

    # Upstream from node_c
    upstream = suite.get_premise_conclusions("node_c")
    upstream_ids = {c.conclusion_id for c in upstream}
    assert upstream_ids == {"node_a", "node_b"}

    # Cascade invalidation analysis
    cascade_ids = suite.analyze_invalidation_cascade("node_a")
    assert set(cascade_ids) == {"node_b", "node_c"}

    # Two-way view
    view = suite.traverse_two_way("node_b")
    assert len(view.upstream_premises) == 1
    assert view.upstream_premises[0].conclusion_id == "node_a"
    assert len(view.downstream_derivatives) == 1
    assert view.downstream_derivatives[0].conclusion_id == "node_c"


def test_times_derived_increment() -> None:
    """Verifies that re-adding identical conclusion increments times_derived counter."""
    suite = ConclusionEvidenceSuite()
    c = AttributedConclusion(
        conclusion_id="c_repeat",
        peer_id="agent",
        content="Frequent observation",
        level=AttributionLevel.INDUCTIVE,
    )
    first = suite.add_conclusion(c)
    assert first.times_derived == 1

    second = suite.add_conclusion(c)
    assert second.times_derived == 2

    third = suite.add_conclusion(c)
    assert third.times_derived == 3


def test_chat_with_evidence_on_demand_mode() -> None:
    """Verifies on-demand evidence bundle packaging and prompt cache preservation."""
    suite = ConclusionEvidenceSuite()

    # Register message snapshot evidence
    suite.register_message_evidence(
        MessageEvidenceItem(
            message_id="msg_101",
            session_id="session_alpha",
            peer_id="alice",
            content_snippet="Please always use TypeScript with strict types.",
        )
    )

    # Register tool execution evidence
    suite.record_tool_call(
        ToolCallEvidenceItem(
            tool_name="lint_check",
            tool_input={"target": "src/index.ts"},
            tool_output="0 errors found",
        )
    )

    # Register conclusion linking to msg_101
    suite.add_conclusion(
        AttributedConclusion(
            conclusion_id="c_ts_strict",
            peer_id="alice",
            content="Alice mandates strict TypeScript without any types",
            level=AttributionLevel.EXPLICIT,
            evidence_message_ids=("msg_101",),
        )
    )

    # Query without evidence (default: zero token overhead)
    text_plain, bundle_none = suite.chat_with_evidence(
        query="TypeScript strict",
        peer_id="alice",
        include_evidence=False,
    )
    assert "strict TypeScript" in text_plain
    assert bundle_none is None

    # Query with evidence (on-demand audit mode)
    text_audit, bundle_full = suite.chat_with_evidence(
        query="TypeScript strict",
        peer_id="alice",
        include_evidence=True,
    )
    assert "strict TypeScript" in text_audit
    assert bundle_full is not None
    assert len(bundle_full.conclusions) == 1
    assert bundle_full.conclusions[0].conclusion_id == "c_ts_strict"
    assert len(bundle_full.messages) == 1
    assert bundle_full.messages[0].message_id == "msg_101"
    assert "strict types" in bundle_full.messages[0].content_snippet
    assert len(bundle_full.tool_calls) >= 1


def test_graph_stats_and_removal() -> None:
    """Verifies stats counters and clean edge removal."""
    suite = ConclusionEvidenceSuite()
    suite.add_conclusion(
        AttributedConclusion(
            conclusion_id="r1",
            peer_id="p",
            content="Root 1",
            level=AttributionLevel.EXPLICIT,
        )
    )
    suite.add_conclusion(
        AttributedConclusion(
            conclusion_id="d1",
            peer_id="p",
            content="Derived 1",
            level=AttributionLevel.DEDUCTIVE,
            source_ids=("r1",),
        )
    )

    stats = suite.get_stats()
    assert stats.total_conclusions == 2
    assert stats.total_explicit == 1
    assert stats.total_derived == 1
    assert stats.total_edges == 1
    assert stats.max_derivation_depth == 2

    # Remove node
    removed = suite.remove_conclusion("r1")
    assert removed is True
    assert suite.get_conclusion("r1") is None

    # Edge from r1 to d1 should be pruned
    assert len(suite.get_premise_conclusions("d1")) == 0
