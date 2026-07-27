"""Tests for zero-dependency English token normalization."""

from __future__ import annotations

from myrm_agent_harness.toolkits.retriever.bm25.english_normalizer import (
    normalize_english_token,
    normalize_english_tokens,
)


def test_stopwords_return_none() -> None:
    assert normalize_english_token("the") is None
    assert normalize_english_token("FOR") is None


def test_suffix_normalization_golden_cases() -> None:
    assert normalize_english_token("running") == "run"
    assert normalize_english_token("jumped") == "jump"
    assert normalize_english_token("learning") == "learn"
    assert normalize_english_token("programming") == "program"
    assert normalize_english_token("authentication") == "authentication"


def test_plural_and_status_tokens_are_not_over_stripped() -> None:
    """Skill-adjacent tokens like status/alias must remain exact for BM25 recall."""
    assert normalize_english_token("status") == "status"
    assert normalize_english_token("alias") == "alias"
    assert normalize_english_token("boxes") == "boxes"
    assert normalize_english_token("business") == "business"


def test_batch_preserves_order_and_filters_stopwords() -> None:
    tokens = normalize_english_tokens(["The", "quick", "fox", "jumping"])
    assert tokens == ["quick", "fox", "jump"]


def test_empty_token_skipped() -> None:
    assert normalize_english_tokens(["", "  ", "valid"]) == ["valid"]
