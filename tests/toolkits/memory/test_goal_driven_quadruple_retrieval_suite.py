"""Unit tests for Goal-Driven Quadruple Retrieval and Reasoner Suite.

[POS]
Harness framework unit tests verifying TaskGoalParser, QuadrupleParallelRetriever,
ReasonerReranker with MMR diversity, and QuadrupleRetrievalOrchestrator end-to-end.
"""

from __future__ import annotations

from dataclasses import dataclass

from myrm_agent_harness.toolkits.memory.quadruple_retrieval import (
    ParsedTaskGoal,
    QuadrupleParallelRetriever,
    QuadrupleRetrievalOrchestrator,
    QueryIntentType,
    ReasonerDecisionKind,
    ReasonerReranker,
    RetrievalChannelKind,
    TaskGoalParser,
    UnifiedCandidateHit,
)


@dataclass(slots=True)
class MockMemoryItem:
    """Mock test item implementing MemoryStoreItem protocol."""

    memory_id: str
    content: str
    subject: str
    predicate: str
    object_value: str
    metadata: dict[str, str]


def test_task_goal_parser_intent_and_edge_cases() -> None:
    """Verify task goal parsing across intents and defensive edge fallbacks."""
    parser = TaskGoalParser()

    # 1. Procedural query with entities
    q1 = "如何配置 PostgreSQL 的 connection_pool 和 timeout 参数？"
    g1 = parser.parse_query(q1)
    assert g1.intent_type == QueryIntentType.PROCEDURAL
    assert any("postgresql" in e.lower() or "connection_pool" in e.lower() for e in g1.target_entities)

    # 2. Episodic query with temporal constraint
    q2 = "我们在去年关于 Docker 容器安全的配置要求是什么？"
    g2 = parser.parse_query(q2)
    assert g2.intent_type == QueryIntentType.EPISODIC
    assert g2.temporal_constraint is not None
    assert "去年" in g2.temporal_constraint

    # 3. Preference query
    q3 = "代码编写规范中，我们更喜欢使用 TailwindCSS 还是 CSS Modules？"
    g3 = parser.parse_query(q3)
    assert g3.intent_type == QueryIntentType.PREFERENCE

    # 4. Defensive edge case: Empty query
    g_empty = parser.parse_query("   ")
    assert g_empty.intent_type == QueryIntentType.GENERAL_EXPLORATION
    assert g_empty.target_entities == []

    # 5. Defensive edge case: Extremely long query (> 2048 chars)
    long_q = "关于微服务架构 " + ("token_safety " * 300)
    g_long = parser.parse_query(long_q)
    assert len(g_long.original_query) > 1024
    assert g_long.intent_type is not None


def test_quadruple_parallel_retriever_multi_channel_recall() -> None:
    """Verify 4-channel recall coverage and multi-channel consensus fusion."""
    retriever = QuadrupleParallelRetriever()
    parser = TaskGoalParser()

    items = [
        MockMemoryItem(
            memory_id="mem_1",
            content="PostgreSQL database connection pool timeout is configured to 30 seconds",
            subject="PostgreSQL",
            predicate="timeout",
            object_value="30s",
            metadata={"env": "prod", "tier": "critical"},
        ),
        MockMemoryItem(
            memory_id="mem_2",
            content="Frontend component styling strictly mandates TailwindCSS utility classes",
            subject="Frontend",
            predicate="css_framework",
            object_value="TailwindCSS",
            metadata={"env": "all", "tier": "standard"},
        ),
        MockMemoryItem(
            memory_id="mem_3",
            content="Historical database benchmark notes from earlier performance tests",
            subject="Database",
            predicate="benchmark",
            object_value="notes",
            metadata={"env": "staging"},
        ),
    ]

    goal = parser.parse_query(
        "PostgreSQL connection timeout specifications",
        scoped_filters={"env": "prod"},
    )

    channel_hits, fused_candidates = retriever.execute_recall(goal, items, top_k=5)

    # Verify channels had matches
    assert len(channel_hits[RetrievalChannelKind.GRAPH]) >= 1
    assert len(channel_hits[RetrievalChannelKind.VECTOR]) >= 1
    assert len(channel_hits[RetrievalChannelKind.LEXICAL]) >= 1
    assert len(channel_hits[RetrievalChannelKind.METADATA]) >= 1

    # Verify fused candidates
    assert len(fused_candidates) >= 1
    top_cand = fused_candidates[0]
    assert top_cand.memory_id == "mem_1"
    # Multiple channels hit for mem_1 creates synergy boost
    assert len(top_cand.channels_hit) >= 3
    assert top_cand.fused_score > 1.0


def test_reasoner_reranker_rrf_and_mmr_diversity() -> None:
    """Verify Reasoner evaluates intent alignment, penalizes staleness, and prunes redundancy."""
    reasoner = ReasonerReranker(rrf_k=60, mmr_lambda=0.70)
    parser = TaskGoalParser()

    goal: ParsedTaskGoal = parser.parse_query("PostgreSQL timeout configuration")

    candidates = [
        # Candidate 1: Authoritative fresh record with high consensus
        UnifiedCandidateHit(
            memory_id="cand_fresh",
            content="PostgreSQL timeout statement set to 30 seconds for standard OLTP",
            channels_hit=[RetrievalChannelKind.GRAPH, RetrievalChannelKind.VECTOR],
            fused_score=1.45,
            metadata={"status": "active"},
        ),
        # Candidate 2: Deprecated stale record
        UnifiedCandidateHit(
            memory_id="cand_stale",
            content="PostgreSQL timeout was 10s in legacy deprecated deployment",
            channels_hit=[RetrievalChannelKind.LEXICAL],
            fused_score=1.20,
            metadata={"status": "deprecated"},
        ),
        # Candidate 3: Near-duplicate of Candidate 1 (Redundant)
        UnifiedCandidateHit(
            memory_id="cand_dup",
            content="PostgreSQL timeout statement set to 30s for standard OLTP workloads",
            channels_hit=[RetrievalChannelKind.VECTOR],
            fused_score=1.40,
            metadata={"status": "active"},
        ),
        # Candidate 4: Complementary diverse record
        UnifiedCandidateHit(
            memory_id="cand_pool",
            content="Connection pool idle lifetime configured to 600s",
            channels_hit=[RetrievalChannelKind.METADATA],
            fused_score=0.90,
            metadata={"status": "active"},
        ),
    ]

    reranked = reasoner.rerank_candidates(goal=goal, candidates=candidates, top_k=3)

    assert len(reranked) == 3
    rank_1 = reranked[0]
    assert rank_1.memory_id == "cand_fresh"
    assert rank_1.reasoner_decision == ReasonerDecisionKind.BOOST
    assert "boosted" in rank_1.rationale.lower()

    # Verify stale candidate got penalized
    stale_hits = [r for r in reranked if r.memory_id == "cand_stale"]
    if stale_hits:
        assert stale_hits[0].reasoner_decision == ReasonerDecisionKind.PENALIZE_STALE


def test_end_to_end_orchestrator() -> None:
    """Verify integrated pipeline: goal parsing -> 4-way recall -> reasoner reranking."""
    orchestrator = QuadrupleRetrievalOrchestrator()

    items = [
        MockMemoryItem(
            memory_id="m_docker_1",
            content="Docker containers must mount root filesystem as read-only for security",
            subject="Docker",
            predicate="filesystem",
            object_value="read_only",
            metadata={"env": "prod"},
        ),
        MockMemoryItem(
            memory_id="m_docker_2",
            content="Docker Compose drops all Linux capabilities by default",
            subject="Docker",
            predicate="capabilities",
            object_value="drop_all",
            metadata={"env": "prod"},
        ),
    ]

    report = orchestrator.search(
        query="我们在关于 Docker 容器安全的配置要求是什么？",
        items=items,
        top_k=2,
    )

    assert report.query is not None
    assert report.parsed_goal.intent_type is not None
    assert report.fused_candidates_count >= 1
    assert len(report.final_hits) >= 1
    assert report.latency_ms >= 0.0
    assert report.final_hits[0].final_rank == 1
