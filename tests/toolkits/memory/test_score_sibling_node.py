"""Tests for _score_sibling_node scoring formula.

Covers all 5 scoring factors: token overlap, distance decay, freshness, importance, channel affinity.
Plus boundary conditions: empty tokens, zero overlap, score capping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance_enrichment import (
    _score_sibling_node,
)


_NOW = datetime(2026, 8, 1, tzinfo=UTC)


class TestTokenOverlap:
    """Token overlap is the base scoring factor."""

    def test_zero_overlap_returns_zero(self):
        score = _score_sibling_node(
            query_tokens={"python", "rust"},
            content="java and typescript",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        assert score == 0.0

    def test_single_token_overlap(self):
        score = _score_sibling_node(
            query_tokens={"python", "rust"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        # base = min(0.55 + 1*0.08, 0.88) = 0.63, * decay^0 = 0.63, * (0.7+0.3*0.5)=0.85 → 0.5355
        assert 0.4 < score < 0.7

    def test_multiple_token_overlap_increases_score(self):
        score_one = _score_sibling_node(
            query_tokens={"python", "rust", "tutorial"},
            content="python guide",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        score_two = _score_sibling_node(
            query_tokens={"python", "rust", "tutorial"},
            content="python rust comparison",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        assert score_two > score_one

    def test_empty_query_tokens_returns_zero(self):
        score = _score_sibling_node(
            query_tokens=set(),
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        assert score == 0.0

    def test_score_capped_at_095(self):
        """Even with all boosts maximized, score must not exceed 0.95."""
        score = _score_sibling_node(
            query_tokens={"a", "b", "c", "d", "e", "f"},
            content="a b c d e f g h i j",
            depth=1, distance_decay=1.0, importance=1.0,
            created_at=_NOW - timedelta(days=1),
            current_channel_id="ch1", channel_id="ch1", now=_NOW,
        )
        assert score <= 0.95


class TestDistanceDecay:
    """Deeper nodes get lower scores via distance_decay^(depth-1)."""

    def test_depth_1_no_decay(self):
        score = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        score_no_decay = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=1.0, importance=0.5,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        assert score == score_no_decay

    def test_depth_2_applies_decay(self):
        score_d1 = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        score_d2 = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=2, distance_decay=0.5, importance=0.5,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        assert score_d2 < score_d1
        assert pytest.approx(score_d2 / score_d1, rel=0.05) == 0.5


class TestFreshness:
    """Freshness boosts: fresh(≤7d) +0.08, aging(8-30d) +0.04, stale(>30d) +0."""

    def test_fresh_memory_gets_boost(self):
        score_fresh = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=_NOW - timedelta(days=3), current_channel_id=None, channel_id=None, now=_NOW,
        )
        score_none = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        assert score_fresh > score_none

    def test_aging_memory_gets_smaller_boost(self):
        score_aging = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=_NOW - timedelta(days=15), current_channel_id=None, channel_id=None, now=_NOW,
        )
        score_fresh = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=_NOW - timedelta(days=3), current_channel_id=None, channel_id=None, now=_NOW,
        )
        assert score_aging < score_fresh

    def test_stale_memory_no_boost(self):
        score_stale = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=_NOW - timedelta(days=60), current_channel_id=None, channel_id=None, now=_NOW,
        )
        score_none = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        # Stale gets freshness boost of 0.0, but importance modulation applies after freshness
        # Both should be very close (stale may differ slightly due to order of operations)
        assert abs(score_stale - score_none) < 0.01


class TestImportance:
    """Importance modulation: score *= 0.7 + 0.3 * clamp(importance, 0, 1)."""

    def test_high_importance_scores_higher(self):
        score_high = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=1.0,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        score_low = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.0,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        assert score_high > score_low

    def test_negative_importance_clamped_to_zero(self):
        score_neg = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=-0.5,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        score_zero = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.0,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        assert score_neg == score_zero

    def test_importance_above_1_clamped(self):
        score_over = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=2.0,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        score_one = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=1.0,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        assert score_over == score_one


class TestChannelAffinity:
    """Same channel gets +0.06 boost."""

    def test_same_channel_gets_boost(self):
        score_same = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=None, current_channel_id="ch1", channel_id="ch1", now=_NOW,
        )
        score_diff = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=None, current_channel_id="ch1", channel_id="ch2", now=_NOW,
        )
        assert score_same > score_diff
        assert pytest.approx(score_same - score_diff, abs=0.001) == 0.06

    def test_no_channel_no_boost(self):
        score_none = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=None, current_channel_id=None, channel_id=None, now=_NOW,
        )
        score_diff = _score_sibling_node(
            query_tokens={"python"},
            content="python tutorial",
            depth=1, distance_decay=0.5, importance=0.5,
            created_at=None, current_channel_id="ch1", channel_id="ch2", now=_NOW,
        )
        assert score_none == score_diff
