"""Tests for score-discontinuity autocut algorithm."""

import pytest

from myrm_agent_harness.toolkits.retriever.autocut import (
    AutocutConfig,
    AutocutDecision,
    apply_autocut,
)


class TestAutocutConfig:
    """Test AutocutConfig dataclass."""

    def test_defaults(self):
        config = AutocutConfig()
        assert config.enabled is True
        assert config.jump_ratio == 0.2
        assert config.min_keep == 1

    def test_custom_values(self):
        config = AutocutConfig(enabled=False, jump_ratio=0.5, min_keep=3)
        assert config.enabled is False
        assert config.jump_ratio == 0.5
        assert config.min_keep == 3

    def test_frozen(self):
        config = AutocutConfig()
        with pytest.raises(AttributeError):
            config.enabled = False  # type: ignore[misc]


class TestAutocutDecision:
    """Test AutocutDecision dataclass."""

    def test_no_cut(self):
        decision = AutocutDecision(original_count=5, kept_count=5)
        assert not decision.was_cut
        assert decision.cut_index is None
        assert decision.max_gap is None

    def test_with_cut(self):
        decision = AutocutDecision(original_count=10, kept_count=3, cut_index=3, max_gap=0.45)
        assert decision.was_cut
        assert decision.cut_index == 3
        assert decision.max_gap == 0.45


class TestApplyAutocut:
    """Test apply_autocut core algorithm."""

    def test_clear_gap_triggers_cut(self):
        """Obvious score gap: [0.92, 0.88, 0.15, 0.12] → keep 2."""
        scores = [0.92, 0.88, 0.15, 0.12]
        decision = apply_autocut(scores)
        assert decision.was_cut
        assert decision.kept_count == 2
        assert decision.cut_index == 2
        assert decision.max_gap is not None
        assert decision.max_gap > 0.2

    def test_no_gap_keeps_all(self):
        """Uniform scores: [0.85, 0.82, 0.80, 0.78] → keep all."""
        scores = [0.85, 0.82, 0.80, 0.78]
        decision = apply_autocut(scores)
        assert not decision.was_cut
        assert decision.kept_count == 4

    def test_empty_scores(self):
        """Empty list → no-op."""
        decision = apply_autocut([])
        assert not decision.was_cut
        assert decision.kept_count == 0

    def test_single_score(self):
        """Single score → no-op (min_keep=1)."""
        decision = apply_autocut([0.95])
        assert not decision.was_cut
        assert decision.kept_count == 1

    def test_disabled_config(self):
        """Disabled config → no-op."""
        scores = [0.92, 0.88, 0.15, 0.12]
        config = AutocutConfig(enabled=False)
        decision = apply_autocut(scores, config)
        assert not decision.was_cut
        assert decision.kept_count == 4

    def test_none_config_uses_defaults(self):
        """None config → uses default config."""
        scores = [0.92, 0.88, 0.15, 0.12]
        decision = apply_autocut(scores, None)
        assert decision.was_cut
        assert decision.kept_count == 2

    def test_min_keep_respected(self):
        """Even with a huge gap at index 1, min_keep=3 prevents cutting below 3."""
        scores = [0.95, 0.10, 0.08, 0.05]
        config = AutocutConfig(min_keep=3)
        decision = apply_autocut(scores, config)
        if decision.was_cut:
            assert decision.kept_count >= 3

    def test_min_keep_1_allows_cut_at_index_1(self):
        """Gap at index 1 with min_keep=1: [0.95, 0.10] → keep 1."""
        scores = [0.95, 0.10]
        config = AutocutConfig(min_keep=1)
        decision = apply_autocut(scores, config)
        assert decision.was_cut
        assert decision.kept_count == 1

    def test_high_jump_ratio_suppresses_cut(self):
        """High jump_ratio makes it harder to trigger autocut."""
        scores = [0.92, 0.88, 0.65, 0.63]
        config = AutocutConfig(jump_ratio=0.5)
        decision = apply_autocut(scores, config)
        assert not decision.was_cut
        assert decision.kept_count == 4

    def test_low_jump_ratio_triggers_more_cuts(self):
        """Low jump_ratio makes even small gaps trigger autocut."""
        scores = [0.92, 0.88, 0.65, 0.63]
        config = AutocutConfig(jump_ratio=0.1)
        decision = apply_autocut(scores, config)
        assert decision.was_cut
        assert decision.kept_count == 2

    def test_multiple_gaps_finds_largest(self):
        """Multiple gaps: largest gap wins."""
        scores = [0.95, 0.90, 0.40, 0.38, 0.10, 0.08]
        decision = apply_autocut(scores)
        assert decision.was_cut
        assert decision.kept_count == 2  # gap at index 2 is largest

    def test_gap_at_end_is_detected(self):
        """Gap at the very end: [0.90, 0.88, 0.86, 0.10] → keep 3."""
        scores = [0.90, 0.88, 0.86, 0.10]
        decision = apply_autocut(scores)
        assert decision.was_cut
        assert decision.kept_count == 3

    def test_all_zero_scores(self):
        """All zeros → no-op (max_score <= 0)."""
        scores = [0.0, 0.0, 0.0]
        decision = apply_autocut(scores)
        assert not decision.was_cut
        assert decision.kept_count == 3

    def test_negative_scores(self):
        """Negative max score → no-op."""
        scores = [-0.1, -0.5, -0.9]
        decision = apply_autocut(scores)
        assert not decision.was_cut
        assert decision.kept_count == 3

    def test_identical_scores(self):
        """All identical scores → no gap → no cut."""
        scores = [0.75, 0.75, 0.75, 0.75]
        decision = apply_autocut(scores)
        assert not decision.was_cut
        assert decision.kept_count == 4

    def test_gradual_decline_no_cut(self):
        """Gradual decline without cliff: [0.90, 0.85, 0.80, 0.75, 0.70]."""
        scores = [0.90, 0.85, 0.80, 0.75, 0.70]
        decision = apply_autocut(scores)
        assert not decision.was_cut
        assert decision.kept_count == 5

    def test_realistic_web_search_scores(self):
        """Realistic web search scenario with clear relevance cluster."""
        scores = [0.93, 0.91, 0.87, 0.22, 0.18, 0.15, 0.12, 0.09, 0.05, 0.03]
        decision = apply_autocut(scores)
        assert decision.was_cut
        assert decision.kept_count == 3
        assert decision.original_count == 10

    def test_decision_metadata_correctness(self):
        """Verify all metadata fields are correct."""
        scores = [0.92, 0.88, 0.15, 0.12, 0.08]
        decision = apply_autocut(scores)
        assert decision.original_count == 5
        assert decision.kept_count == 2
        assert decision.cut_index == 2
        assert decision.max_gap is not None
        assert 0.7 < decision.max_gap < 0.85  # (0.88-0.15)/0.92 ≈ 0.79

    def test_two_results_with_small_gap(self):
        """Two results with small gap → no cut."""
        scores = [0.88, 0.82]
        decision = apply_autocut(scores)
        assert not decision.was_cut
        assert decision.kept_count == 2

    def test_preserves_order_semantics(self):
        """Verify the algorithm assumes descending order."""
        scores = [0.95, 0.93, 0.91, 0.20, 0.18]
        decision = apply_autocut(scores)
        assert decision.was_cut
        assert decision.kept_count == 3
