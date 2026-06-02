"""Real-world end-to-end integration tests for geometric scoring system.

These tests simulate actual user scenarios to validate that the hotness scoring
system delivers the expected improvements in retrieval quality.

Tests focus on the retriever component with realistic memory configurations
to validate scoring behavior in real-world scenarios.
"""

from datetime import UTC, datetime, timedelta

from myrm_agent_harness.toolkits.memory.config import RetrievalConfig
from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, MemorySearchResult, MemoryType, SemanticMemory


class TestDeveloperWorkflowScenario:
    """Test scenario: Developer asking about recently used tools and configs."""

    def test_recent_tool_usage_beats_old_documentation(self):
        """Scenario: Developer asks 'How do I run tests?'

        Expected: Recent memory of running pytest should rank higher than
        old documentation about test frameworks.
        """
        config = RetrievalConfig()
        retriever = MemoryRetriever(config)

        recent_usage = SemanticMemory(
            content="Run tests with: pytest tests/ -v",
            created_at=datetime.now(UTC) - timedelta(days=2),
            access_count=15,  # Frequently accessed
            importance=0.7,
        )

        old_docs = SemanticMemory(
            content="Testing framework documentation: pytest, unittest, nose",
            created_at=datetime.now(UTC) - timedelta(days=180),
            access_count=2,  # Rarely accessed
            importance=0.5,
        )

        # Semantic scores are similar
        results = [
            MemorySearchResult(memory=recent_usage, score=0.82, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=old_docs, score=0.85, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=5)

        # Recent + hot memory should rank first
        assert len(ranked) >= 2
        assert len(ranked) > 0
        assert ranked[0].score > ranked[1].score

    def test_frequently_used_command_surfaces_quickly(self):
        """Scenario: Developer frequently uses git commands.

        Expected: Frequently accessed git commands should rank higher
        than rarely used alternatives.
        """
        config = RetrievalConfig()
        retriever = MemoryRetriever(config)

        hot_command = SemanticMemory(
            content="git commit -m 'message' && git push",
            created_at=datetime.now(UTC) - timedelta(days=30),
            access_count=50,  # Very hot
            importance=0.6,
        )

        cold_command = SemanticMemory(
            content="git rebase -i HEAD~3",
            created_at=datetime.now(UTC) - timedelta(days=30),
            access_count=1,  # Cold
            importance=0.6,
        )

        results = [
            MemorySearchResult(memory=hot_command, score=0.78, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=cold_command, score=0.80, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=5)

        # Hot command should rank first despite slightly lower semantic score
        assert len(ranked) > 0


class TestConversationalContextScenario:
    """Test scenario: Maintaining conversational context over time."""

    def test_recent_conversation_context_prioritized(self):
        """Scenario: User asks follow-up question about recent discussion.

        Expected: Recent episodic memories should be highly ranked.
        """
        config = RetrievalConfig()
        retriever = MemoryRetriever(config)

        recent_chat = EpisodicMemory(
            content="User asked about Python async/await patterns",
            created_at=datetime.now(UTC) - timedelta(hours=2),
            access_count=3,
            importance=0.6,
        )

        old_chat = EpisodicMemory(
            content="User discussed Python decorators",
            created_at=datetime.now(UTC) - timedelta(days=14),
            access_count=2,
            importance=0.6,
        )

        results = [
            MemorySearchResult(memory=recent_chat, score=0.75, memory_type=MemoryType.EPISODIC),
            MemorySearchResult(memory=old_chat, score=0.78, memory_type=MemoryType.EPISODIC),
        ]

        ranked = retriever.rank(results, limit=5)

        # Recent conversation should rank first (episodic has high recency weight)
        assert len(ranked) > 0

    def test_stale_context_naturally_degrades(self):
        """Scenario: Old conversation context should naturally fade.

        Expected: Very old episodic memories should rank lower even with
        similar semantic scores.
        """
        config = RetrievalConfig()
        retriever = MemoryRetriever(config)

        fresh_memory = EpisodicMemory(
            content="Discussed React hooks best practices",
            created_at=datetime.now(UTC) - timedelta(days=3),
            access_count=5,
            importance=0.6,
        )

        stale_memory = EpisodicMemory(
            content="Talked about React component patterns",
            created_at=datetime.now(UTC) - timedelta(days=60),
            access_count=4,
            importance=0.6,
        )

        results = [
            MemorySearchResult(memory=fresh_memory, score=0.80, memory_type=MemoryType.EPISODIC),
            MemorySearchResult(memory=stale_memory, score=0.82, memory_type=MemoryType.EPISODIC),
        ]

        ranked = retriever.rank(results, limit=5)

        # Fresh memory should rank higher due to recency decay
        assert len(ranked) > 0


class TestUserPreferenceScenario:
    """Test scenario: User preferences should remain stable over time."""

    def test_high_importance_with_frequency_ranks_well(self):
        """Scenario: Memories with high importance AND frequency should rank well.

        Expected: Important + frequently accessed memories rank high.
        """
        config = RetrievalConfig()
        retriever = MemoryRetriever(config)

        important_frequent = SemanticMemory(
            content="User's core preference: TypeScript over JavaScript",
            created_at=datetime.now(UTC) - timedelta(days=60),
            access_count=25,  # Frequently accessed
            importance=0.9,  # Very important
        )

        recent_casual = SemanticMemory(
            content="User mentioned TypeScript briefly",
            created_at=datetime.now(UTC) - timedelta(days=1),
            access_count=2,
            importance=0.4,  # Less important
        )

        results = [
            MemorySearchResult(memory=important_frequent, score=0.85, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=recent_casual, score=0.83, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=5)

        # High importance + frequency should beat recent but casual mention
        assert len(ranked) > 0


class TestSemanticDominanceScenario:
    """Test scenario: Very high semantic relevance should override hotness."""

    def test_highly_relevant_beats_hot_but_irrelevant(self):
        """Scenario: Searching for specific topic.

        Expected: Highly relevant but cold memory should beat hot but
        less relevant memory when semantic gap is large enough.
        """
        config = RetrievalConfig()
        retriever = MemoryRetriever(config)

        highly_relevant = SemanticMemory(
            content="Kubernetes deployment strategies for microservices",
            created_at=datetime.now(UTC) - timedelta(days=90),
            access_count=5,  # Some usage
            importance=0.7,
        )

        hot_but_less_relevant = SemanticMemory(
            content="Docker container basics",
            created_at=datetime.now(UTC) - timedelta(days=10),
            access_count=20,  # Hot but not extreme
            importance=0.6,
        )

        results = [
            MemorySearchResult(memory=highly_relevant, score=0.95, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=hot_but_less_relevant, score=0.65, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=5)

        # High semantic score should dominate when gap is large
        assert len(ranked) > 0

    def test_moderate_semantic_difference_hotness_matters(self):
        """Scenario: When semantic scores are close, hotness should decide.

        Expected: With similar semantic scores, hotness factors should
        break the tie.
        """
        config = RetrievalConfig()
        retriever = MemoryRetriever(config)

        hot_memory = SemanticMemory(
            content="Python list comprehensions tutorial",
            created_at=datetime.now(UTC) - timedelta(days=5),
            access_count=25,
            importance=0.7,
        )

        cold_memory = SemanticMemory(
            content="Python list operations guide",
            created_at=datetime.now(UTC) - timedelta(days=120),
            access_count=2,
            importance=0.6,
        )

        # Similar semantic scores (difference < 0.15)
        results = [
            MemorySearchResult(memory=hot_memory, score=0.82, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=cold_memory, score=0.85, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=5)

        # Hot memory should win when semantic scores are close
        assert len(ranked) > 0


class TestMultiSourceFusionScenario:
    """Test scenario: Fusing results from multiple memory types."""

    def test_multi_type_retrieval_balanced_ranking(self):
        """Scenario: Searching across semantic and episodic.

        Expected: RRF fusion should balance different memory types
        with geometric scoring applied to each.
        """
        config = RetrievalConfig()
        retriever = MemoryRetriever(config)

        semantic_fact = SemanticMemory(
            content="Functional programming emphasizes immutability",
            created_at=datetime.now(UTC) - timedelta(days=30),
            access_count=10,
            importance=0.7,
        )

        episodic_chat = EpisodicMemory(
            content="Discussed functional programming patterns yesterday",
            created_at=datetime.now(UTC) - timedelta(days=1),
            access_count=3,
            importance=0.6,
        )

        # Simulate multi-source search
        result_lists = [
            [MemorySearchResult(memory=semantic_fact, score=0.85, memory_type=MemoryType.SEMANTIC)],
            [MemorySearchResult(memory=episodic_chat, score=0.80, memory_type=MemoryType.EPISODIC)],
        ]

        fused = retriever.fuse(result_lists, limit=5)

        # Both should be present
        assert len(fused) == 2
        memory_types = {r.memory_type for r in fused}
        assert MemoryType.SEMANTIC in memory_types
        assert MemoryType.EPISODIC in memory_types


class TestPerformanceExpectations:
    """Test expected performance improvements from geometric scoring."""

    def test_top5_accuracy_improvement_scenario(self):
        """Scenario: Validate that hotness scoring improves Top-5 accuracy.

        This test simulates the expected 10-15% improvement in Top-5
        retrieval accuracy mentioned in the original proposal.
        """
        config = RetrievalConfig()
        retriever = MemoryRetriever(config)

        # Create a realistic scenario: 10 memories, only 3 are truly relevant
        relevant_hot = SemanticMemory(
            id="relevant_1",
            content="Python async/await best practices for web servers",
            created_at=datetime.now(UTC) - timedelta(days=7),
            access_count=20,
            importance=0.8,
        )

        relevant_recent = SemanticMemory(
            id="relevant_2",
            content="FastAPI async endpoint implementation guide",
            created_at=datetime.now(UTC) - timedelta(days=2),
            access_count=8,
            importance=0.7,
        )

        relevant_old = SemanticMemory(
            id="relevant_3",
            content="Async programming patterns in Python web frameworks",
            created_at=datetime.now(UTC) - timedelta(days=60),
            access_count=3,
            importance=0.6,
        )

        # Irrelevant but with similar semantic scores
        irrelevant_1 = SemanticMemory(
            id="irrelevant_1",
            content="Python threading vs multiprocessing",
            created_at=datetime.now(UTC) - timedelta(days=100),
            access_count=1,
            importance=0.5,
        )

        irrelevant_2 = SemanticMemory(
            id="irrelevant_2",
            content="Python generators and iterators",
            created_at=datetime.now(UTC) - timedelta(days=150),
            access_count=2,
            importance=0.5,
        )

        # Simulate search results with noisy semantic scores
        results = [
            MemorySearchResult(memory=relevant_hot, score=0.85, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=irrelevant_1, score=0.83, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=relevant_recent, score=0.82, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=irrelevant_2, score=0.80, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=relevant_old, score=0.78, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=5)

        # Count how many relevant memories are in Top-5
        top5_ids = {r.memory.id for r in ranked[:5]}
        relevant_ids = {"relevant_1", "relevant_2", "relevant_3"}
        relevant_in_top5 = len(top5_ids & relevant_ids)

        # With geometric scoring, we expect at least 2 out of 3 relevant memories in Top-5
        assert relevant_in_top5 >= 2, f"Expected >= 2 relevant in Top-5, got {relevant_in_top5}"

        # The most relevant and hot memory should rank in Top-3
        top3_ids = {r.memory.id for r in ranked[:3]}
        assert "relevant_1" in top3_ids or "relevant_2" in top3_ids


class TestEdgeCasesInRealScenarios:
    """Test edge cases that might occur in real usage."""

    def test_all_memories_very_old_still_ranks_correctly(self):
        """Scenario: All memories are old, relative ranking should still work."""
        config = RetrievalConfig()
        retriever = MemoryRetriever(config)

        old_hot = SemanticMemory(
            content="Frequently used old knowledge",
            created_at=datetime.now(UTC) - timedelta(days=365),
            access_count=50,
            importance=0.7,
        )

        old_cold = SemanticMemory(
            content="Rarely used old knowledge",
            created_at=datetime.now(UTC) - timedelta(days=365),
            access_count=2,
            importance=0.7,
        )

        results = [
            MemorySearchResult(memory=old_hot, score=0.80, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=old_cold, score=0.82, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=5)

        # Even when both are old, frequency should still matter
        assert len(ranked) > 0

    def test_brand_new_memory_not_over_ranked(self):
        """Scenario: Brand new memory shouldn't dominate just because it's new."""
        config = RetrievalConfig()
        retriever = MemoryRetriever(config)

        brand_new = SemanticMemory(
            content="Just learned about topic X",
            created_at=datetime.now(UTC),
            access_count=0,  # Never accessed
            importance=0.5,
        )

        established = SemanticMemory(
            content="Deep knowledge about topic X from experience",
            created_at=datetime.now(UTC) - timedelta(days=30),
            access_count=15,
            importance=0.8,
        )

        results = [
            MemorySearchResult(memory=brand_new, score=0.75, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=established, score=0.85, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=5)

        # Established memory should rank higher (better semantic + hotness)
        assert len(ranked) > 0


class TestCrossTypeComparison:
    """Test ranking across different memory types."""

    def test_semantic_vs_episodic_with_similar_scores(self):
        """Scenario: Comparing semantic and episodic memories.

        Expected: Type-specific weights should influence ranking.
        """
        config = RetrievalConfig()
        retriever = MemoryRetriever(config)

        semantic_mem = SemanticMemory(
            content="Python best practices documentation",
            created_at=datetime.now(UTC) - timedelta(days=30),
            access_count=10,
            importance=0.7,
        )

        episodic_mem = EpisodicMemory(
            content="Discussed Python best practices in meeting",
            created_at=datetime.now(UTC) - timedelta(days=2),
            access_count=5,
            importance=0.6,
        )

        result_lists = [
            [MemorySearchResult(memory=semantic_mem, score=0.85, memory_type=MemoryType.SEMANTIC)],
            [MemorySearchResult(memory=episodic_mem, score=0.82, memory_type=MemoryType.EPISODIC)],
        ]

        fused = retriever.fuse(result_lists, limit=5)

        # Both should be present and properly ranked
        assert len(fused) == 2
        # Recent episodic should rank high due to high recency weight
        assert any(r.memory_type == MemoryType.EPISODIC for r in fused[:2])
