"""Coverage tests for retriever.py edge cases."""

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.config import RetrievalConfig
from myrm_agent_harness.toolkits.memory.query_analyzer import QueryContext
from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever, _jaccard_similarity
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, MemorySearchResult, MemoryType, SemanticMemory


class TestBoostMethod:
    """Test _boost method directly."""

    def test_boost_delegates_to_geometric_score(self) -> None:
        """Test that _boost correctly delegates to _geometric_score + hybrid enhancements."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0)
        retriever = MemoryRetriever(config)

        mem = SemanticMemory(content="test", created_at=datetime.now(UTC), access_count=10, importance=0.7)

        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)

        boost_score = retriever._boost(0.8, result, frozenset())
        geometric_score = retriever._geometric_score(0.8, result)

        assert boost_score == geometric_score

    def test_boost_with_zero_base_score(self) -> None:
        """Test _boost with zero base score."""
        retriever = MemoryRetriever()

        mem = SemanticMemory(content="test", importance=1.0)

        result = MemorySearchResult(memory=mem, score=0.0, memory_type=MemoryType.SEMANTIC)

        score = retriever._boost(0.0, result, frozenset())
        assert score == 0.0

    def test_boost_with_very_low_base_score(self) -> None:
        """Test _boost with very low base score."""
        retriever = MemoryRetriever()

        mem = SemanticMemory(content="test", importance=0.7)

        result = MemorySearchResult(memory=mem, score=0.001, memory_type=MemoryType.SEMANTIC)

        score = retriever._boost(0.001, result, frozenset())
        assert score > 0.0


class TestNormaliseEdgeCases:
    """Test _normalise method edge cases."""

    def test_normalise_empty_scores(self) -> None:
        """Test normalise with empty scores dict."""
        retriever = MemoryRetriever()
        result = retriever._normalise({}, {}, limit=10)
        assert result == []

    def test_normalise_single_very_small_score(self) -> None:
        """Test normalise with single very small score."""
        retriever = MemoryRetriever()

        mem = SemanticMemory(content="test", importance=0.5)
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)

        scores = {"id1": 0.001}
        items = {"id1": result}

        normalized = retriever._normalise(scores, items, limit=10)
        assert len(normalized) == 1
        assert normalized[0].score == 1.0

    def test_normalise_all_same_scores(self) -> None:
        """Test normalise when all scores are identical."""
        retriever = MemoryRetriever()

        mem1 = SemanticMemory(content="test1", importance=0.5)
        mem2 = SemanticMemory(content="test2", importance=0.5)

        result1 = MemorySearchResult(memory=mem1, score=0.8, memory_type=MemoryType.SEMANTIC)
        result2 = MemorySearchResult(memory=mem2, score=0.8, memory_type=MemoryType.SEMANTIC)

        scores = {"id1": 0.5, "id2": 0.5}
        items = {"id1": result1, "id2": result2}

        normalized = retriever._normalise(scores, items, limit=10)
        assert len(normalized) == 2
        assert all(r.score == 1.0 for r in normalized)

    def test_normalise_respects_limit(self) -> None:
        """Test that normalise respects limit parameter."""
        retriever = MemoryRetriever()

        memories = {
            f"id{i}": MemorySearchResult(
                memory=SemanticMemory(content=f"test{i}", importance=0.5), score=0.8, memory_type=MemoryType.SEMANTIC
            )
            for i in range(20)
        }

        scores = {f"id{i}": float(20 - i) for i in range(20)}

        normalized = retriever._normalise(scores, memories, limit=5)
        assert len(normalized) == 5

    def test_normalise_score_clamping(self) -> None:
        """Test that scores are clamped to [0, 1]."""
        retriever = MemoryRetriever()

        mem = SemanticMemory(content="test", importance=0.5)
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)

        scores = {"id1": 100.0}
        items = {"id1": result}

        normalized = retriever._normalise(scores, items, limit=10)
        assert normalized[0].score == 1.0


class TestSuppressCorrectedEdgeCases:
    """Test _suppress_corrected method edge cases."""

    def test_suppress_with_no_corrections(self) -> None:
        """Test suppress when no corrections exist."""
        retriever = MemoryRetriever()

        mem = SemanticMemory(id="mem-id", content="test", importance=0.8)

        result = MemorySearchResult(memory=mem, score=0.9, memory_type=MemoryType.SEMANTIC)

        scores = {"mem-id": 0.9}
        items = {"mem-id": result}

        original_score = scores["mem-id"]
        retriever._suppress_corrected(scores, items)

        assert scores["mem-id"] == original_score

    def test_suppress_with_correction_not_in_scores(self) -> None:
        """Test suppress when corrected memory is not in scores."""
        retriever = MemoryRetriever()

        corrected_mem = SemanticMemory(
            id="new-id", content="corrected", correction_of="old-id-not-present", importance=0.9
        )

        result = MemorySearchResult(memory=corrected_mem, score=0.85, memory_type=MemoryType.SEMANTIC)

        scores = {"new-id": 0.85}
        items = {"new-id": result}

        retriever._suppress_corrected(scores, items)

        assert scores == {"new-id": 0.85}

    def test_suppress_with_non_semantic_memory(self) -> None:
        """Test suppress with non-semantic memory types."""
        retriever = MemoryRetriever()

        episodic_mem = EpisodicMemory(id="epi-id", content="episodic", importance=0.8)

        result = MemorySearchResult(memory=episodic_mem, score=0.9, memory_type=MemoryType.EPISODIC)

        scores = {"epi-id": 0.9}
        items = {"epi-id": result}

        original_score = scores["epi-id"]
        retriever._suppress_corrected(scores, items)

        assert scores["epi-id"] == original_score

    def test_suppress_multiple_corrections(self) -> None:
        """Test suppress with multiple correction chains."""
        retriever = MemoryRetriever()

        old_mem1 = SemanticMemory(id="old1", content="old1", importance=0.8)
        old_mem2 = SemanticMemory(id="old2", content="old2", importance=0.8)
        new_mem1 = SemanticMemory(id="new1", content="new1", correction_of="old1", importance=0.9)
        new_mem2 = SemanticMemory(id="new2", content="new2", correction_of="old2", importance=0.9)

        results = {
            "old1": MemorySearchResult(memory=old_mem1, score=0.9, memory_type=MemoryType.SEMANTIC),
            "old2": MemorySearchResult(memory=old_mem2, score=0.85, memory_type=MemoryType.SEMANTIC),
            "new1": MemorySearchResult(memory=new_mem1, score=0.88, memory_type=MemoryType.SEMANTIC),
            "new2": MemorySearchResult(memory=new_mem2, score=0.87, memory_type=MemoryType.SEMANTIC),
        }

        scores = {"old1": 0.9, "old2": 0.85, "new1": 0.88, "new2": 0.87}

        retriever._suppress_corrected(scores, results)

        assert scores["old1"] == 0.9 * 0.1
        assert scores["old2"] == 0.85 * 0.1
        assert scores["new1"] == 0.88
        assert scores["new2"] == 0.87


class TestFuseEdgeCases:
    """Test fuse method edge cases."""

    def test_fuse_with_unknown_memory_type(self) -> None:
        """Test fuse with memory type not in type_weights."""
        config = RetrievalConfig(
            type_weights={
                MemoryType.PROFILE: 1.0,
                MemoryType.SEMANTIC: 1.0,
            }
        )
        retriever = MemoryRetriever(config)

        mem = EpisodicMemory(content="test", importance=0.5)

        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.EPISODIC)

        fused = retriever.fuse([[result]], limit=10)
        assert len(fused) == 1

    def test_fuse_accumulates_duplicate_ids(self) -> None:
        """Test that fuse accumulates scores for duplicate memory IDs."""
        retriever = MemoryRetriever()

        mem = SemanticMemory(id="same-id", content="test", importance=0.5)

        result1 = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)
        result2 = MemorySearchResult(memory=mem, score=0.7, memory_type=MemoryType.SEMANTIC)
        result3 = MemorySearchResult(memory=mem, score=0.6, memory_type=MemoryType.SEMANTIC)

        fused = retriever.fuse([[result1], [result2], [result3]], limit=10)

        assert len(fused) == 1
        assert fused[0].id == "same-id"

    def test_fuse_with_very_large_rrf_k(self) -> None:
        """Test fuse with very large rrf_k value."""
        config = RetrievalConfig(rrf_k=10000)
        retriever = MemoryRetriever(config)

        mem1 = SemanticMemory(content="test1", importance=0.8)
        mem2 = SemanticMemory(content="test2", importance=0.6)

        result1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.SEMANTIC)
        result2 = MemorySearchResult(memory=mem2, score=0.7, memory_type=MemoryType.SEMANTIC)

        fused = retriever.fuse([[result1, result2]], limit=10)
        assert len(fused) == 2


class TestRankEdgeCases:
    """Test rank method edge cases."""

    def test_rank_with_single_result(self) -> None:
        """Test rank with single result."""
        retriever = MemoryRetriever()

        mem = SemanticMemory(content="test", importance=0.5)
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)

        ranked = retriever.rank([result], limit=10)
        assert len(ranked) == 1
        assert ranked[0].score == 1.0

    def test_rank_preserves_order_for_equal_scores(self) -> None:
        """Test rank behavior with equal scores."""
        retriever = MemoryRetriever()

        mem1 = SemanticMemory(content="test1", created_at=datetime.now(UTC), access_count=10, importance=0.5)
        mem2 = SemanticMemory(content="test2", created_at=datetime.now(UTC), access_count=10, importance=0.5)

        result1 = MemorySearchResult(memory=mem1, score=0.8, memory_type=MemoryType.SEMANTIC)
        result2 = MemorySearchResult(memory=mem2, score=0.8, memory_type=MemoryType.SEMANTIC)

        ranked = retriever.rank([result1, result2], limit=10)
        assert len(ranked) == 2

    def test_rank_with_limit_zero(self) -> None:
        """Test rank with limit=0."""
        retriever = MemoryRetriever()

        mem = SemanticMemory(content="test", importance=0.5)
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)

        ranked = retriever.rank([result], limit=0)
        assert len(ranked) == 0


class TestGeometricScoreEdgeCases:
    """Test _geometric_score method edge cases."""

    def test_geometric_score_with_all_signals_at_minimum(self) -> None:
        """Test geometric score with all signals at minimum values."""
        retriever = MemoryRetriever()

        mem = SemanticMemory(
            content="test",
            created_at=datetime.now(UTC) - timedelta(days=365),
            access_count=0,
            importance=0.0,
            confidence=0.01,
        )

        result = MemorySearchResult(memory=mem, score=0.01, memory_type=MemoryType.SEMANTIC)

        score = retriever._geometric_score(0.01, result)
        assert score > 0.0
        assert score < 0.01

    def test_geometric_score_with_all_signals_at_maximum(self) -> None:
        """Test geometric score with all signals at maximum values."""
        retriever = MemoryRetriever()

        mem = SemanticMemory(
            content="test", created_at=datetime.now(UTC), access_count=100, importance=1.0, confidence=1.0
        )

        result = MemorySearchResult(memory=mem, score=1.0, memory_type=MemoryType.SEMANTIC)

        score = retriever._geometric_score(1.0, result)
        assert score > 0.0
        assert score <= 1.0

    def test_geometric_score_with_missing_all_optional_fields(self) -> None:
        """Test geometric score when memory has minimal fields."""
        retriever = MemoryRetriever()

        mem = SemanticMemory(content="test")

        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)

        score = retriever._geometric_score(0.8, result)
        assert score > 0.0

    def test_geometric_score_preference_weight_zero(self) -> None:
        """Test that preference is excluded when weight is zero."""
        retriever = MemoryRetriever()

        mem_with_pref = SemanticMemory(
            content="test", importance=0.5, preference_type="explicit", preference_strength=0.9
        )

        mem_without_pref = SemanticMemory(content="test", importance=0.5)

        result_with = MemorySearchResult(memory=mem_with_pref, score=0.8, memory_type=MemoryType.SEMANTIC)
        result_without = MemorySearchResult(memory=mem_without_pref, score=0.8, memory_type=MemoryType.SEMANTIC)

        score_with = retriever._geometric_score(0.8, result_with)
        score_without = retriever._geometric_score(0.8, result_without)

        assert score_with == score_without

    def test_geometric_score_with_profile_preference(self) -> None:
        """Test geometric score with profile type that has preference weight."""
        retriever = MemoryRetriever()

        mem_with_pref = SemanticMemory(
            content="test", importance=0.5, preference_type="explicit", preference_strength=0.9
        )

        mem_without_pref = SemanticMemory(content="test", importance=0.5)

        result_with = MemorySearchResult(memory=mem_with_pref, score=0.8, memory_type=MemoryType.PROFILE)
        result_without = MemorySearchResult(memory=mem_without_pref, score=0.8, memory_type=MemoryType.PROFILE)

        score_with = retriever._geometric_score(0.8, result_with)
        score_without = retriever._geometric_score(0.8, result_without)

        assert score_with > score_without


class TestRetrieverInitialization:
    """Test MemoryRetriever initialization."""

    def test_init_with_none_config(self) -> None:
        """Test initialization with None config creates default."""
        retriever = MemoryRetriever(None)
        assert retriever._config.rrf_k == 60
        assert retriever._config.frequency_saturation == 50

    def test_init_with_custom_config(self) -> None:
        """Test initialization with custom config."""
        config = RetrievalConfig(rrf_k=80, frequency_saturation=100)
        retriever = MemoryRetriever(config)
        assert retriever._config.rrf_k == 80
        assert retriever._config.frequency_saturation == 100

    def test_init_creates_signal_calculator(self) -> None:
        """Test that initialization creates SignalCalculator instance."""
        from myrm_agent_harness.toolkits.memory.signals import SignalCalculator

        retriever = MemoryRetriever()
        assert retriever._signal_calc is not None
        assert isinstance(retriever._signal_calc, SignalCalculator)


class TestPatternMatchingBoost:
    """Test _pattern_matching_boost method."""

    def test_no_query_context_returns_zero(self) -> None:
        retriever = MemoryRetriever()
        mem = SemanticMemory(content="test content", importance=0.5)
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)
        assert retriever._pattern_matching_boost(result, None) == 0.0

    def test_invalid_query_context_type_returns_zero(self) -> None:
        retriever = MemoryRetriever()
        mem = SemanticMemory(content="test content", importance=0.5)
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)
        assert retriever._pattern_matching_boost(result, "not a query context") == 0.0

    def test_quoted_phrase_found(self) -> None:
        retriever = MemoryRetriever()
        mem = SemanticMemory(content="This is about machine learning algorithms", importance=0.5)
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)
        ctx = QueryContext(
            quoted_phrases=["machine learning"],
            person_names=[],
            temporal_markers=[],
        )
        boost = retriever._pattern_matching_boost(result, ctx)
        assert boost >= retriever._config.quoted_phrase_boost

    def test_quoted_phrase_not_found(self) -> None:
        retriever = MemoryRetriever()
        mem = SemanticMemory(content="This is about web development", importance=0.5)
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)
        ctx = QueryContext(
            quoted_phrases=["machine learning"],
            person_names=[],
            temporal_markers=[],
        )
        boost = retriever._pattern_matching_boost(result, ctx)
        assert boost == 0.0

    def test_person_name_found(self) -> None:
        retriever = MemoryRetriever()
        mem = SemanticMemory(content="John mentioned a new approach", importance=0.5)
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)
        ctx = QueryContext(
            quoted_phrases=[],
            person_names=["John"],
            temporal_markers=[],
        )
        boost = retriever._pattern_matching_boost(result, ctx)
        assert boost >= retriever._config.person_name_boost

    def test_person_name_not_found(self) -> None:
        retriever = MemoryRetriever()
        mem = SemanticMemory(content="Someone mentioned a new approach", importance=0.5)
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)
        ctx = QueryContext(
            quoted_phrases=[],
            person_names=["John"],
            temporal_markers=[],
        )
        boost = retriever._pattern_matching_boost(result, ctx)
        assert boost == 0.0

    def test_temporal_proximity_within_one_day(self) -> None:
        now = datetime.now(UTC)
        yesterday = now - timedelta(hours=12)
        retriever = MemoryRetriever()
        mem = SemanticMemory(content="test", importance=0.5, created_at=yesterday)
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)
        ctx = QueryContext(
            quoted_phrases=[],
            person_names=[],
            temporal_markers=["yesterday"],
            reference_time=now - timedelta(days=1),
        )
        boost = retriever._pattern_matching_boost(result, ctx)
        assert boost >= retriever._config.temporal_boost_weight

    def test_temporal_proximity_within_one_week(self) -> None:
        now = datetime.now(UTC)
        retriever = MemoryRetriever()
        mem = SemanticMemory(content="test", importance=0.5, created_at=now - timedelta(days=10))
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)
        ctx = QueryContext(
            quoted_phrases=[],
            person_names=[],
            temporal_markers=["last week"],
            reference_time=now - timedelta(weeks=1),
        )
        boost = retriever._pattern_matching_boost(result, ctx)
        assert boost >= retriever._config.temporal_boost_weight * 0.5
        assert boost < retriever._config.temporal_boost_weight

    def test_temporal_proximity_within_one_month(self) -> None:
        now = datetime.now(UTC)
        retriever = MemoryRetriever()
        mem = SemanticMemory(content="test", importance=0.5, created_at=now - timedelta(days=40))
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)
        ctx = QueryContext(
            quoted_phrases=[],
            person_names=[],
            temporal_markers=["last month"],
            reference_time=now - timedelta(days=30),
        )
        boost = retriever._pattern_matching_boost(result, ctx)
        assert boost >= retriever._config.temporal_boost_weight * 0.2
        assert boost < retriever._config.temporal_boost_weight * 0.5

    def test_temporal_no_reference_time(self) -> None:
        retriever = MemoryRetriever()
        mem = SemanticMemory(content="test", importance=0.5, created_at=datetime.now(UTC))
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)
        ctx = QueryContext(
            quoted_phrases=[],
            person_names=[],
            temporal_markers=[],
            reference_time=None,
        )
        boost = retriever._pattern_matching_boost(result, ctx)
        assert boost == 0.0

    def test_combined_boosts(self) -> None:
        now = datetime.now(UTC)
        yesterday = now - timedelta(hours=12)
        retriever = MemoryRetriever()
        mem = SemanticMemory(content="John said machine learning is great", importance=0.5, created_at=yesterday)
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)
        ctx = QueryContext(
            quoted_phrases=["machine learning"],
            person_names=["John"],
            temporal_markers=["yesterday"],
            reference_time=now - timedelta(days=1),
        )
        boost = retriever._pattern_matching_boost(result, ctx)
        expected_min = (
            retriever._config.quoted_phrase_boost
            + retriever._config.person_name_boost
            + retriever._config.temporal_boost_weight
        )
        assert boost >= expected_min


class TestMMRSelect:
    """Test _mmr_select method."""

    def test_lambda_1_returns_all(self) -> None:
        """When lambda=1.0, MMR is skipped (pure relevance)."""
        config = RetrievalConfig(mmr_lambda=1.0)
        retriever = MemoryRetriever(config)

        mem1 = SemanticMemory(content="test1", importance=0.5)
        mem2 = SemanticMemory(content="test2", importance=0.5)
        result1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.SEMANTIC)
        result2 = MemorySearchResult(memory=mem2, score=0.7, memory_type=MemoryType.SEMANTIC)

        scores = {"id1": 0.9, "id2": 0.7}
        items = {"id1": result1, "id2": result2}

        new_scores, new_items = retriever._mmr_select(scores, items, limit=5)
        assert new_scores == scores
        assert new_items == items

    def test_fewer_items_than_limit(self) -> None:
        """When items <= limit, MMR is skipped."""
        config = RetrievalConfig(mmr_lambda=0.7)
        retriever = MemoryRetriever(config)

        mem = SemanticMemory(content="test", importance=0.5)
        result = MemorySearchResult(memory=mem, score=0.9, memory_type=MemoryType.SEMANTIC)

        scores = {"id1": 0.9}
        items = {"id1": result}

        new_scores, _new_items = retriever._mmr_select(scores, items, limit=5)
        assert new_scores == scores

    def test_diversity_selection(self) -> None:
        """MMR should prefer diverse content over similar content."""
        config = RetrievalConfig(mmr_lambda=0.5)
        retriever = MemoryRetriever(config)

        mem1 = SemanticMemory(id="a", content="python machine learning tensorflow keras", importance=0.5)
        mem2 = SemanticMemory(id="b", content="python machine learning pytorch neural", importance=0.5)
        mem3 = SemanticMemory(id="c", content="javascript react frontend web application", importance=0.5)

        result1 = MemorySearchResult(memory=mem1, score=0.9, memory_type=MemoryType.SEMANTIC)
        result2 = MemorySearchResult(memory=mem2, score=0.85, memory_type=MemoryType.SEMANTIC)
        result3 = MemorySearchResult(memory=mem3, score=0.8, memory_type=MemoryType.SEMANTIC)

        scores = {"a": 0.9, "b": 0.85, "c": 0.8}
        items = {"a": result1, "b": result2, "c": result3}

        new_scores, _new_items = retriever._mmr_select(scores, items, limit=2)
        assert len(new_scores) == 2
        assert "a" in new_scores
        assert "c" in new_scores

    def test_all_zero_scores(self) -> None:
        """When all scores are zero, return as-is."""
        config = RetrievalConfig(mmr_lambda=0.7)
        retriever = MemoryRetriever(config)

        mem1 = SemanticMemory(content="test1", importance=0.5)
        mem2 = SemanticMemory(content="test2", importance=0.5)

        result1 = MemorySearchResult(memory=mem1, score=0.0, memory_type=MemoryType.SEMANTIC)
        result2 = MemorySearchResult(memory=mem2, score=0.0, memory_type=MemoryType.SEMANTIC)

        scores = {"id1": 0.0, "id2": 0.0}
        items = {"id1": result1, "id2": result2}

        new_scores, _new_items = retriever._mmr_select(scores, items, limit=1)
        assert new_scores == scores


class TestJaccardSimilarity:
    """Test _jaccard_similarity function."""

    def test_identical_sets(self) -> None:
        assert _jaccard_similarity(frozenset({"a", "b"}), frozenset({"a", "b"})) == 1.0

    def test_no_overlap(self) -> None:
        assert _jaccard_similarity(frozenset({"a", "b"}), frozenset({"c", "d"})) == 0.0

    def test_partial_overlap(self) -> None:
        result = _jaccard_similarity(frozenset({"a", "b", "c"}), frozenset({"b", "c", "d"}))
        assert 0.0 < result < 1.0
        assert abs(result - 2.0 / 4.0) < 1e-9

    def test_empty_sets(self) -> None:
        assert _jaccard_similarity(frozenset(), frozenset({"a"})) == 0.0
        assert _jaccard_similarity(frozenset({"a"}), frozenset()) == 0.0
        assert _jaccard_similarity(frozenset(), frozenset()) == 0.0


class TestBoostWithQueryContext:
    """Test _boost method with query_context parameter."""

    def test_boost_with_query_context_increases_score(self) -> None:
        now = datetime.now(UTC)
        retriever = MemoryRetriever()
        mem = SemanticMemory(content="John talked about machine learning", importance=0.7, created_at=now - timedelta(hours=12))
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)

        ctx = QueryContext(
            quoted_phrases=["machine learning"],
            person_names=["John"],
            temporal_markers=["yesterday"],
            reference_time=now - timedelta(days=1),
        )

        score_without_ctx = retriever._boost(0.8, result, frozenset())
        score_with_ctx = retriever._boost(0.8, result, frozenset(), ctx)
        assert score_with_ctx > score_without_ctx

    def test_boost_none_query_context_same_as_without(self) -> None:
        retriever = MemoryRetriever()
        mem = SemanticMemory(content="test content", importance=0.7)
        result = MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)

        score_none = retriever._boost(0.8, result, frozenset(), None)
        score_default = retriever._boost(0.8, result, frozenset())
        assert score_none == pytest.approx(score_default, rel=1e-6)


class TestRankWithQueryContext:
    """Test rank/fuse methods pass query_context correctly."""

    def test_rank_with_query_context(self) -> None:
        now = datetime.now(UTC)
        retriever = MemoryRetriever()

        mem_recent = SemanticMemory(id="recent", content="John discussed yesterday", importance=0.7, created_at=now - timedelta(hours=12))
        mem_old = SemanticMemory(id="old", content="some old content", importance=0.8, created_at=now - timedelta(days=30))

        results = [
            MemorySearchResult(memory=mem_recent, score=0.75, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=mem_old, score=0.85, memory_type=MemoryType.SEMANTIC),
        ]

        ctx = QueryContext(
            quoted_phrases=[],
            person_names=["John"],
            temporal_markers=["yesterday"],
            reference_time=now - timedelta(days=1),
        )

        ranked = retriever.rank(results, limit=10, query_context=ctx)
        assert len(ranked) == 2
        assert ranked[0].memory.id == "recent"

    def test_fuse_with_query_context(self) -> None:
        now = datetime.now(UTC)
        retriever = MemoryRetriever()

        mem_match = SemanticMemory(id="match", content="Alice said hello world", importance=0.7, created_at=now)
        mem_no = SemanticMemory(id="nomatch", content="some other thing", importance=0.7, created_at=now)

        list1 = [MemorySearchResult(memory=mem_match, score=0.7, memory_type=MemoryType.SEMANTIC)]
        list2 = [MemorySearchResult(memory=mem_no, score=0.8, memory_type=MemoryType.SEMANTIC)]

        ctx = QueryContext(
            quoted_phrases=["hello world"],
            person_names=["Alice"],
            temporal_markers=[],
        )

        fused = retriever.fuse([list1, list2], limit=10, query_context=ctx)
        assert len(fused) == 2
        assert fused[0].memory.id == "match"


class TestSourceDecayMMR:
    """Test source decay in MMR selection."""

    def _make_result(self, mid: str, content: str, source_chat_id: str | None = None) -> MemorySearchResult:
        mem = SemanticMemory(id=mid, content=content, importance=0.5, source_chat_id=source_chat_id)
        return MemorySearchResult(memory=mem, score=0.8, memory_type=MemoryType.SEMANTIC)

    def test_source_decay_disabled_when_weight_zero(self) -> None:
        """When source_diversity_weight=0, behaves like standard MMR."""
        config = RetrievalConfig(mmr_lambda=0.7, source_diversity_weight=0.0)
        retriever = MemoryRetriever(config)

        results = [
            self._make_result("a1", "react performance virtual dom", "chat_a"),
            self._make_result("a2", "react memo usecallback hooks", "chat_a"),
            self._make_result("a3", "react code splitting lazy", "chat_a"),
            self._make_result("b1", "vue performance reactivity", "chat_b"),
        ]

        ranked = retriever.rank(results, limit=4, query="performance optimization")
        assert len(ranked) == 4

    def test_source_decay_promotes_diverse_sources(self) -> None:
        """With source_diversity_weight > 0, results from diverse sources are promoted."""
        config = RetrievalConfig(mmr_lambda=0.7, source_diversity_weight=0.8)
        retriever = MemoryRetriever(config)

        results = [
            self._make_result("a1", "react performance optimization tips", "chat_a"),
            self._make_result("a2", "react virtual dom rendering speed", "chat_a"),
            self._make_result("a3", "react code splitting bundle size", "chat_a"),
            self._make_result("a4", "react memo usecallback perf", "chat_a"),
            self._make_result("b1", "vue performance reactivity system", "chat_b"),
            self._make_result("c1", "svelte compile time optimization", "chat_c"),
        ]

        ranked_no_decay = MemoryRetriever(
            RetrievalConfig(mmr_lambda=0.7, source_diversity_weight=0.0)
        ).rank(results, limit=5, query="frontend performance optimization")

        ranked_with_decay = retriever.rank(results, limit=5, query="frontend performance optimization")

        sources_no_decay = [getattr(r.memory, "source_chat_id", None) for r in ranked_no_decay]
        sources_with_decay = [getattr(r.memory, "source_chat_id", None) for r in ranked_with_decay]

        unique_no_decay = len(set(s for s in sources_no_decay if s))
        unique_with_decay = len(set(s for s in sources_with_decay if s))

        assert unique_with_decay >= unique_no_decay

    def test_source_decay_handles_none_source_id(self) -> None:
        """Results without source_chat_id are never penalized."""
        config = RetrievalConfig(mmr_lambda=0.7, source_diversity_weight=0.8)
        retriever = MemoryRetriever(config)

        results = [
            self._make_result("a1", "performance optimization react", None),
            self._make_result("a2", "performance tuning react apps", None),
            self._make_result("b1", "vue performance optimization", "chat_b"),
        ]

        ranked = retriever.rank(results, limit=3, query="performance")
        assert len(ranked) == 3

    def test_source_decay_does_not_eliminate_high_relevance(self) -> None:
        """High-relevance same-source results still appear (soft penalty, not hard cutoff)."""
        config = RetrievalConfig(mmr_lambda=0.7, source_diversity_weight=0.5)
        retriever = MemoryRetriever(config)

        results = [
            self._make_result("a1", "react performance optimization virtual dom", "chat_a"),
            self._make_result("a2", "react hooks performance memo callback", "chat_a"),
            self._make_result("a3", "react code splitting lazy loading", "chat_a"),
            self._make_result("b1", "python backend performance", "chat_b"),
        ]

        ranked = retriever.rank(results, limit=4, query="react performance")
        source_ids = [getattr(r.memory, "source_chat_id", None) for r in ranked]
        chat_a_count = sum(1 for s in source_ids if s == "chat_a")
        assert chat_a_count >= 2
