"""Tests for evaluation decontamination helpers."""

from __future__ import annotations

from myrm_agent_harness.eval import (
    HUGGINGFACE_DOMAINS,
    HUGGINGFACE_QUERY_MARKERS,
    normalize_answer,
)


class TestNormalizeAnswer:
    def test_lowercase_and_whitespace(self) -> None:
        assert normalize_answer("  Hello   World  ") == "hello world"

    def test_punctuation_stripped(self) -> None:
        assert normalize_answer("El Niño: 4.2%") == "el niño 4 dot 2"

    def test_unicode_normalized(self) -> None:
        assert normalize_answer("ｆｕｌｌｗｉｄｔｈ") == "fullwidth"

    def test_equivalent_spellings_collapse(self) -> None:
        assert normalize_answer("Berlin, Germany") == normalize_answer("berlin germany")

    def test_decimal_never_collapses_into_integer(self) -> None:
        assert normalize_answer("42.5") != normalize_answer("425")
        assert normalize_answer("3.14") != normalize_answer("314")

    def test_whole_number_decimal_folds(self) -> None:
        assert normalize_answer("42.0") == normalize_answer("42")
        assert normalize_answer("2.0") == normalize_answer("2")

    def test_trailing_decimal_zeros_fold(self) -> None:
        assert normalize_answer("42.50") == normalize_answer("42.5")
        assert normalize_answer("3.140") == normalize_answer("3.14")
        assert normalize_answer("42.050") == normalize_answer("42.05")

    def test_distinct_decimals_stay_distinct(self) -> None:
        assert normalize_answer("42.05") != normalize_answer("42.5")
        assert normalize_answer("v2.5.1") != normalize_answer("v251")

    def test_sentence_final_period_keeps_matching(self) -> None:
        assert normalize_answer("The answer is 42.") == normalize_answer(
            "the answer is 42"
        )
        assert normalize_answer("2024.") == normalize_answer("2024")
        assert normalize_answer("Apple, Inc.") == normalize_answer("apple inc")


class TestPublicConstants:
    def test_domains_cover_both_hosts(self) -> None:
        assert "huggingface.co" in HUGGINGFACE_DOMAINS
        assert "*.huggingface.co" in HUGGINGFACE_DOMAINS
        assert "hf.co" in HUGGINGFACE_DOMAINS

    def test_query_markers_are_lowercase_terms(self) -> None:
        assert all(marker == marker.lower() for marker in HUGGINGFACE_QUERY_MARKERS)
        assert HUGGINGFACE_QUERY_MARKERS


def test_normalize_roundtrip() -> None:
    """Smoke: helper is importable from the eval package namespace."""
    assert normalize_answer("A") == "a"
