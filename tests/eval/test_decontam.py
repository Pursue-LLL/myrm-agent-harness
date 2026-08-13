"""Tests for evaluation decontamination helpers."""

from __future__ import annotations

import pytest

from myrm_agent_harness.eval import (
    HUGGINGFACE_DOMAINS,
    HUGGINGFACE_QUERY_MARKERS,
    is_huggingface_url,
    normalize_answer,
    query_targets_huggingface,
)


class TestIsHuggingfaceUrl:
    def test_canonical_domain(self) -> None:
        assert is_huggingface_url("https://huggingface.co/models")

    def test_short_alias(self) -> None:
        assert is_huggingface_url("https://hf.co/datasets/foo")

    def test_subdomain(self) -> None:
        assert is_huggingface_url("https://datasets-server.huggingface.co/rows")

    def test_www_prefix(self) -> None:
        assert is_huggingface_url("https://www.huggingface.co/papers")

    def test_non_hf_host_rejected(self) -> None:
        assert not is_huggingface_url("https://example.com/huggingface")

    def test_lookalike_rejected(self) -> None:
        assert not is_huggingface_url("https://huggingface.co.evil.com/x")

    def test_empty_url_rejected(self) -> None:
        assert not is_huggingface_url("")


class TestQueryTargetsHuggingface:
    def test_plain_mention(self) -> None:
        assert query_targets_huggingface("find the model card on huggingface")

    def test_short_alias_mention(self) -> None:
        assert query_targets_huggingface("search hf.co for the dataset")

    def test_case_insensitive(self) -> None:
        assert query_targets_huggingface("Hugging Face leaderboard")

    def test_unrelated_query_rejected(self) -> None:
        assert not query_targets_huggingface("top chess openings 2026")

    def test_false_fragment_rejected(self) -> None:
        assert not query_targets_huggingface("hugging and facing the mirror")


class TestNormalizeAnswer:
    def test_lowercase_and_whitespace(self) -> None:
        assert normalize_answer("  Hello   World  ") == "hello world"

    def test_punctuation_stripped(self) -> None:
        assert normalize_answer("El Niño: 4.2%") == "el niño 42"

    def test_unicode_normalized(self) -> None:
        assert normalize_answer("ｆｕｌｌｗｉｄｔｈ") == "fullwidth"

    def test_equivalent_spellings_collapse(self) -> None:
        assert normalize_answer("Berlin, Germany") == normalize_answer("berlin germany")


class TestPublicConstants:
    def test_domains_cover_both_hosts(self) -> None:
        assert "huggingface.co" in HUGGINGFACE_DOMAINS
        assert "*.huggingface.co" in HUGGINGFACE_DOMAINS
        assert "hf.co" in HUGGINGFACE_DOMAINS

    def test_query_markers_align_with_detector(self) -> None:
        for marker in HUGGINGFACE_QUERY_MARKERS:
            assert query_targets_huggingface(f"look up {marker} data")


def test_detector_and_normalize_roundtrip() -> None:
    """Smoke: helpers are importable from the eval package namespace."""
    assert is_huggingface_url("https://hf.co/x")
    assert normalize_answer("A") == "a"
