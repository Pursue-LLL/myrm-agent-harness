"""Unit tests for Full-Lifecycle Memory Attribution and Explainable Traceability Matrix."""

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.memory.attribution import (
    AttributionHealthMatrixEvaluator,
    CandidateRecallItem,
    DiscardedRecallItem,
    FilterDiscardReason,
    InjectedContextItem,
    MemoryLifecycleTracer,
    ModelCitationItem,
)


@pytest.fixture
def tracer() -> MemoryLifecycleTracer:
    """Fixture providing an active memory lifecycle tracer."""
    return MemoryLifecycleTracer()


def test_single_trace_lifecycle_flow(tracer: MemoryLifecycleTracer) -> None:
    """Test recording the complete single-trace lifecycle from recall to final output citation."""
    session_id = "session-task-42"
    query = "How to configure PostgreSQL connection pooling?"
    now = datetime.now(UTC)

    # 1. Start trace
    trace_id = tracer.start_trace(session_id, query)
    assert trace_id.startswith("trace-")
    assert tracer.total_traces == 1

    # 2. Record retrieved candidates
    candidates = [
        CandidateRecallItem(
            memory_id="mem-pg-pool-1",
            score=0.92,
            content_preview="Use PgBouncer transaction mode for connection pooling.",
            source_namespace="tech_docs",
            retrieved_at=now,
        ),
        CandidateRecallItem(
            memory_id="mem-pg-pool-old",
            score=0.75,
            content_preview="Legacy Postgres 9.6 connection settings.",
            source_namespace="tech_docs",
            retrieved_at=now,
        ),
        CandidateRecallItem(
            memory_id="mem-unrelated",
            score=0.35,
            content_preview="Redis cluster failover guide.",
            source_namespace="cache_docs",
            retrieved_at=now,
        ),
    ]
    tracer.record_candidates(trace_id, candidates)

    # 3. Record discarded candidates with explicit reasons
    discarded = [
        DiscardedRecallItem(
            memory_id="mem-pg-pool-old",
            discard_reason=FilterDiscardReason.EXPIRED,
            rationale="Postgres 9.6 is obsolete; filtered by temporal validity engine.",
            stage="temporal_filter",
        ),
        DiscardedRecallItem(
            memory_id="mem-unrelated",
            discard_reason=FilterDiscardReason.LOW_RELEVANCE,
            rationale="Similarity score 0.35 is below cutoff 0.60.",
            stage="score_filter",
        ),
    ]
    tracer.record_discarded(trace_id, discarded)

    # 4. Record injected memories into prompt context
    injections = [
        InjectedContextItem(
            memory_id="mem-pg-pool-1",
            token_count=45,
            position_index=0,
            formatted_preview="[Fact #1] PgBouncer transaction mode connection pooling.",
        )
    ]
    tracer.record_injections(trace_id, injections)

    # 5. Record model citations
    citations = [
        ModelCitationItem(
            memory_id="mem-pg-pool-1",
            confidence=0.98,
            citation_snippet="It is recommended to deploy PgBouncer in transaction mode.",
            supported_fact="PgBouncer transaction pooling",
        )
    ]
    tracer.record_citations(trace_id, citations)

    # 6. Finalize trace
    finalized = tracer.finalize_trace(trace_id, duration_ms=18.5)
    assert finalized.is_finalized is True
    assert finalized.duration_ms == 18.5
    assert len(finalized.candidate_recalls) == 3
    assert len(finalized.discarded_items) == 2
    assert len(finalized.prompt_injections) == 1
    assert len(finalized.model_citations) == 1


def test_export_attribution_graph(tracer: MemoryLifecycleTracer) -> None:
    """Test generating a structured attribution graph for UI visualization."""
    now = datetime.now(UTC)
    trace_id = tracer.start_trace("sess-graph", "Show database schema")

    tracer.record_candidates(
        trace_id,
        [
            CandidateRecallItem(
                memory_id="m1",
                score=0.88,
                content_preview="Users table schema",
                source_namespace="db",
                retrieved_at=now,
            )
        ],
    )
    tracer.record_injections(
        trace_id,
        [
            InjectedContextItem(
                memory_id="m1",
                token_count=20,
                position_index=0,
                formatted_preview="Users table definition",
            )
        ],
    )
    tracer.record_citations(
        trace_id,
        [
            ModelCitationItem(
                memory_id="m1",
                confidence=0.95,
                citation_snippet="According to the schema, users table has an id field.",
            )
        ],
    )
    tracer.finalize_trace(trace_id, 12.0)

    # Export graph payload
    graph = tracer.export_attribution_graph(trace_id)
    node_ids = {n.node_id for n in graph.nodes}
    node_types = {n.node_type for n in graph.nodes}

    assert f"node-query-{trace_id}" in node_ids
    assert "node-cand-m1" in node_ids
    assert "node-inj-m1" in node_ids
    assert "node-cite-m1" in node_ids
    assert node_types == {"query", "candidate", "injected", "cited"}

    # Verify edge connectivity
    relations = {e.relation for e in graph.edges}
    assert "recalled" in relations
    assert "injected_into_prompt" in relations
    assert "cited_in_response" in relations


def test_revocation_and_trace_audit(tracer: MemoryLifecycleTracer) -> None:
    """Test tracing affected outputs when a memory is revoked."""
    trace1 = tracer.start_trace("s1", "Q1")
    tracer.record_citations(
        trace1,
        [ModelCitationItem(memory_id="tainted-mem-1", citation_snippet="bad claim")],
    )
    tracer.finalize_trace(trace1)

    trace2 = tracer.start_trace("s2", "Q2")
    tracer.record_citations(
        trace2,
        [ModelCitationItem(memory_id="clean-mem-2", citation_snippet="good claim")],
    )
    tracer.finalize_trace(trace2)

    # Audit all traces referencing the tainted memory
    affected_traces = tracer.find_traces_citing_memory("tainted-mem-1")
    assert affected_traces == [trace1]

    # Mark revocation
    tracer.mark_memory_revoked("tainted-mem-1", "Deprecating false hallucinated advice.")


def test_attribution_health_matrix_evaluation(tracer: MemoryLifecycleTracer) -> None:
    """Test four-dimensional health evaluation report computation."""
    evaluator = AttributionHealthMatrixEvaluator()

    # Create trace 1: healthy adoption
    t1 = tracer.start_trace("s1", "Query 1")
    tracer.record_candidates(
        t1,
        [
            CandidateRecallItem(
                memory_id="m1",
                score=0.9,
                content_preview="Fact A",
                source_namespace="kb",
                retrieved_at=datetime.now(UTC),
            )
        ],
    )
    tracer.record_injections(
        t1,
        [InjectedContextItem(memory_id="m1", token_count=50, position_index=0, formatted_preview="Fact A")],
    )
    tracer.record_citations(
        t1,
        [ModelCitationItem(memory_id="m1", citation_snippet="Cited Fact A")],
    )
    tracer.finalize_trace(t1)

    # Create trace 2: policy blocked candidate
    t2 = tracer.start_trace("s2", "Query 2")
    tracer.record_candidates(
        t2,
        [
            CandidateRecallItem(
                memory_id="m2_leak",
                score=0.85,
                content_preview="Other tenant secret",
                source_namespace="kb",
                retrieved_at=datetime.now(UTC),
            )
        ],
    )
    tracer.record_discarded(
        t2,
        [
            DiscardedRecallItem(
                memory_id="m2_leak",
                discard_reason=FilterDiscardReason.POLICY_BLOCKED,
                rationale="Cross-tenant isolation block.",
            )
        ],
    )
    tracer.finalize_trace(t2)

    report = evaluator.evaluate_traces(tracer.list_traces())
    assert report.total_traces_analyzed == 2
    assert 0.0 <= report.recall_quality_score <= 1.0
    assert 0.0 <= report.task_outcome_adoption_rate <= 1.0
    assert report.cost_overhead_token_ratio >= 0.0
    assert report.safety_governance_score < 1.0  # Because 1 of 2 candidates was policy_blocked
    assert len(report.recommendations) > 0


def test_empty_traces_matrix_evaluation() -> None:
    """Test graceful fallback when evaluating empty trace batch."""
    evaluator = AttributionHealthMatrixEvaluator()
    report = evaluator.evaluate_traces([])
    assert report.total_traces_analyzed == 0
    assert report.recall_quality_score == 1.0
    assert report.task_outcome_adoption_rate == 1.0


def test_trace_not_found_handling(tracer: MemoryLifecycleTracer) -> None:
    """Invalid trace ID access must raise KeyError."""
    with pytest.raises(KeyError, match="Trace 'unknown-id' not found"):
        tracer.export_attribution_graph("unknown-id")
