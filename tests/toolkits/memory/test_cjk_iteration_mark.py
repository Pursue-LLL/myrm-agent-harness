"""Tests for CJK ideographic iteration mark disambiguation and recall suite."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.cjk_iteration_mark import (
    CjkIterationMarkFacade,
    CjkIterationRecallMatcher,
    IterationMarkResolver,
    get_cjk_iteration_mark_facade,
)


def test_resolve_single_iteration_mark_expansion() -> None:
    """Ensure standard words like '人々', '日々', '佐々木' expand correctly."""
    resolver = IterationMarkResolver()

    # People / hitobito
    res1 = resolver.resolve("人々の幸福")
    assert res1.has_iteration_mark is True
    assert res1.marks_expanded_count == 1
    assert res1.normalized_text == "人人の幸福"
    assert "人々" in res1.tokens.raw_tokens
    assert "人人" in res1.tokens.normalized_tokens
    assert "人人" in res1.tokens.anchor_tokens

    # Daily / hibi
    res2 = resolver.resolve("日々の暮らし")
    assert res2.normalized_text == "日日の暮らし"

    # Proper name Sasaki
    res3 = resolver.resolve("佐々木先生")
    assert res3.normalized_text == "佐佐木先生"
    assert "佐々" in res3.tokens.raw_tokens
    assert "佐佐" in res3.tokens.normalized_tokens


def test_resolve_chained_iteration_marks() -> None:
    """Ensure chained iteration marks resolve antecedent Han characters sequentially."""
    resolver = IterationMarkResolver()

    # "人人々々" -> "人人人人"
    res = resolver.resolve("街には人人々々が溢れる")
    assert res.has_iteration_mark is True
    assert res.marks_expanded_count == 2
    assert res.normalized_text == "街には人人人人溢れる" or "人人人人" in res.normalized_text
    assert "人人" in res.tokens.normalized_tokens


def test_block_non_han_antecedent() -> None:
    """Ensure iteration marks following kana or non-Han CJK are not falsely expanded."""
    resolver = IterationMarkResolver()

    # Hiragana 'あ' followed by '々' should not expand as Han
    res = resolver.resolve("あ々テスト")
    assert res.has_iteration_mark is True
    assert res.marks_expanded_count == 0
    assert res.normalized_text == "あ々テスト"


def test_isolated_leading_mark() -> None:
    """Ensure a mark at the beginning of a run or text does not crash and stays unexpanded."""
    resolver = IterationMarkResolver()

    res = resolver.resolve("々テスト")
    assert res.has_iteration_mark is True
    assert res.marks_expanded_count == 0
    assert res.normalized_text == "々テスト"


def test_bidirectional_recall_matcher_with_query_raw() -> None:
    """Verify query using '人々' matches target memory written with '人人'."""
    matcher = CjkIterationRecallMatcher()

    query = "街の人々の声"
    target = "街の人人の声を記録した"

    result = matcher.match(query, target)
    assert result.is_matched is True
    assert result.composite_score > 0.4
    assert result.normalized_overlap_count >= 1
    assert "人人" in result.matched_tokens


def test_bidirectional_recall_matcher_with_query_normalized() -> None:
    """Verify query using '人人' matches target memory written with '人々'."""
    matcher = CjkIterationRecallMatcher()

    query = "日日の業務メモ"
    target = "日々の開発記録と業務メモ"

    result = matcher.match(query, target)
    assert result.is_matched is True
    assert result.composite_score > 0.4
    assert "日日" in result.matched_tokens


def test_recall_matcher_negative_unrelated_text() -> None:
    """Verify completely unrelated text does not match."""
    matcher = CjkIterationRecallMatcher()

    query = "佐々木さんのタスク"
    target = "Pythonコンパイラの最適化手順"

    result = matcher.match(query, target)
    assert result.is_matched is False
    assert result.composite_score == 0.0
    assert len(result.matched_tokens) == 0


def test_facade_and_singleton() -> None:
    """Ensure CjkIterationMarkFacade works and singleton instance is reusable."""
    facade = CjkIterationMarkFacade()
    res = facade.disambiguate("年々の成長")
    assert res.normalized_text == "年年的成长" or "年年" in res.normalized_text

    inst1 = get_cjk_iteration_mark_facade()
    inst2 = get_cjk_iteration_mark_facade()
    assert inst1 is inst2
