"""Tests for toolkits.llms.fallback.recommendations — fallback model recommendations."""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.fallback.recommendations import (
    FALLBACK_RECOMMENDATIONS,
    FallbackRecommendation,
    generate_quantified_reason,
    get_primary_recommendation,
    recommend_fallback,
)


class TestRecommendFallback:
    def test_known_model(self) -> None:
        recs = recommend_fallback("gpt-4o")
        assert len(recs) >= 1
        assert all(isinstance(r, FallbackRecommendation) for r in recs)

    def test_unknown_model_empty(self) -> None:
        recs = recommend_fallback("unknown-model-xyz")
        assert recs == []

    def test_primary_only(self) -> None:
        recs = recommend_fallback("gpt-4o", include_secondary=False)
        assert all(r.is_primary for r in recs)

    def test_includes_secondary(self) -> None:
        recs = recommend_fallback("gpt-4o", include_secondary=True)
        has_secondary = any(not r.is_primary for r in recs)
        assert has_secondary


class TestGetPrimaryRecommendation:
    def test_known_model(self) -> None:
        rec = get_primary_recommendation("gpt-4o")
        assert rec is not None
        assert rec.is_primary

    def test_unknown_model(self) -> None:
        rec = get_primary_recommendation("unknown-model")
        assert rec is None


class TestGenerateQuantifiedReason:
    def test_cost_reduction(self) -> None:
        rec = FallbackRecommendation("m", "Lower cost", cost_factor=0.1)
        result = generate_quantified_reason(rec)
        assert "cost reduction" in result

    def test_cost_increase(self) -> None:
        rec = FallbackRecommendation("m", "Higher cost", cost_factor=1.5)
        result = generate_quantified_reason(rec)
        assert "cost increase" in result

    def test_latency_improvement(self) -> None:
        rec = FallbackRecommendation("m", "Faster", latency_factor=0.8)
        result = generate_quantified_reason(rec)
        assert "latency improvement" in result

    def test_latency_increase(self) -> None:
        rec = FallbackRecommendation("m", "Slower", latency_factor=1.2)
        result = generate_quantified_reason(rec)
        assert "latency increase" in result

    def test_quality_tradeoff(self) -> None:
        rec = FallbackRecommendation("m", "Lower quality", quality_factor=0.7)
        result = generate_quantified_reason(rec)
        assert "quality trade-off" in result

    def test_quality_improvement(self) -> None:
        rec = FallbackRecommendation("m", "Better", quality_factor=1.3)
        result = generate_quantified_reason(rec)
        assert "quality improvement" in result

    def test_no_metrics(self) -> None:
        rec = FallbackRecommendation("m", "Same everything")
        result = generate_quantified_reason(rec)
        assert result == "Same everything"

    def test_combined_metrics(self) -> None:
        rec = FallbackRecommendation("m", "Trade-off", cost_factor=0.5, latency_factor=0.9, quality_factor=0.8)
        result = generate_quantified_reason(rec)
        assert "cost reduction" in result
        assert "latency improvement" in result
        assert "quality trade-off" in result


class TestFallbackRecommendationsData:
    def test_all_entries_have_recommendations(self) -> None:
        for model, recs in FALLBACK_RECOMMENDATIONS.items():
            assert len(recs) >= 1, f"Model {model} has no recommendations"
            assert any(r.is_primary for r in recs), f"Model {model} has no primary recommendation"
