"""Unit tests for Conclusion Attribution and Chat Evidence Suite (Item 141).

Tests cycle detection, bidirectional graph traversal, ripple impact calculation,
cascade deletion safety, and runtime chat evidence packaging.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.conclusion_attribution import (
    AttributedConclusion,
    AttributionGraphEngine,
    AttributionLevel,
    ConclusionAttributionSuite,
    EvidenceCollector,
)


def test_explicit_conclusion_creation() -> None:
    """Verify creating a basic explicit fact extracted from conversation."""
    suite = ConclusionAttributionSuite()
    conc = suite.create_conclusion(
        peer_id="alice",
        content="Alice prefers small pull requests with under 200 lines of code.",
        level=AttributionLevel.EXPLICIT,
        session_id="sess_001",
        confidence=0.95,
    )

    assert conc.id.startswith("conc_")
    assert conc.peer_id == "alice"
    assert conc.level == AttributionLevel.EXPLICIT
    assert conc.source_ids == []
    assert conc.times_derived == 1
    assert conc.confidence == 0.95


def test_derived_conclusion_and_premise_tracking() -> None:
    """Verify deductive derivation and premise usage updates."""
    suite = ConclusionAttributionSuite()
    p1 = suite.create_conclusion(
        peer_id="alice",
        content="Alice writes TypeScript with strict mode enabled.",
        level=AttributionLevel.EXPLICIT,
    )
    p2 = suite.create_conclusion(
        peer_id="alice",
        content="Alice dislikes using any type annotations.",
        level=AttributionLevel.EXPLICIT,
    )

    # Derived rule
    derived = suite.create_conclusion(
        peer_id="alice",
        content="Code reviews for Alice must strictly check for explicit type definitions.",
        level=AttributionLevel.DEDUCTIVE,
        source_ids=[p1.id, p2.id],
    )

    assert derived.level == AttributionLevel.DEDUCTIVE
    assert derived.source_ids == [p1.id, p2.id]

    # Verify premise times_derived got bumped
    refreshed_p1 = suite.get_conclusion(p1.id)
    assert refreshed_p1 is not None
    assert refreshed_p1.times_derived == 2


def test_cycle_detection_guard() -> None:
    """Verify cycle detection prevents circular premise reasoning."""
    suite = ConclusionAttributionSuite()
    a = suite.create_conclusion(peer_id="alice", content="Premise A")
    b = suite.create_conclusion(
        peer_id="alice",
        content="Premise B",
        level=AttributionLevel.DEDUCTIVE,
        source_ids=[a.id],
    )

    # Direct manual check on engine
    is_cycle = AttributionGraphEngine.detect_cycles(a.id, [b.id], suite._store)
    assert is_cycle is True

    # Linking B back to A should fail if attempted
    fake_store: dict[str, AttributedConclusion] = {
        "A": AttributedConclusion(
            id="A",
            peer_id="p",
            content="A",
            source_ids=["B"],
            created_at="now",
        ),
        "B": AttributedConclusion(
            id="B",
            peer_id="p",
            content="B",
            source_ids=["C"],
            created_at="now",
        ),
        "C": AttributedConclusion(
            id="C",
            peer_id="p",
            content="C",
            source_ids=[],
            created_at="now",
        ),
    }
    # Connecting C -> A creates A -> B -> C -> A
    assert AttributionGraphEngine.detect_cycles("C", ["A"], fake_store) is True
    # Connecting C -> D is clean
    assert AttributionGraphEngine.detect_cycles("C", ["D"], fake_store) is False


def test_bidirectional_traversal_downward_and_upward() -> None:
    """Verify walking downward to premises and upward to derived conclusions."""
    suite = ConclusionAttributionSuite()
    # Level 0 (explicit roots)
    r1 = suite.create_conclusion(peer_id="u1", content="Root 1")
    r2 = suite.create_conclusion(peer_id="u1", content="Root 2")

    # Level 1
    m1 = suite.create_conclusion(
        peer_id="u1",
        content="Intermediate 1",
        level=AttributionLevel.DEDUCTIVE,
        source_ids=[r1.id, r2.id],
    )

    # Level 2
    top = suite.create_conclusion(
        peer_id="u1",
        content="Top conclusion",
        level=AttributionLevel.INDUCTIVE,
        source_ids=[m1.id],
    )

    # Downward traversal from top should reach m1, r1, r2
    down_nodes = suite.walk_downward(top.id)
    down_ids = [n.conclusion.id for n in down_nodes]
    assert down_ids[0] == top.id
    assert m1.id in down_ids
    assert r1.id in down_ids
    assert r2.id in down_ids

    # Upward traversal from r1 should reach m1 and top
    up_nodes = suite.walk_upward(r1.id)
    up_ids = [n.conclusion.id for n in up_nodes]
    assert up_ids[0] == r1.id
    assert m1.id in up_ids
    assert top.id in up_ids


def test_ripple_impact_assessment() -> None:
    """Verify assessing consequences of modifying or deleting a premise."""
    suite = ConclusionAttributionSuite()
    root = suite.create_conclusion(peer_id="u1", content="Core premise")
    d1 = suite.create_conclusion(
        peer_id="u1",
        content="Derived 1",
        level=AttributionLevel.DEDUCTIVE,
        source_ids=[root.id],
    )
    d2 = suite.create_conclusion(
        peer_id="u1",
        content="Derived 2",
        level=AttributionLevel.DEDUCTIVE,
        source_ids=[root.id],
    )
    d3 = suite.create_conclusion(
        peer_id="u1",
        content="Derived 3 (sub-child)",
        level=AttributionLevel.INDUCTIVE,
        source_ids=[d1.id],
    )

    impact = suite.get_ripple_impact(root.id)
    assert impact.target_conclusion_id == root.id
    assert len(impact.impacted_conclusion_ids) == 3
    assert d1.id in impact.impacted_conclusion_ids
    assert d2.id in impact.impacted_conclusion_ids
    assert d3.id in impact.impacted_conclusion_ids
    assert impact.severity == "high"


def test_cascade_and_non_cascade_deletion() -> None:
    """Verify non-cascade cleans source_ids while cascade cleans subtrees."""
    suite = ConclusionAttributionSuite()
    root = suite.create_conclusion(peer_id="u1", content="Root")
    child = suite.create_conclusion(
        peer_id="u1",
        content="Child",
        level=AttributionLevel.DEDUCTIVE,
        source_ids=[root.id],
    )

    # 1. Non-cascade delete of root
    deleted = suite.delete_conclusion(root.id, cascade=False)
    assert deleted == [root.id]
    assert suite.get_conclusion(root.id) is None
    # Child still exists but root is removed from its sources
    child_refreshed = suite.get_conclusion(child.id)
    assert child_refreshed is not None
    assert root.id not in child_refreshed.source_ids

    # 2. Cascade delete
    r2 = suite.create_conclusion(peer_id="u1", content="Root 2")
    c2 = suite.create_conclusion(
        peer_id="u1",
        content="Child 2",
        level=AttributionLevel.DEDUCTIVE,
        source_ids=[r2.id],
    )
    c3 = suite.create_conclusion(
        peer_id="u1",
        content="Grandchild 2",
        level=AttributionLevel.DEDUCTIVE,
        source_ids=[c2.id],
    )

    deleted_cascade = suite.delete_conclusion(r2.id, cascade=True)
    assert r2.id in deleted_cascade
    assert c2.id in deleted_cascade
    assert c3.id in deleted_cascade
    assert suite.get_conclusion(c3.id) is None


def test_runtime_evidence_collection() -> None:
    """Verify runtime evidence collector assembling audit-ready packages."""
    collector = EvidenceCollector(session_id="sess_xyz")
    collector.set_trace_id("trace_1234")

    c = AttributedConclusion(
        id="c_1",
        peer_id="alice",
        content="Prefers pnpm over npm",
        level=AttributionLevel.EXPLICIT,
        created_at="2026-10-08T00:00:00Z",
    )
    collector.record_conclusion_access(c)
    collector.record_message_reference(
        message_id="m_100",
        session_id="sess_xyz",
        snippet="Please always use pnpm in our repo",
        role="user",
    )
    collector.record_tool_call(
        tool_name="package_manager_detect",
        tool_input={"cwd": "/app"},
        tool_output_snippet="pnpm-lock.yaml detected",
    )

    evidence = collector.assemble()
    assert len(evidence.conclusions) == 1
    assert evidence.conclusions[0].content == "Prefers pnpm over npm"
    assert len(evidence.messages) == 1
    assert evidence.messages[0].message_id == "m_100"
    assert len(evidence.tool_calls) == 1
    assert evidence.reasoning_trace_id == "trace_1234"


def test_evidence_package_generation_and_metrics() -> None:
    """Verify facade package builder and global attribution metrics."""
    suite = ConclusionAttributionSuite()
    suite.create_conclusion(
        peer_id="alice",
        content="FastAPI is our primary web framework.",
        level=AttributionLevel.EXPLICIT,
    )
    suite.create_conclusion(
        peer_id="alice",
        content="Pydantic V2 must be strictly used.",
        level=AttributionLevel.EXPLICIT,
    )

    pkg = suite.create_evidence_package(
        query="FastAPI framework",
        peer_id="alice",
        session_id="sess_mock",
    )
    assert len(pkg.conclusions) >= 1
    assert any("FastAPI" in it.content for it in pkg.conclusions)
    assert len(pkg.tool_calls) == 1

    metrics = suite.get_metrics("alice")
    assert metrics.total_conclusions == 2
    assert metrics.explicit_count == 2
    assert metrics.deductive_count == 0
    assert metrics.average_times_derived == 1.0
