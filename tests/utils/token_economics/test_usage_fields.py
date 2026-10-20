"""Provider cache-field extraction: one payload must yield one interpretation.

Cost computation and ``TokenTracker`` both read these helpers, so a provider that
reports the same cache quantity under a different key must be counted identically
by both — otherwise the billed cost and the reported cache hit rate disagree.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.utils.token_economics.usage_fields import (
    extract_cache_write_tokens,
    extract_cached_tokens,
    extract_cost_tokens,
)


class TestExtractCachedTokens:
    def test_reads_prompt_tokens_details(self) -> None:
        usage = {"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 40}}

        assert extract_cached_tokens(usage) == 40

    def test_accepts_top_level_cache_read_alias(self) -> None:
        assert extract_cached_tokens({"cache_read_tokens": 25}) == 25

    def test_accepts_anthropic_cache_read_field(self) -> None:
        assert extract_cached_tokens({"cache_read_input_tokens": 12}) == 12

    def test_details_win_over_top_level_alias(self) -> None:
        usage = {"cache_read_tokens": 5, "prompt_tokens_details": {"cached_tokens": 90}}

        assert extract_cached_tokens(usage) == 90

    def test_zero_and_missing_keys_yield_zero(self) -> None:
        assert extract_cached_tokens({}) == 0
        assert extract_cached_tokens({"prompt_tokens_details": {"cached_tokens": 0}}) == 0

    def test_rejects_negative_and_non_numeric(self) -> None:
        assert extract_cached_tokens({"cache_read_tokens": -5}) == 0
        assert extract_cached_tokens({"cache_read_tokens": "many"}) == 0


class TestExtractCacheWriteTokens:
    def test_reads_anthropic_creation_field(self) -> None:
        assert extract_cache_write_tokens({"cache_creation_input_tokens": 30}) == 30

    def test_reads_litellm_cache_write_alias(self) -> None:
        assert extract_cache_write_tokens({"cache_write_tokens": 18}) == 18

    def test_falls_back_to_prompt_details(self) -> None:
        usage = {"prompt_tokens_details": {"cache_creation_input_tokens": 7}}

        assert extract_cache_write_tokens(usage) == 7

    def test_missing_yields_zero(self) -> None:
        assert extract_cache_write_tokens({"prompt_tokens": 10}) == 0


class TestExtractCostTokens:
    def test_returns_four_counters_in_order(self) -> None:
        usage = {
            "prompt_tokens": 200,
            "completion_tokens": 50,
            "prompt_tokens_details": {"cached_tokens": 120, "cache_creation_input_tokens": 8},
        }

        assert extract_cost_tokens(usage) == pytest.approx((200, 50, 120, 8))

    def test_empty_usage_is_all_zero(self) -> None:
        assert extract_cost_tokens({}) == (0, 0, 0, 0)

    def test_agrees_with_the_individual_readers(self) -> None:
        usage = {"prompt_tokens": 10, "cache_read_tokens": 4, "cache_write_tokens": 2}

        prompt, completion, cached, written = extract_cost_tokens(usage)
        assert cached == extract_cached_tokens(usage)
        assert written == extract_cache_write_tokens(usage)
        assert (prompt, completion) == (10, 0)
