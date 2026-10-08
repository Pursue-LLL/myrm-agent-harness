"""Unit tests for GoalDrivenQuadrupleRetrievalAndReasonerSuite (Item 127 P1).

Validates pre-retrieval task goal parsing, quadruple parallel recall (Graph, Vector, Lexical, Metadata),
and Reasoner semantic inference reranking.
"""

from dataclasses import dataclass, field

from myrm_agent_harness.toolkits.memory.quadruple_retrieval import (
    ParsedTaskGoal,
    QuadrupleParallelRetriever,
    QuadrupleRetrievalOrchestrator,
    ReasonerDecisionKind,
    ReasonerReranker,
    RetrievalChannelKind,
    TaskGoalParser,
)


@dataclass
class MockMemoryItem:
    """Mock memory record for quadruple retrieval tests."""

    memory_id: str
    content: str
    subject: str
    predicate: str
    object_value: str
    metadata: dict[str, str] = field(default_factory=dict)


def test_task_goal_parser_intent_and_entity_extraction() -> None:
    """Test extracting technical standard intent and entities from complex query."""
    parser = TaskGoalParser()
    query = '帮我查一下 Python 规范中关于 "Pydantic V2" 的要求'
    goal: ParsedTaskGoal = parser.parse_query(query)

    assert goal.explicit_intent == "technical_standard"
    assert "Pydantic V2" in goal.target_entities
    assert any("pydantic" in kw.lower() or "规范" in kw for kw in goal.extracted_keywords)
    assert goal.metadata_filters.get("category") == "technical_standard"


def test_quadruple_parallel_recall_and_fusion() -> None:
    """Test 4-channel parallel recall execution and RRF-style candidate fusion."""
    retriever = QuadrupleParallelRetriever()
    items = [
        MockMemoryItem(
            memory_id="mem_pydantic_v2",
            content="Project strictly mandates Pydantic V2 frozen models with no Any typing allowed.",
            subject="Tech Stack",
            predicate="schema_validation",
            object_value="Pydantic V2 strict models",
            metadata={"category": "technical_standard", "status": "active"},
        ),
        MockMemoryItem(
            memory_id="mem_coffee_pref",
            content="User prefers iced oat latte in the afternoon.",
            subject="User",
            predicate="prefers_beverage",
            object_value="Iced Oat Latte",
            metadata={"category": "user_preference", "status": "active"},
        ),
        MockMemoryItem(
            memory_id="mem_old_python_v1",
            content="Legacy Python standard allows dictionary types without Pydantic schemas.",
            subject="Tech Stack",
            predicate="schema_validation",
            object_value="Legacy Python",
            metadata={"category": "technical_standard", "status": "superseded"},
        ),
    ]

    goal = ParsedTaskGoal(
        goal_id="goal_test_01",
        original_query="Pydantic V2 schema validation standard",
        explicit_intent="technical_standard",
        target_entities=["Pydantic V2"],
        extracted_keywords=["pydantic", "schema", "standard"],
        metadata_filters={"category": "technical_standard"},
    )

    channel_results, fused = retriever.execute_recall(goal, items, top_k=5)

    assert len(channel_results[RetrievalChannelKind.GRAPH]) >= 1
    assert len(channel_results[RetrievalChannelKind.LEXICAL]) >= 1
    assert len(fused) >= 1

    top_candidate = fused[0]
    assert top_candidate.memory_id == "mem_pydantic_v2"
    # mem_pydantic_v2 hit multiple channels (Graph, Lexical, Metadata)
    assert len(top_candidate.channels_hit) >= 2
    assert top_candidate.fused_score > 1.0


def test_reasoner_reranker_intent_boost_and_stale_penalty() -> None:
    """Test reasoner boosting intent-aligned items and penalizing superseded items."""
    retriever = QuadrupleParallelRetriever()
    reasoner = ReasonerReranker()

    items = [
        MockMemoryItem(
            memory_id="mem_active_rule",
            content="Active coding standard: strictly forbid Any in Pydantic models.",
            subject="Standards",
            predicate="type_safety",
            object_value="Strict Typing",
            metadata={"category": "technical_standard", "status": "active"},
        ),
        MockMemoryItem(
            memory_id="mem_superseded_rule",
            content="Superseded standard: Any typing allowed in Pydantic models.",
            subject="Standards",
            predicate="type_safety",
            object_value="Loose Typing",
            metadata={"category": "technical_standard", "status": "superseded"},
        ),
    ]

    goal = ParsedTaskGoal(
        goal_id="goal_test_02",
        original_query="What is the Pydantic type standard?",
        explicit_intent="technical_standard",
        target_entities=["Pydantic"],
        extracted_keywords=["pydantic", "standard"],
        metadata_filters={"category": "technical_standard"},
    )

    _, fused = retriever.execute_recall(goal, items, top_k=5)
    reranked = reasoner.rerank_candidates(goal, fused, top_k=5)

    assert len(reranked) >= 1
    # Active item should be rank 1 with BOOST decision
    assert reranked[0].memory_id == "mem_active_rule"
    assert reranked[0].reasoner_decision == ReasonerDecisionKind.BOOST

    # Superseded item should have PENALIZE_STALE decision if included
    stale_hits = [h for h in reranked if h.memory_id == "mem_superseded_rule"]
    if stale_hits:
        assert stale_hits[0].reasoner_decision == ReasonerDecisionKind.PENALIZE_STALE


def test_orchestrator_end_to_end_search() -> None:
    """Test full pipeline execution producing comprehensive report."""
    orchestrator = QuadrupleRetrievalOrchestrator()
    items = [
        MockMemoryItem(
            memory_id="mem_1",
            content="User prefers TailwindCSS over CSS modules.",
            subject="UI",
            predicate="prefers_framework",
            object_value="TailwindCSS",
            metadata={"category": "user_preference", "status": "active"},
        ),
        MockMemoryItem(
            memory_id="mem_2",
            content="Backend API convention mandates FastAPI async routers.",
            subject="API",
            predicate="standard",
            object_value="FastAPI",
            metadata={"category": "technical_standard", "status": "active"},
        ),
    ]

    report = orchestrator.search(
        query="帮我查一下用户关于 TailwindCSS 框架的偏好",
        items=items,
        top_k=2,
    )

    assert report.query != ""
    assert report.parsed_goal.explicit_intent == "user_preference"
    assert report.fused_candidates_count >= 1
    assert len(report.final_hits) >= 1
    assert report.final_hits[0].memory_id == "mem_1"
    assert report.latency_ms >= 0.0
    assert "graph" in report.channel_hits_count
    assert "vector" in report.channel_hits_count
    assert "lexical" in report.channel_hits_count
    assert "metadata" in report.channel_hits_count
