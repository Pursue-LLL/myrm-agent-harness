"""Unit tests for explicit param normalization (_explicit_params.py).

Covers:
- Volcengine Doubao: time_range mapping, custom date range
- SearxNG: time_range passthrough
- Tavily: time_range → days conversion
- Edge cases: empty params, None values, unknown providers
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.web_search._explicit_params import (
    apply_tavily_site_constraint,
    normalize_explicit_params,
    tavily_time_range_to_days,
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
        result = normalize_explicit_params(
            {"time_range": time_range},
            "volcengine_doubao",
        )
        assert result is not None
        assert result["TimeRange"] == expected_volcengine

    def test_custom_date_range_passed_to_volcengine(self):
        """Volcengine supports custom date ranges (YYYY-MM-DD..YYYY-MM-DD)."""
        result = normalize_explicit_params(
            {"time_range": "2025-01-01..2025-06-30"},
            "volcengine_doubao",
        )
        assert result is not None
        assert result["TimeRange"] == "2025-01-01..2025-06-30"

    def test_unknown_time_range_without_dots_ignored(self):
        result = normalize_explicit_params(
            {"time_range": "unknown_value"},
            "volcengine_doubao",
        )
        assert result is None


class TestNormalizeExplicitParamsSearxng:
    """SearxNG provider normalization."""

    def test_time_range_passthrough(self):
        result = normalize_explicit_params(
            {"time_range": "week"},
            "searxng",
        )
        assert result is not None
        assert result["time_range"] == "week"


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
        result = normalize_explicit_params(
            {"time_range": time_range},
            "tavily",
        )
        assert result is not None
        assert result["days"] == expected_days

    def test_unknown_time_range_defaults_to_7(self):
        result = normalize_explicit_params(
            {"time_range": "custom_unknown"},
            "tavily",
        )
        assert result is not None
        assert result["days"] == "7"

    def test_custom_date_range_computes_day_span(self):
        result = normalize_explicit_params(
            {"time_range": "2025-01-01..2025-06-30"},
            "tavily",
        )
        assert result is not None
        assert result["days"] == "181"


class TestNormalizeExplicitParamsEdgeCases:
    """Edge cases and error handling."""

    def test_empty_dict_returns_none(self):
        result = normalize_explicit_params({}, "volcengine_doubao")
        assert result is None

    def test_none_values_returns_none(self):
        result = normalize_explicit_params(
            {"time_range": None},
            "volcengine_doubao",
        )
        assert result is None

    def test_empty_string_time_range_returns_none(self):
        result = normalize_explicit_params(
            {"time_range": ""},
            "volcengine_doubao",
        )
        assert result is None


class TestTavilyTimeRangeToDays:
    """Direct tests for tavily_time_range_to_days helper."""

    def test_known_values(self):
        assert tavily_time_range_to_days("day") == "1"
        assert tavily_time_range_to_days("week") == "7"
        assert tavily_time_range_to_days("month") == "30"
        assert tavily_time_range_to_days("year") == "365"

    def test_unknown_defaults_to_7(self):
        assert tavily_time_range_to_days("quarter") == "7"

    def test_custom_date_range_span(self):
        assert tavily_time_range_to_days("2025-01-01..2025-06-30") == "181"

    def test_invalid_custom_date_range_defaults_to_7(self):
        assert tavily_time_range_to_days("not-a-date..also-bad") == "7"

    def test_inverted_custom_date_range_defaults_to_7(self):
        assert tavily_time_range_to_days("2025-06-30..2025-01-01") == "7"


class TestTavilySiteConstraint:
    def test_extracts_domain_filter_and_cleans_query(self):
        cleaned, override = apply_tavily_site_constraint(
            "site:gov.cn 数字经济 政策",
            None,
        )
        assert cleaned == "数字经济 政策"
        assert override is not None
        assert override["search_domain_filter"] == ["gov.cn"]

    def test_preserves_existing_override(self):
        cleaned, override = apply_tavily_site_constraint(
            "site:github.com rust async",
            {"days": "7"},
        )
        assert cleaned == "rust async"
        assert override == {"days": "7", "search_domain_filter": ["github.com"]}

    def test_merges_existing_domain_filter_list(self):
        cleaned, override = apply_tavily_site_constraint(
            "site:gov.cn policy",
            {"search_domain_filter": ["example.com"]},
        )
        assert cleaned == "policy"
        assert override is not None
        assert override["search_domain_filter"] == ["example.com", "gov.cn"]

    def test_no_site_operator_passthrough(self):
        query = "python asyncio tutorial"
        cleaned, override = apply_tavily_site_constraint(query, {"days": "30"})
        assert cleaned == query
        assert override == {"days": "30"}

    def test_site_only_query_keeps_original(self):
        query = "site:gov.cn"
        cleaned, override = apply_tavily_site_constraint(query, None)
        assert cleaned == query
        assert override is not None
        assert override["search_domain_filter"] == ["gov.cn"]
