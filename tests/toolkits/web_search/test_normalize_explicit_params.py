"""Unit tests for _normalize_explicit_params in engine.py.

Covers:
- Volcengine Doubao: time_range mapping, custom date range, AuthInfoLevel
- SearxNG: time_range passthrough
- Tavily: time_range → days conversion
- Edge cases: empty params, None values, unknown providers
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.web_search.engine import (
    _normalize_explicit_params,
    _tavily_time_range_to_days,
)


class TestNormalizeExplicitParamsVolcengine:
    """Volcengine Doubao provider normalization."""

    @pytest.mark.parametrize(
        "time_range,expected_volcengine",
        [
            ("day", "OneDay"),
            ("week", "OneWeek"),
            ("month", "OneMonth"),
            ("year", "OneYear"),
        ],
    )
    def test_standard_time_ranges(self, time_range: str, expected_volcengine: str):
        result = _normalize_explicit_params(
            {"time_range": time_range},
            "volcengine_doubao",
        )
        assert result is not None
        assert result["TimeRange"] == expected_volcengine

    def test_custom_date_range_passed_to_volcengine(self):
        """Volcengine supports custom date ranges (YYYY-MM-DD..YYYY-MM-DD)."""
        result = _normalize_explicit_params(
            {"time_range": "2025-01-01..2025-06-30"},
            "volcengine_doubao",
        )
        assert result is not None
        assert result["TimeRange"] == "2025-01-01..2025-06-30"

    def test_source_authority_high(self):
        result = _normalize_explicit_params(
            {"source_authority": "high"},
            "volcengine_doubao",
        )
        assert result is not None
        assert result["AuthInfoLevel"] == 1
        assert isinstance(result["AuthInfoLevel"], int)

    def test_combined_time_range_and_authority(self):
        result = _normalize_explicit_params(
            {"time_range": "week", "source_authority": "high"},
            "volcengine_doubao",
        )
        assert result is not None
        assert result["TimeRange"] == "OneWeek"
        assert result["AuthInfoLevel"] == 1

    def test_source_authority_any_not_applied(self):
        result = _normalize_explicit_params(
            {"source_authority": "any"},
            "volcengine_doubao",
        )
        assert result is None

    def test_unknown_time_range_without_dots_ignored(self):
        result = _normalize_explicit_params(
            {"time_range": "unknown_value"},
            "volcengine_doubao",
        )
        assert result is None


class TestNormalizeExplicitParamsSearxng:
    """SearxNG provider normalization."""

    def test_time_range_passthrough(self):
        result = _normalize_explicit_params(
            {"time_range": "week"},
            "searxng",
        )
        assert result is not None
        assert result["time_range"] == "week"

    def test_source_authority_not_supported(self):
        result = _normalize_explicit_params(
            {"source_authority": "high"},
            "searxng",
        )
        assert result is None


class TestNormalizeExplicitParamsTavily:
    """Tavily provider normalization."""

    @pytest.mark.parametrize(
        "time_range,expected_days",
        [
            ("day", "1"),
            ("week", "7"),
            ("month", "30"),
            ("year", "365"),
        ],
    )
    def test_time_range_to_days(self, time_range: str, expected_days: str):
        result = _normalize_explicit_params(
            {"time_range": time_range},
            "tavily",
        )
        assert result is not None
        assert result["days"] == expected_days

    def test_unknown_time_range_defaults_to_7(self):
        result = _normalize_explicit_params(
            {"time_range": "custom_unknown"},
            "tavily",
        )
        assert result is not None
        assert result["days"] == "7"


class TestNormalizeExplicitParamsEdgeCases:
    """Edge cases and error handling."""

    def test_empty_dict_returns_none(self):
        result = _normalize_explicit_params({}, "volcengine_doubao")
        assert result is None

    def test_none_values_returns_none(self):
        result = _normalize_explicit_params(
            {"time_range": None, "source_authority": None},
            "volcengine_doubao",
        )
        assert result is None

    def test_empty_string_time_range_returns_none(self):
        result = _normalize_explicit_params(
            {"time_range": ""},
            "volcengine_doubao",
        )
        assert result is None


class TestTavilyTimeRangeToDays:
    """Direct test for _tavily_time_range_to_days helper."""

    def test_known_values(self):
        assert _tavily_time_range_to_days("day") == "1"
        assert _tavily_time_range_to_days("week") == "7"
        assert _tavily_time_range_to_days("month") == "30"
        assert _tavily_time_range_to_days("year") == "365"

    def test_unknown_defaults_to_7(self):
        assert _tavily_time_range_to_days("quarter") == "7"
