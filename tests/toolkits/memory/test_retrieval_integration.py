"""Integration test for geometric scoring in real retrieval scenarios."""

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.config import RetrievalConfig
from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemorySearchResult,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
)


class TestRetrievalScenarios:
    """Test real-world retrieval scenarios."""

    def test_recent_config_beats_old_similar_config(self) -> None:
        """Recently used config should rank higher than older one with similar semantic score."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        recent_config = SemanticMemory(
            content="User prefers dark theme in VS Code",
            created_at=datetime.now(UTC) - timedelta(days=1),
            access_count=15,
            importance=0.6,
        )

        old_config = SemanticMemory(
            content="User prefers dark mode in editor",
            created_at=datetime.now(UTC) - timedelta(days=90),
            access_count=3,
            importance=0.6,
        )

        results = [
            MemorySearchResult(memory=recent_config, score=0.82, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=old_config, score=0.85, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=2)

        assert ranked[0].memory.content == "User prefers dark theme in VS Code"
        assert ranked[1].memory.content == "User prefers dark mode in editor"

    def test_highly_relevant_beats_hot_irrelevant(self) -> None:
        """Very high semantic score should beat hot but less relevant memory."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        highly_relevant = SemanticMemory(
            content="Python async best practices",
            created_at=datetime.now(UTC) - timedelta(days=60),
            access_count=2,
            importance=0.5,
        )

        hot_but_less_relevant = SemanticMemory(
            content="JavaScript promises", created_at=datetime.now(UTC), access_count=50, importance=0.9
        )

        results = [
            MemorySearchResult(memory=highly_relevant, score=0.95, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=hot_but_less_relevant, score=0.55, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=2)

        assert ranked[0].memory.content == "Python async best practices"

    def test_episodic_recent_conversation_prioritized(self) -> None:
        """Recent episodic memory should rank higher than old ones."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        recent_convo = EpisodicMemory(
            content="Discussed API design patterns",
            created_at=datetime.now(UTC) - timedelta(days=2),
            access_count=5,
            importance=0.6,
        )

        old_convo = EpisodicMemory(
            content="Talked about API architecture",
            created_at=datetime.now(UTC) - timedelta(days=30),
            access_count=3,
            importance=0.6,
        )

        results = [
            MemorySearchResult(memory=recent_convo, score=0.75, memory_type=MemoryType.EPISODIC),
            MemorySearchResult(memory=old_convo, score=0.78, memory_type=MemoryType.EPISODIC),
        ]

        ranked = retriever.rank(results, limit=2)

        assert ranked[0].memory.content == "Discussed API design patterns"

    def test_profile_preference_stable_over_time(self) -> None:
        """Profile preferences should not decay over time."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        old_preference = SemanticMemory(
            content="User prefers concise responses",
            created_at=datetime.now(UTC) - timedelta(days=365),
            access_count=0,
            importance=0.7,
            preference_type="explicit",
            preference_strength=0.9,
        )

        result = MemorySearchResult(memory=old_preference, score=0.8, memory_type=MemoryType.PROFILE)

        score = retriever._boost(0.8, result, frozenset())

        assert score > 0.6

    def test_multi_source_fusion(self) -> None:
        """Test RRF fusion with geometric scoring."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        vector_results = [
            MemorySearchResult(
                memory=SemanticMemory(
                    content="Python type hints",
                    created_at=datetime.now(UTC) - timedelta(days=10),
                    access_count=20,
                    importance=0.7,
                ),
                score=0.9,
                memory_type=MemoryType.SEMANTIC,
            ),
            MemorySearchResult(
                memory=SemanticMemory(
                    content="Python typing module",
                    created_at=datetime.now(UTC) - timedelta(days=30),
                    access_count=5,
                    importance=0.6,
                ),
                score=0.75,
                memory_type=MemoryType.SEMANTIC,
            ),
        ]

        bm25_results = [
            MemorySearchResult(
                memory=SemanticMemory(
                    content="Python typing module",
                    created_at=datetime.now(UTC) - timedelta(days=30),
                    access_count=5,
                    importance=0.6,
                ),
                score=0.85,
                memory_type=MemoryType.SEMANTIC,
            ),
            MemorySearchResult(
                memory=SemanticMemory(
                    content="Type annotations in Python",
                    created_at=datetime.now(UTC) - timedelta(days=5),
                    access_count=10,
                    importance=0.5,
                ),
                score=0.7,
                memory_type=MemoryType.SEMANTIC,
            ),
        ]

        fused = retriever.fuse([vector_results, bm25_results], limit=3)

        assert len(fused) == 3
        assert fused[0].score == 1.0


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.parametrize(
        "input_lists,expected_len",
        [
            ([], 0),  # Empty lists
            (
                [
                    [
                        MemorySearchResult(
                            memory=SemanticMemory(content="test", importance=0.5),
                            score=0.8,
                            memory_type=MemoryType.SEMANTIC,
                        )
                    ]
                ],
                1,
            ),  # Single list
        ],
        ids=["empty_lists", "single_list"],
    )
    def test_fuse_edge_cases(self, input_lists, expected_len) -> None:
        """Test fuse method with edge case inputs."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        result = retriever.fuse(input_lists, limit=10)
        assert len(result) == expected_len

    def test_fuse_with_empty_sublists(self) -> None:
        """Fusing with some empty sublists should work."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        mem1 = MemorySearchResult(
            memory=SemanticMemory(content="test1", importance=0.5), score=0.8, memory_type=MemoryType.SEMANTIC
        )
        mem2 = MemorySearchResult(
            memory=SemanticMemory(content="test2", importance=0.6), score=0.7, memory_type=MemoryType.SEMANTIC
        )

        result = retriever.fuse([[mem1], [], [mem2]], limit=10)
        assert len(result) == 2

    def test_suppress_corrected_with_episodic(self) -> None:
        """Correction suppression should only apply to SemanticMemory."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        epi_mem = EpisodicMemory(id="epi-id", content="episodic event", importance=0.8)

        results = [MemorySearchResult(memory=epi_mem, score=0.9, memory_type=MemoryType.EPISODIC)]

        ranked = retriever.rank(results, limit=1)
        assert len(ranked) == 1

    def test_rank_empty_results(self) -> None:
        """Ranking empty results should return empty."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        result = retriever.rank([], limit=10)
        assert result == []

    def test_normalise_with_single_result(self) -> None:
        """Normalising single result should set score to 1.0."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        mem = MemorySearchResult(
            memory=SemanticMemory(content="test", importance=0.5), score=0.5, memory_type=MemoryType.SEMANTIC
        )

        result = retriever.rank([mem], limit=1)
        assert len(result) == 1
        assert result[0].score == 1.0

    def test_fuse_with_duplicate_memories(self) -> None:
        """Fusing duplicate memories should accumulate scores."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        mem = SemanticMemory(id="same-id", content="duplicate", importance=0.5)

        result1 = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)
        result2 = MemorySearchResult(memory=mem, score=0.7, memory_type=MemoryType.SEMANTIC)

        fused = retriever.fuse([[result1], [result2]], limit=10)
        assert len(fused) == 1
        assert fused[0].id == "same-id"

    def test_retriever_with_custom_config(self) -> None:
        """Test retriever initialization with custom config."""
        config = RetrievalConfig(frequency_saturation=100, rrf_k=80)
        retriever = MemoryRetriever(config)

        assert retriever._config.frequency_saturation == 100
        assert retriever._config.rrf_k == 80

    def test_retriever_with_default_config(self) -> None:
        """Test retriever initialization with default config."""
        retriever = MemoryRetriever()

        assert retriever._config.frequency_saturation == 50

    def test_geometric_score_all_memory_types(self) -> None:
        """Test geometric scoring with all memory types."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        profile_mem = SemanticMemory(
            content="profile", importance=0.5, preference_type="explicit", preference_strength=0.8
        )

        episodic_mem = EpisodicMemory(
            content="episodic", created_at=datetime.now(UTC) - timedelta(days=3), access_count=10, importance=0.6
        )

        procedural_mem = ProceduralMemory(
            content="procedural", trigger="when X", action="do Y", access_count=20, priority=1
        )

        results = [
            MemorySearchResult(memory=profile_mem, score=0.8, memory_type=MemoryType.PROFILE),
            MemorySearchResult(memory=episodic_mem, score=0.75, memory_type=MemoryType.EPISODIC),
            MemorySearchResult(memory=procedural_mem, score=0.7, memory_type=MemoryType.PROCEDURAL),
        ]

        for result in results:
            score = retriever._boost(result.score, result, frozenset())
            assert score > 0.0

    def test_fuse_with_all_empty_lists(self) -> None:
        """Fusing all empty lists should return empty."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        result = retriever.fuse([[], [], []], limit=10)
        assert result == []

    def test_correction_chain_with_missing_corrected_id(self) -> None:
        """Correction chain should handle missing corrected ID gracefully."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        corrected_mem = SemanticMemory(
            id="new-id", content="corrected fact", correction_of="non-existent-id", importance=0.9
        )

        results = [MemorySearchResult(memory=corrected_mem, score=0.85, memory_type=MemoryType.SEMANTIC)]

        ranked = retriever.rank(results, limit=1)
        assert len(ranked) == 1
        assert ranked[0].id == "new-id"

    def test_fuse_with_different_type_weights(self) -> None:
        """Test that type_weights are applied correctly in fusion."""
        config = RetrievalConfig(
            type_weights={
                MemoryType.PROFILE: 1.5,
                MemoryType.SEMANTIC: 1.0,
                MemoryType.EPISODIC: 0.5,
                MemoryType.PROCEDURAL: 0.8,
            }
        )
        retriever = MemoryRetriever(config)

        profile_mem = MemorySearchResult(
            memory=SemanticMemory(
                content="profile", importance=0.5, preference_type="explicit", preference_strength=0.8
            ),
            score=0.7,
            memory_type=MemoryType.PROFILE,
        )

        episodic_mem = MemorySearchResult(
            memory=EpisodicMemory(content="episodic", importance=0.5), score=0.7, memory_type=MemoryType.EPISODIC
        )

        fused = retriever.fuse([[profile_mem], [episodic_mem]], limit=2)
        assert len(fused) == 2
        assert fused[0].memory_type == MemoryType.PROFILE

    def test_normalise_with_very_small_scores(self) -> None:
        """Normalise should handle very small scores without division by zero."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        mem = SemanticMemory(
            content="test", created_at=datetime.now(UTC) - timedelta(days=365), access_count=0, importance=0.1
        )
        result = MemorySearchResult(memory=mem, score=0.01, memory_type=MemoryType.SEMANTIC)

        ranked = retriever.rank([result], limit=1)
        assert len(ranked) == 1
        assert ranked[0].score > 0.0

    def test_geometric_score_with_very_high_access_count(self) -> None:
        """Geometric scoring should handle very high access counts."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        mem = SemanticMemory(content="super hot", created_at=datetime.now(UTC), access_count=10000, importance=0.8)

        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)
        score = retriever._boost(0.8, result, frozenset())
        assert 0.0 < score <= 1.0

    def test_correction_chain_in_fuse(self) -> None:
        """Test correction chain suppression in fuse method."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        old_mem = SemanticMemory(id="old-id", content="old fact", importance=0.8)

        corrected_mem = SemanticMemory(id="new-id", content="corrected fact", correction_of="old-id", importance=0.9)

        list1 = [MemorySearchResult(memory=old_mem, score=0.9, memory_type=MemoryType.SEMANTIC)]
        list2 = [MemorySearchResult(memory=corrected_mem, score=0.85, memory_type=MemoryType.SEMANTIC)]

        fused = retriever.fuse([list1, list2], limit=2)

        assert fused[0].id == "new-id"
        assert fused[1].id == "old-id"

    def test_geometric_score_with_zero_confidence(self) -> None:
        """Zero confidence should zero out the final score."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        mem = SemanticMemory(
            content="test", created_at=datetime.now(UTC), access_count=50, importance=1.0, confidence=0.0
        )

        result = MemorySearchResult(memory=mem, score=0.9, memory_type=MemoryType.SEMANTIC)
        score = retriever._boost(0.9, result, frozenset())
        assert score == 0.0

    @pytest.mark.parametrize(
        "method_name,limit",
        [
            ("fuse", 3),
            ("rank", 3),
        ],
        ids=["fuse_with_limit", "rank_with_limit"],
    )
    def test_result_limiting(self, method_name, limit) -> None:
        """Test that fuse and rank methods respect limit parameter."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        memories = [
            MemorySearchResult(
                memory=SemanticMemory(content=f"mem{i}", importance=0.5),
                score=max(0.1, 0.9 - i * 0.04),
                memory_type=MemoryType.SEMANTIC,
            )
            for i in range(10)
        ]

        if method_name == "fuse":
            result = retriever.fuse([memories], limit=limit)
        else:
            result = retriever.rank(memories, limit=limit)

        assert len(result) == limit

    def test_suppress_corrected_with_none_correction_of(self) -> None:
        """Suppress should handle None correction_of gracefully."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        mem = SemanticMemory(id="mem-id", content="normal fact", correction_of=None, importance=0.8)

        results = [MemorySearchResult(memory=mem, score=0.9, memory_type=MemoryType.SEMANTIC)]
        ranked = retriever.rank(results, limit=1)

        assert len(ranked) == 1
        assert ranked[0].id == "mem-id"
