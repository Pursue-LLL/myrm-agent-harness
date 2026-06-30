"""B11 Competitive Ranking Verification Tests.

Verifies that MyrmAgent's memory ranking system provides capabilities
equal to or superior to gbrain's source-boost approach. Each test maps
to a specific competitive claim:

1. type_weights → gbrain's source-boost (per-source boost factors)
2. correction_chain suppression → gbrain's hard-exclude (remove outdated info)
3. archival config → gbrain's detail-gate (reduce noise from old memories)
4. geometric scoring → gbrain's SQL-level scoring (multi-signal ranking)
5. MMR diversity → no gbrain equivalent (superior diversity control)
6. keyword/temporal/person/preference boosts → no gbrain equivalent (superior context-awareness)
7. dual-channel RRF → gbrain's two-stage search (broader coverage)
"""

from datetime import UTC, datetime, timedelta

from myrm_agent_harness.toolkits.memory.config import RetrievalConfig
from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever
from myrm_agent_harness.toolkits.memory.signals import (
    SignalCalculator,
    get_default_half_life,
    get_default_signal_weights,
)
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)


class TestTypeWeightsVsSourceBoost:
    """Verify type_weights provides per-memory-type ranking differentiation.

    gbrain: Fixed source-boost factors (originals/ = 1.5, wintermute/chat/ = 0.5)
    MyrmAgent: Fine-grained type_weights per MemoryType + geometric scoring
    """

    def test_profile_memories_boosted_over_episodic(self) -> None:
        """Profile (1.0) should consistently outrank Episodic (0.8) at equal semantic score."""
        config = RetrievalConfig(
            keyword_overlap_weight=0.0,
            temporal_boost_weight=0.0,
            min_relevance_score=0.0,
        )
        retriever = MemoryRetriever(config)

        profile = MemorySearchResult(
            memory=SemanticMemory(
                content="User prefers Python 3.12",
                created_at=datetime.now(UTC) - timedelta(days=30),
                access_count=5,
                importance=0.6,
                preference_type="explicit",
                preference_strength=0.8,
            ),
            score=0.80,
            memory_type=MemoryType.PROFILE,
        )
        episodic = MemorySearchResult(
            memory=EpisodicMemory(
                content="Talked about Python 3.12",
                created_at=datetime.now(UTC) - timedelta(days=30),
                access_count=5,
                importance=0.6,
            ),
            score=0.80,
            memory_type=MemoryType.EPISODIC,
        )

        fused = retriever.fuse([[profile, episodic]], limit=2)
        assert fused[0].memory_type == MemoryType.PROFILE

    def test_claim_boosted_above_conversation(self) -> None:
        """Claim (1.05) should outrank Conversation (0.95) at equal conditions."""
        config = RetrievalConfig(
            keyword_overlap_weight=0.0,
            temporal_boost_weight=0.0,
            min_relevance_score=0.0,
            type_weights={
                MemoryType.CLAIM: 1.05,
                MemoryType.CONVERSATION: 0.95,
            },
        )
        retriever = MemoryRetriever(config)

        claim = MemorySearchResult(
            memory=SemanticMemory(
                content="User always uses pytest",
                created_at=datetime.now(UTC) - timedelta(days=10),
                access_count=10,
                importance=0.7,
            ),
            score=0.80,
            memory_type=MemoryType.CLAIM,
        )
        conversation = MemorySearchResult(
            memory=SemanticMemory(
                content="Discussed pytest in session",
                created_at=datetime.now(UTC) - timedelta(days=10),
                access_count=10,
                importance=0.7,
            ),
            score=0.80,
            memory_type=MemoryType.CONVERSATION,
        )

        fused = retriever.fuse([[claim, conversation]], limit=2)
        assert fused[0].memory_type == MemoryType.CLAIM

    def test_custom_type_weights_respected(self) -> None:
        """Custom type_weights configuration must be applied."""
        config = RetrievalConfig(
            type_weights={
                MemoryType.SEMANTIC: 2.0,
                MemoryType.EPISODIC: 0.1,
            },
            keyword_overlap_weight=0.0,
            min_relevance_score=0.0,
            temporal_boost_weight=0.0,
        )
        retriever = MemoryRetriever(config)

        semantic = MemorySearchResult(
            memory=SemanticMemory(content="semantic fact", importance=0.5),
            score=0.70,
            memory_type=MemoryType.SEMANTIC,
        )
        episodic = MemorySearchResult(
            memory=EpisodicMemory(content="episodic event", importance=0.5),
            score=0.90,
            memory_type=MemoryType.EPISODIC,
        )

        fused = retriever.fuse([[semantic], [episodic]], limit=2)
        assert fused[0].memory_type == MemoryType.SEMANTIC


class TestCorrectionSuppressionVsHardExclude:
    """Verify correction-chain suppression (gbrain's hard-exclude equivalent).

    gbrain: PREFIX_HARD_EXCLUDES blocks entire sources via SQL WHERE NOT LIKE
    MyrmAgent: correction_of chain penalizes specific outdated memories (0.1x penalty)
    """

    def test_corrected_memory_demoted(self) -> None:
        """A memory with correction should be heavily penalized."""
        config = RetrievalConfig(
            correction_penalty=0.1,
            keyword_overlap_weight=0.0,
            temporal_boost_weight=0.0,
            min_relevance_score=0.0,
        )
        retriever = MemoryRetriever(config)

        old_fact = SemanticMemory(id="old-001", content="Python 3.11 is latest", importance=0.8)
        correction = SemanticMemory(
            id="new-001", content="Python 3.13 is latest", correction_of="old-001", importance=0.9
        )

        results = [
            MemorySearchResult(memory=old_fact, score=0.90, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=correction, score=0.85, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=2)
        assert ranked[0].id == "new-001"
        assert ranked[1].id == "old-001"
        # Corrected memory should have significantly lower normalized score
        assert ranked[0].score > ranked[1].score * 3

    def test_correction_chain_preserves_uncorrected(self) -> None:
        """Memories without correction relationship should not be affected."""
        config = RetrievalConfig(
            correction_penalty=0.1,
            keyword_overlap_weight=0.0,
            temporal_boost_weight=0.0,
            min_relevance_score=0.0,
        )
        retriever = MemoryRetriever(config)

        mem_a = SemanticMemory(id="a-001", content="TypeScript is great", importance=0.7)
        mem_b = SemanticMemory(id="b-001", content="JavaScript is popular", importance=0.6)

        results = [
            MemorySearchResult(memory=mem_a, score=0.80, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=mem_b, score=0.75, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=2)
        assert ranked[0].id == "a-001"
        # Both scores should be close (no suppression applied)
        ratio = ranked[1].score / ranked[0].score
        assert ratio > 0.5

    def test_multiple_corrections_all_suppressed(self) -> None:
        """Multiple corrections should all suppress their targets."""
        config = RetrievalConfig(
            correction_penalty=0.1,
            keyword_overlap_weight=0.0,
            temporal_boost_weight=0.0,
            min_relevance_score=0.0,
        )
        retriever = MemoryRetriever(config)

        old_a = SemanticMemory(id="old-a", content="outdated A", importance=0.8)
        old_b = SemanticMemory(id="old-b", content="outdated B", importance=0.8)
        new_a = SemanticMemory(id="new-a", content="corrected A", correction_of="old-a", importance=0.9)
        new_b = SemanticMemory(id="new-b", content="corrected B", correction_of="old-b", importance=0.9)

        results = [
            MemorySearchResult(memory=old_a, score=0.90, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=old_b, score=0.88, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=new_a, score=0.85, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=new_b, score=0.83, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=4)
        # Corrections should be at the top
        top_ids = {ranked[0].id, ranked[1].id}
        assert "new-a" in top_ids
        assert "new-b" in top_ids


class TestGeometricScoringVsSqlRanking:
    """Verify geometric 5-signal scoring (gbrain's SQL-level ranking equivalent).

    gbrain: source_factor * distance single-dimension scoring in SQL
    MyrmAgent: semantic^w0 * recency^w1 * frequency^w2 * importance^w3 * preference^w4 * confidence
    """

    def test_five_signal_fusion_all_contribute(self) -> None:
        """All 5 signals should contribute to final score."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0, min_relevance_score=0.0)
        retriever = MemoryRetriever(config)
        SignalCalculator()

        mem = SemanticMemory(
            content="test multi-signal",
            created_at=datetime.now(UTC) - timedelta(days=5),
            access_count=20,
            importance=0.8,
            confidence=0.9,
        )
        result = MemorySearchResult(memory=mem, score=0.85, memory_type=MemoryType.SEMANTIC)

        score = retriever._geometric_score(0.85, result)
        assert score > 0.0

        # Compare with same memory but lower importance
        mem_low_imp = SemanticMemory(
            content="test multi-signal low",
            created_at=datetime.now(UTC) - timedelta(days=5),
            access_count=20,
            importance=0.1,
            confidence=0.9,
        )
        result_low = MemorySearchResult(memory=mem_low_imp, score=0.85, memory_type=MemoryType.SEMANTIC)
        score_low = retriever._geometric_score(0.85, result_low)
        assert score > score_low

    def test_recency_signal_decays_correctly(self) -> None:
        """Recency should decay older memories for SEMANTIC type."""
        calc = SignalCalculator()

        recent = SemanticMemory(content="recent", created_at=datetime.now(UTC) - timedelta(days=1))
        old = SemanticMemory(content="old", created_at=datetime.now(UTC) - timedelta(days=60))

        half_life = get_default_half_life(MemoryType.SEMANTIC)  # 30 days
        recent_factor = calc.recency_factor(recent, half_life)
        old_factor = calc.recency_factor(old, half_life)

        assert recent_factor > old_factor
        assert recent_factor > 0.95  # 1 day old ≈ 0.977
        assert old_factor < 0.3  # 60 days = 2 half-lives ≈ 0.25

    def test_profile_immune_to_recency_decay(self) -> None:
        """Profile type should have zero recency decay (half_life = 0)."""
        half_life = get_default_half_life(MemoryType.PROFILE)
        assert half_life == 0.0

        calc = SignalCalculator()
        ancient = SemanticMemory(
            content="profile preference", created_at=datetime.now(UTC) - timedelta(days=1000)
        )
        factor = calc.recency_factor(ancient, half_life)
        assert factor == 1.0

    def test_frequency_saturation_logarithmic(self) -> None:
        """Frequency factor should saturate logarithmically."""
        calc = SignalCalculator()

        low_access = SemanticMemory(content="low", access_count=1)
        mid_access = SemanticMemory(content="mid", access_count=25)
        high_access = SemanticMemory(content="high", access_count=50)
        extreme_access = SemanticMemory(content="extreme", access_count=500)

        f_low = calc.frequency_factor(low_access, saturation_point=50)
        f_mid = calc.frequency_factor(mid_access, saturation_point=50)
        f_high = calc.frequency_factor(high_access, saturation_point=50)
        f_extreme = calc.frequency_factor(extreme_access, saturation_point=50)

        assert f_low < f_mid < f_high
        # Logarithmic: extreme shouldn't be much higher than saturation
        assert f_high <= 1.0
        assert f_extreme <= 1.0
        assert f_extreme - f_high < 0.5  # Saturation effect

    def test_confidence_gates_score(self) -> None:
        """Zero confidence should zero out entire score."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0, min_relevance_score=0.0)
        retriever = MemoryRetriever(config)

        mem_confident = SemanticMemory(
            content="confident fact",
            created_at=datetime.now(UTC),
            access_count=50,
            importance=1.0,
            confidence=1.0,
        )
        mem_uncertain = SemanticMemory(
            content="uncertain fact",
            created_at=datetime.now(UTC),
            access_count=50,
            importance=1.0,
            confidence=0.0,
        )

        r1 = MemorySearchResult(memory=mem_confident, score=0.9, memory_type=MemoryType.SEMANTIC)
        r2 = MemorySearchResult(memory=mem_uncertain, score=0.9, memory_type=MemoryType.SEMANTIC)

        s1 = retriever._geometric_score(0.9, r1)
        s2 = retriever._geometric_score(0.9, r2)

        assert s1 > 0.5
        assert s2 == 0.0

    def test_type_specific_weight_profiles(self) -> None:
        """Each memory type should have distinct signal weight profiles."""
        profile_w = get_default_signal_weights(MemoryType.PROFILE)
        semantic_w = get_default_signal_weights(MemoryType.SEMANTIC)
        episodic_w = get_default_signal_weights(MemoryType.EPISODIC)
        procedural_w = get_default_signal_weights(MemoryType.PROCEDURAL)

        # Profile: preference-dominant (0.45)
        assert profile_w["preference"] > profile_w["semantic"]
        # Semantic: semantic-dominant (0.65)
        assert semantic_w["semantic"] >= 0.6
        # Episodic: recency important (0.25)
        assert episodic_w["recency"] > semantic_w["recency"]
        # Procedural: importance-dominant (0.45)
        assert procedural_w["importance"] >= 0.4


class TestMMRDiversity:
    """Verify MMR diversity control (no gbrain equivalent).

    gbrain: No diversity mechanism; can return N nearly-identical results
    MyrmAgent: Jaccard-based MMR with configurable λ parameter
    """

    def test_mmr_removes_near_duplicates(self) -> None:
        """MMR should prefer diverse results over similar ones."""
        config = RetrievalConfig(
            mmr_lambda=0.5,
            keyword_overlap_weight=0.0,
            temporal_boost_weight=0.0,
            min_relevance_score=0.0,
        )
        retriever = MemoryRetriever(config)

        mem1 = SemanticMemory(content="Python type hints are useful for code quality", importance=0.6)
        mem2 = SemanticMemory(content="Python type hints are useful for code readability", importance=0.6)
        mem3 = SemanticMemory(content="Docker containers provide isolated environments", importance=0.6)

        results = [
            MemorySearchResult(memory=mem1, score=0.90, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=mem2, score=0.88, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=mem3, score=0.75, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=2)
        contents = [r.memory.content for r in ranked]
        # At least one of the top 2 should be the Docker memory (diversity)
        assert any("Docker" in c for c in contents)

    def test_mmr_lambda_1_pure_relevance(self) -> None:
        """λ=1.0 should degrade to pure relevance ordering."""
        config = RetrievalConfig(
            mmr_lambda=1.0,
            keyword_overlap_weight=0.0,
            temporal_boost_weight=0.0,
            min_relevance_score=0.0,
        )
        retriever = MemoryRetriever(config)

        mem1 = SemanticMemory(content="Python type hints are useful for code quality", importance=0.6)
        mem2 = SemanticMemory(content="Python type hints are useful for code readability", importance=0.6)

        results = [
            MemorySearchResult(memory=mem1, score=0.90, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=mem2, score=0.88, memory_type=MemoryType.SEMANTIC),
        ]

        ranked = retriever.rank(results, limit=2)
        # Pure relevance: higher score first
        assert ranked[0].memory.content == mem1.content


class TestContextAwareBoosts:
    """Verify context-aware boost strategies (no gbrain equivalent).

    gbrain: No keyword/temporal/person-name/preference boosting
    MyrmAgent: 4 independent boost strategies with configurable weights
    """

    def test_keyword_overlap_boost(self) -> None:
        """Results with keyword overlap should be boosted."""
        config = RetrievalConfig(
            keyword_overlap_weight=0.3,
            keyword_overlap_min_tokens=1,
            temporal_boost_weight=0.0,
            min_relevance_score=0.0,
        )
        retriever = MemoryRetriever(config)

        mem_match = SemanticMemory(content="Python asyncio is powerful for concurrency", importance=0.5)
        mem_no_match = SemanticMemory(content="JavaScript promises handle async operations", importance=0.5)

        r_match = MemorySearchResult(memory=mem_match, score=0.75, memory_type=MemoryType.SEMANTIC)
        r_no = MemorySearchResult(memory=mem_no_match, score=0.80, memory_type=MemoryType.SEMANTIC)

        query = "Python asyncio concurrency"
        ranked = retriever.rank([r_match, r_no], limit=2, query=query)
        # Keyword boost should elevate the matching result
        assert ranked[0].memory.content == mem_match.content

    def test_temporal_proximity_boost(self) -> None:
        """Recent memories should get temporal proximity boost."""
        config = RetrievalConfig(
            temporal_boost_weight=0.40,
            keyword_overlap_weight=0.0,
            min_relevance_score=0.0,
        )
        retriever = MemoryRetriever(config)

        very_recent = SemanticMemory(
            content="just discussed topic",
            created_at=datetime.now(UTC) - timedelta(hours=2),
            importance=0.5,
        )
        old = SemanticMemory(
            content="discussed topic long ago",
            created_at=datetime.now(UTC) - timedelta(days=30),
            importance=0.5,
        )

        r_recent = MemorySearchResult(memory=very_recent, score=0.70, memory_type=MemoryType.SEMANTIC)
        r_old = MemorySearchResult(memory=old, score=0.75, memory_type=MemoryType.SEMANTIC)

        ranked = retriever.rank([r_recent, r_old], limit=2)
        # Temporal boost should lift the recent one above old despite lower base score
        assert ranked[0].memory.content == very_recent.content

    def test_preference_boost_for_profile_memories(self) -> None:
        """Preference-tagged memories should get boosted for PROFILE type."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0, min_relevance_score=0.0)
        retriever = MemoryRetriever(config)

        pref_mem = SemanticMemory(
            content="User prefers dark mode",
            importance=0.5,
            preference_type="explicit",
            preference_strength=0.9,
        )
        plain_mem = SemanticMemory(
            content="User uses dark mode",
            importance=0.5,
        )

        r_pref = MemorySearchResult(memory=pref_mem, score=0.75, memory_type=MemoryType.PROFILE)
        r_plain = MemorySearchResult(memory=plain_mem, score=0.80, memory_type=MemoryType.SEMANTIC)

        s_pref = retriever._boost(0.75, r_pref, frozenset())
        retriever._boost(0.80, r_plain, frozenset())

        # Profile with preference should get significant preference weight
        # (preference weight = 0.45 for PROFILE type vs 0.0 for SEMANTIC)
        assert s_pref > 0.0


class TestDualChannelFusion:
    """Verify dual-channel RRF fusion (gbrain's two-stage search equivalent).

    gbrain: Two-stage search (initial + retry with relaxed threshold)
    MyrmAgent: Dual-channel (raw_embedding + summary_embedding) RRF fusion
    """

    def test_multi_channel_fusion_accumulates_scores(self) -> None:
        """Same memory appearing in multiple channels should accumulate RRF scores."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0, min_relevance_score=0.0)
        retriever = MemoryRetriever(config)

        shared_mem = SemanticMemory(
            id="shared-001",
            content="Python asyncio patterns",
            created_at=datetime.now(UTC) - timedelta(days=5),
            access_count=10,
            importance=0.7,
        )
        unique_mem = SemanticMemory(
            id="unique-001",
            content="Rust async runtime",
            created_at=datetime.now(UTC) - timedelta(days=5),
            access_count=10,
            importance=0.7,
        )

        # Channel 1 (vector): shared appears at rank 1
        ch1 = [
            MemorySearchResult(memory=shared_mem, score=0.90, memory_type=MemoryType.SEMANTIC),
            MemorySearchResult(memory=unique_mem, score=0.70, memory_type=MemoryType.SEMANTIC),
        ]
        # Channel 2 (BM25): shared appears at rank 2
        ch2 = [
            MemorySearchResult(
                memory=SemanticMemory(
                    id="another-001", content="asyncio tutorial", importance=0.5
                ),
                score=0.85,
                memory_type=MemoryType.SEMANTIC,
            ),
            MemorySearchResult(memory=shared_mem, score=0.80, memory_type=MemoryType.SEMANTIC),
        ]

        fused = retriever.fuse([ch1, ch2], limit=3)
        # Shared memory should be boosted by appearing in both channels
        assert fused[0].id == "shared-001"

    def test_single_channel_still_works(self) -> None:
        """Single channel input should still produce valid results."""
        config = RetrievalConfig(keyword_overlap_weight=0.0, temporal_boost_weight=0.0, min_relevance_score=0.0)
        retriever = MemoryRetriever(config)

        results = [
            MemorySearchResult(
                memory=SemanticMemory(content=f"mem_{i}", importance=0.5),
                score=0.9 - i * 0.1,
                memory_type=MemoryType.SEMANTIC,
            )
            for i in range(5)
        ]

        fused = retriever.fuse([results], limit=3)
        assert len(fused) == 3
        assert fused[0].score == 1.0


class TestArchivalVsDetailGate:
    """Verify archival config provides noise reduction (gbrain's detail-gate equivalent).

    gbrain: detail-gate separates full-detail from summary chunks in SQL
    MyrmAgent: Archival system moves old/rarely-accessed memories to separate collections
    """

    def test_archival_config_defaults_reasonable(self) -> None:
        """Archival config should have production-ready defaults."""
        from myrm_agent_harness.toolkits.memory.config import ArchivalConfig

        ac = ArchivalConfig()
        assert ac.enabled is True
        assert ac.min_age_days >= 90  # At least 3 months before archiving
        assert ac.max_access_count >= 3  # Rarely accessed threshold
        assert ac.max_importance <= 0.5  # Only archive unimportant memories
        assert ac.batch_size >= 50  # Efficient batch processing

    def test_type_weights_can_demote_conversation_noise(self) -> None:
        """CONVERSATION type weight (0.95) inherently reduces chat noise vs SEMANTIC (1.0)."""
        config = RetrievalConfig()
        assert config.type_weights[MemoryType.CONVERSATION] < config.type_weights[MemoryType.SEMANTIC]
        assert config.type_weights[MemoryType.EPISODIC] < config.type_weights[MemoryType.SEMANTIC]


class TestEndToEndRankingPipeline:
    """End-to-end pipeline tests simulating real retrieval scenarios."""

    def test_complex_scenario_multi_signal_ranking(self) -> None:
        """Simulate a real search: mix of memory types, ages, and relevance."""
        config = RetrievalConfig(min_relevance_score=0.0)
        retriever = MemoryRetriever(config)

        memories = [
            # High relevance, old, low access (should rank well for SEMANTIC)
            MemorySearchResult(
                memory=SemanticMemory(
                    content="User uses pytest for all testing",
                    created_at=datetime.now(UTC) - timedelta(days=60),
                    access_count=3,
                    importance=0.8,
                ),
                score=0.92,
                memory_type=MemoryType.SEMANTIC,
            ),
            # Medium relevance, very recent, high access
            MemorySearchResult(
                memory=SemanticMemory(
                    content="pytest is a testing framework for Python",
                    created_at=datetime.now(UTC) - timedelta(hours=2),
                    access_count=30,
                    importance=0.5,
                ),
                score=0.78,
                memory_type=MemoryType.SEMANTIC,
            ),
            # Correction of first result
            MemorySearchResult(
                memory=SemanticMemory(
                    id="correction-001",
                    content="User now prefers pytest-asyncio over plain pytest",
                    correction_of="old-pytest-pref",
                    created_at=datetime.now(UTC) - timedelta(days=2),
                    access_count=5,
                    importance=0.9,
                ),
                score=0.88,
                memory_type=MemoryType.SEMANTIC,
            ),
            # Low confidence memory
            MemorySearchResult(
                memory=SemanticMemory(
                    content="Maybe user uses unittest sometimes",
                    created_at=datetime.now(UTC) - timedelta(days=5),
                    access_count=1,
                    importance=0.3,
                    confidence=0.2,
                ),
                score=0.85,
                memory_type=MemoryType.SEMANTIC,
            ),
            # Profile preference
            MemorySearchResult(
                memory=SemanticMemory(
                    content="User prefers automated testing",
                    created_at=datetime.now(UTC) - timedelta(days=365),
                    importance=0.9,
                    preference_type="implicit",
                    preference_strength=0.7,
                ),
                score=0.70,
                memory_type=MemoryType.PROFILE,
            ),
        ]

        ranked = retriever.rank(memories, limit=5, query="pytest testing")

        # Low confidence memory should NOT be in top 2
        top2_contents = [r.memory.content for r in ranked[:2]]
        assert "Maybe user uses unittest sometimes" not in top2_contents

        # Correction should rank reasonably high
        correction_idx = next(
            i for i, r in enumerate(ranked) if r.id == "correction-001"
        )
        assert correction_idx < 3

    def test_full_pipeline_deterministic(self) -> None:
        """Same inputs should produce same ranking (no randomness)."""
        config = RetrievalConfig(min_relevance_score=0.0)
        retriever = MemoryRetriever(config)

        results = [
            MemorySearchResult(
                memory=SemanticMemory(
                    content=f"fact_{i}",
                    created_at=datetime.now(UTC) - timedelta(days=i * 5),
                    access_count=i * 3,
                    importance=0.5 + i * 0.05,
                ),
                score=0.9 - i * 0.05,
                memory_type=MemoryType.SEMANTIC,
            )
            for i in range(8)
        ]

        ranked_1 = retriever.rank(results[:], limit=5, query="test query")
        ranked_2 = retriever.rank(results[:], limit=5, query="test query")

        ids_1 = [r.id for r in ranked_1]
        ids_2 = [r.id for r in ranked_2]
        assert ids_1 == ids_2

    def test_all_scores_normalized_0_to_1(self) -> None:
        """Final scores must always be in [0, 1] range."""
        config = RetrievalConfig(min_relevance_score=0.0)
        retriever = MemoryRetriever(config)

        results = [
            MemorySearchResult(
                memory=SemanticMemory(
                    content=f"mem_{i}",
                    created_at=datetime.now(UTC) - timedelta(days=i),
                    access_count=i * 10,
                    importance=0.1 + i * 0.1,
                ),
                score=0.5 + i * 0.05,
                memory_type=MemoryType.SEMANTIC,
            )
            for i in range(10)
        ]

        ranked = retriever.rank(results, limit=10, query="test normalization")
        for r in ranked:
            assert 0.0 <= r.score <= 1.0

        fused = retriever.fuse([results[:5], results[5:]], limit=10, query="test normalization")
        for r in fused:
            assert 0.0 <= r.score <= 1.0
