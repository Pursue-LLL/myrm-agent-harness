"""Coverage tests for signals.py edge cases."""

from datetime import UTC, datetime, timedelta

from myrm_agent_harness.toolkits.memory.signals import (
    SignalCalculator,
    get_default_half_life,
    get_default_signal_weights,
)
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, MemoryType, ProceduralMemory, SemanticMemory


class TestRecencyFactorEdgeCases:
    """Test recency_factor edge cases."""

    def test_recency_with_exact_half_life(self) -> None:
        """Test recency at exact half-life point."""
        mem = SemanticMemory(content="test", created_at=datetime.now(UTC) - timedelta(days=30))
        factor = SignalCalculator.recency_factor(mem, half_life_days=30.0)
        assert 0.49 < factor < 0.51

    def test_recency_with_very_small_half_life(self) -> None:
        """Test recency with very small half-life."""
        mem = SemanticMemory(content="test", created_at=datetime.now(UTC) - timedelta(days=1))
        factor = SignalCalculator.recency_factor(mem, half_life_days=0.1)
        assert factor < 0.01

    def test_recency_with_very_large_half_life(self) -> None:
        """Test recency with very large half-life."""
        mem = SemanticMemory(content="test", created_at=datetime.now(UTC) - timedelta(days=365))
        factor = SignalCalculator.recency_factor(mem, half_life_days=1000.0)
        assert factor > 0.7

    def test_recency_with_zero_age(self) -> None:
        """Test recency with memory created right now."""
        mem = SemanticMemory(content="test", created_at=datetime.now(UTC))
        factor = SignalCalculator.recency_factor(mem, half_life_days=7.0)
        assert factor == 1.0

    def test_recency_with_negative_half_life(self) -> None:
        """Test recency with negative half-life."""
        mem = SemanticMemory(content="test", created_at=datetime.now(UTC) - timedelta(days=10))
        factor = SignalCalculator.recency_factor(mem, half_life_days=-5.0)
        assert factor == 1.0


class TestFrequencyFactorEdgeCases:
    """Test frequency_factor edge cases."""

    def test_frequency_with_saturation_point_one(self) -> None:
        """Test frequency with saturation_point=1."""
        mem = SemanticMemory(content="test", access_count=1)
        factor = SignalCalculator.frequency_factor(mem, saturation_point=1)
        assert factor == 1.0

    def test_frequency_with_very_large_saturation(self) -> None:
        """Test frequency with very large saturation point."""
        mem = SemanticMemory(content="test", access_count=50)
        factor = SignalCalculator.frequency_factor(mem, saturation_point=10000)
        assert 0.0 < factor < 0.5

    def test_frequency_with_count_equals_saturation(self) -> None:
        """Test frequency when count exactly equals saturation."""
        mem = SemanticMemory(content="test", access_count=100)
        factor = SignalCalculator.frequency_factor(mem, saturation_point=100)
        assert factor == 1.0

    def test_frequency_with_very_high_count(self) -> None:
        """Test frequency with extremely high access count."""
        mem = SemanticMemory(content="test", access_count=1000000)
        factor = SignalCalculator.frequency_factor(mem, saturation_point=50)
        assert factor == 1.0


class TestImportanceFactorEdgeCases:
    """Test importance_factor edge cases."""

    def test_importance_with_zero(self) -> None:
        """Test importance with zero value."""
        mem = SemanticMemory(content="test", importance=0.0)
        factor = SignalCalculator.importance_factor(mem)
        assert factor == 0.0

    def test_importance_with_one(self) -> None:
        """Test importance with maximum value."""
        mem = SemanticMemory(content="test", importance=1.0)
        factor = SignalCalculator.importance_factor(mem)
        assert factor == 1.0


class TestPreferenceFactorEdgeCases:
    """Test preference_factor edge cases."""

    def test_preference_with_implicit_type(self) -> None:
        """Test preference with implicit preference type."""
        mem = SemanticMemory(content="test", preference_type="implicit", preference_strength=0.6)
        factor = SignalCalculator.preference_factor(mem)
        assert factor == 0.6


class TestConfidenceFactorEdgeCases:
    """Test confidence_factor edge cases."""

    def test_confidence_with_zero(self) -> None:
        """Test confidence with zero value."""
        mem = SemanticMemory(content="test", confidence=0.0)
        factor = SignalCalculator.confidence_factor(mem)
        assert factor == 0.0


class TestGetDefaultSignalWeightsEdgeCases:
    """Test get_default_signal_weights edge cases."""

    def test_weights_for_all_types(self) -> None:
        """Test that all memory types have defined weights."""
        for mem_type in MemoryType:
            weights = get_default_signal_weights(mem_type)
            assert isinstance(weights, dict)
            assert "semantic" in weights
            assert "recency" in weights
            assert "frequency" in weights
            assert "importance" in weights
            assert "preference" in weights

    def test_weights_semantic_dominance(self) -> None:
        """Test that semantic weight is dominant for SEMANTIC type."""
        weights = get_default_signal_weights(MemoryType.SEMANTIC)
        assert weights["semantic"] >= 0.6
        assert weights["semantic"] > weights["recency"]
        assert weights["semantic"] > weights["frequency"]
        assert weights["semantic"] > weights["importance"]

    def test_weights_profile_preference_high(self) -> None:
        """Test that preference weight is high for PROFILE type."""
        weights = get_default_signal_weights(MemoryType.PROFILE)
        assert weights["preference"] >= 0.3

    def test_weights_episodic_recency_high(self) -> None:
        """Test that recency weight is high for EPISODIC type."""
        weights = get_default_signal_weights(MemoryType.EPISODIC)
        assert weights["recency"] >= 0.2

    def test_weights_procedural_importance_high(self) -> None:
        """Test that importance weight is high for PROCEDURAL type."""
        weights = get_default_signal_weights(MemoryType.PROCEDURAL)
        assert weights["importance"] >= 0.4

    def test_weights_with_lowercase_type(self) -> None:
        """Test weights with lowercase memory type string."""

        class LowercaseType:
            def upper(self):
                return "SEMANTIC"

        weights = get_default_signal_weights(LowercaseType())
        assert weights == get_default_signal_weights(MemoryType.SEMANTIC)


class TestGetDefaultHalfLifeEdgeCases:
    """Test get_default_half_life edge cases."""

    def test_half_life_for_all_types(self) -> None:
        """Test that all memory types have defined half-lives."""
        for mem_type in MemoryType:
            half_life = get_default_half_life(mem_type)
            assert isinstance(half_life, float)
            assert half_life >= 0.0

    def test_half_life_profile_no_decay(self) -> None:
        """Test that PROFILE has no decay."""
        half_life = get_default_half_life(MemoryType.PROFILE)
        assert half_life == 0.0

    def test_half_life_procedural_no_decay(self) -> None:
        """Test that PROCEDURAL has no decay."""
        half_life = get_default_half_life(MemoryType.PROCEDURAL)
        assert half_life == 0.0

    def test_half_life_episodic_fast_decay(self) -> None:
        """Test that EPISODIC has faster decay than SEMANTIC."""
        epi_half_life = get_default_half_life(MemoryType.EPISODIC)
        sem_half_life = get_default_half_life(MemoryType.SEMANTIC)
        assert epi_half_life < sem_half_life

    def test_half_life_with_lowercase_type(self) -> None:
        """Test half-life with lowercase memory type string."""

        class LowercaseType:
            def upper(self):
                return "EPISODIC"

        half_life = get_default_half_life(LowercaseType())
        assert half_life == 7.0


class TestSignalCalculatorWithRealMemoryTypes:
    """Test SignalCalculator with all real memory types."""

    def test_all_signals_with_episodic_memory(self) -> None:
        """Test all signal calculations with EpisodicMemory."""
        mem = EpisodicMemory(
            content="test event", created_at=datetime.now(UTC) - timedelta(days=5), access_count=15, importance=0.7
        )

        recency = SignalCalculator.recency_factor(mem, half_life_days=7.0)
        frequency = SignalCalculator.frequency_factor(mem, saturation_point=50)
        importance = SignalCalculator.importance_factor(mem)
        preference = SignalCalculator.preference_factor(mem)
        confidence = SignalCalculator.confidence_factor(mem)

        assert 0.0 < recency <= 1.0
        assert 0.0 < frequency <= 1.0
        assert importance == 0.7
        assert preference == 0.0
        assert confidence == 1.0

    def test_all_signals_with_procedural_memory(self) -> None:
        """Test all signal calculations with ProceduralMemory."""
        mem = ProceduralMemory(
            content="test rule",
            trigger="when X",
            action="do Y",
            created_at=datetime.now(UTC) - timedelta(days=100),
            access_count=25,
            priority=1,
        )

        recency = SignalCalculator.recency_factor(mem, half_life_days=0.0)
        frequency = SignalCalculator.frequency_factor(mem, saturation_point=50)
        importance = SignalCalculator.importance_factor(mem)
        preference = SignalCalculator.preference_factor(mem)
        confidence = SignalCalculator.confidence_factor(mem)

        assert recency == 1.0
        assert 0.0 < frequency <= 1.0
        assert importance == 0.5
        assert preference == 0.0
        assert confidence == 1.0

    def test_all_signals_with_semantic_with_all_fields(self) -> None:
        """Test all signal calculations with SemanticMemory with all fields."""
        mem = SemanticMemory(
            content="test",
            created_at=datetime.now(UTC) - timedelta(days=15),
            access_count=20,
            importance=0.8,
            confidence=0.9,
            preference_type="explicit",
            preference_strength=0.7,
        )

        recency = SignalCalculator.recency_factor(mem, half_life_days=30.0)
        frequency = SignalCalculator.frequency_factor(mem, saturation_point=50)
        importance = SignalCalculator.importance_factor(mem)
        preference = SignalCalculator.preference_factor(mem)
        confidence = SignalCalculator.confidence_factor(mem)

        assert 0.5 < recency < 1.0
        assert 0.0 < frequency < 1.0
        assert importance == 0.8
        assert preference == 0.7
        assert confidence == 0.9


class TestSignalWeightsCompleteness:
    """Test that signal weights are complete and consistent."""

    def test_all_types_have_five_signals(self) -> None:
        """Test that all types define all five signals."""
        for mem_type in MemoryType:
            weights = get_default_signal_weights(mem_type)
            assert len(weights) == 6
            assert set(weights.keys()) == {"semantic", "recency", "frequency", "importance", "preference", "rating"}

    def test_weights_are_non_negative(self) -> None:
        """Test that all weights are non-negative."""
        for mem_type in MemoryType:
            weights = get_default_signal_weights(mem_type)
            for weight in weights.values():
                assert weight >= 0.0

    def test_weights_sum_exactly_to_one(self) -> None:
        """Test that weights sum to exactly 1.0 for all types."""
        for mem_type in MemoryType:
            weights = get_default_signal_weights(mem_type)
            total = sum(weights.values())
            assert abs(total - 1.0) < 0.001

    def test_profile_has_zero_recency(self) -> None:
        """Test that PROFILE has zero recency weight."""
        weights = get_default_signal_weights(MemoryType.PROFILE)
        assert weights["recency"] == 0.0

    def test_profile_has_zero_frequency(self) -> None:
        """Test that PROFILE has zero frequency weight."""
        weights = get_default_signal_weights(MemoryType.PROFILE)
        assert weights["frequency"] == 0.0

    def test_procedural_has_zero_recency(self) -> None:
        """Test that PROCEDURAL has zero recency weight."""
        weights = get_default_signal_weights(MemoryType.PROCEDURAL)
        assert weights["recency"] == 0.0

    def test_semantic_has_zero_preference(self) -> None:
        """Test that SEMANTIC has zero preference weight."""
        weights = get_default_signal_weights(MemoryType.SEMANTIC)
        assert weights["preference"] == 0.0

    def test_episodic_has_zero_preference(self) -> None:
        """Test that EPISODIC has zero preference weight."""
        weights = get_default_signal_weights(MemoryType.EPISODIC)
        assert weights["preference"] == 0.0

    def test_procedural_has_zero_preference(self) -> None:
        """Test that PROCEDURAL has zero preference weight."""
        weights = get_default_signal_weights(MemoryType.PROCEDURAL)
        assert weights["preference"] == 0.0


class TestHalfLifeCompleteness:
    """Test that half-life values are complete and consistent."""

    def test_all_types_have_half_life(self) -> None:
        """Test that all types have defined half-lives."""
        for mem_type in MemoryType:
            half_life = get_default_half_life(mem_type)
            assert isinstance(half_life, float)

    def test_half_life_non_negative(self) -> None:
        """Test that all half-lives are non-negative."""
        for mem_type in MemoryType:
            half_life = get_default_half_life(mem_type)
            assert half_life >= 0.0

    def test_stable_types_have_zero_half_life(self) -> None:
        """Test that stable memory types have zero half-life."""
        assert get_default_half_life(MemoryType.PROFILE) == 0.0
        assert get_default_half_life(MemoryType.PROCEDURAL) == 0.0

    def test_temporal_types_have_positive_half_life(self) -> None:
        """Test that temporal memory types have positive half-life."""
        assert get_default_half_life(MemoryType.SEMANTIC) > 0.0
        assert get_default_half_life(MemoryType.EPISODIC) > 0.0


class TestSignalCalculatorStaticMethods:
    """Test that SignalCalculator methods are truly static."""

    def test_recency_factor_is_static(self) -> None:
        """Test that recency_factor can be called without instance."""
        mem = SemanticMemory(content="test", created_at=datetime.now(UTC))
        factor = SignalCalculator.recency_factor(mem, half_life_days=7.0)
        assert 0.0 <= factor <= 1.0

    def test_frequency_factor_is_static(self) -> None:
        """Test that frequency_factor can be called without instance."""
        mem = SemanticMemory(content="test", access_count=10)
        factor = SignalCalculator.frequency_factor(mem, saturation_point=50)
        assert 0.0 <= factor <= 1.0

    def test_importance_factor_is_static(self) -> None:
        """Test that importance_factor can be called without instance."""
        mem = SemanticMemory(content="test", importance=0.7)
        factor = SignalCalculator.importance_factor(mem)
        assert factor == 0.7

    def test_preference_factor_is_static(self) -> None:
        """Test that preference_factor can be called without instance."""
        mem = SemanticMemory(content="test", preference_type="explicit", preference_strength=0.8)
        factor = SignalCalculator.preference_factor(mem)
        assert factor == 0.8

    def test_confidence_factor_is_static(self) -> None:
        """Test that confidence_factor can be called without instance."""
        mem = SemanticMemory(content="test", confidence=0.9)
        factor = SignalCalculator.confidence_factor(mem)
        assert factor == 0.9
