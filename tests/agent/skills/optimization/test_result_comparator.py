"""Tests for StructuredComparator (Harness layer)

Covers:
- Identical inputs → 1.0 / is_match=True
- Empty inputs → 1.0
- One-side empty → 0.0 / is_match=False
- Partial diff → intermediate score
- Nested dict diff → recursive comparison
- Textual similarity (Jaccard)
- Custom threshold
- Weight configuration
- diff_summary and field_diffs output
"""

import pytest

from myrm_agent_harness.agent.skills.optimization.result_comparator import (
    ComparisonDetail,
    ResultComparator,
    StructuredComparator,
)


@pytest.fixture
def comparator() -> StructuredComparator:
    return StructuredComparator()


@pytest.mark.asyncio
async def test_identical_inputs(comparator: StructuredComparator) -> None:
    result = await comparator.compare({"status": "ok", "result": "hello"}, {"status": "ok", "result": "hello"})
    assert result.similarity_score == 1.0
    assert result.is_match is True
    assert result.diff_summary == "Results are identical"
    assert result.field_diffs == {}


@pytest.mark.asyncio
async def test_both_empty(comparator: StructuredComparator) -> None:
    result = await comparator.compare({}, {})
    assert result.similarity_score == 1.0
    assert result.is_match is True


@pytest.mark.asyncio
async def test_one_side_empty(comparator: StructuredComparator) -> None:
    result = await comparator.compare({"status": "ok"}, {})
    assert result.similarity_score == 0.0
    assert result.is_match is False
    assert "empty" in result.diff_summary.lower()


@pytest.mark.asyncio
async def test_one_side_empty_reversed(comparator: StructuredComparator) -> None:
    result = await comparator.compare({}, {"status": "ok"})
    assert result.similarity_score == 0.0
    assert result.is_match is False


@pytest.mark.asyncio
async def test_partial_diff(comparator: StructuredComparator) -> None:
    result = await comparator.compare(
        {"status": "ok", "result": "hello", "count": 10}, {"status": "ok", "result": "world", "count": 10}
    )
    assert 0.0 < result.similarity_score < 1.0
    assert "result" in result.field_diffs
    assert "1 field(s) differ" in result.diff_summary


@pytest.mark.asyncio
async def test_completely_different(comparator: StructuredComparator) -> None:
    result = await comparator.compare({"a": "1", "b": "2"}, {"c": "3", "d": "4"})
    assert result.similarity_score < 0.3
    assert result.is_match is False


@pytest.mark.asyncio
async def test_nested_dict_comparison(comparator: StructuredComparator) -> None:
    result = await comparator.compare(
        {"meta": {"score": 0.9, "model": "gpt-4"}, "output": "text"},
        {"meta": {"score": 0.9, "model": "gpt-4o"}, "output": "text"},
    )
    assert result.similarity_score >= 0.5
    assert "meta" in result.field_diffs


@pytest.mark.asyncio
async def test_textual_similarity_high() -> None:
    comp = StructuredComparator(structural_weight=0.0, textual_weight=1.0)
    result = await comp.compare(
        {"text": "the quick brown fox jumps over the lazy dog"}, {"text": "the quick brown fox jumps over the lazy cat"}
    )
    assert result.textual_score > 0.7


@pytest.mark.asyncio
async def test_textual_similarity_low() -> None:
    comp = StructuredComparator(structural_weight=0.0, textual_weight=1.0)
    result = await comp.compare({"text": "apple banana cherry"}, {"text": "xyz 123 qwerty"})
    assert result.textual_score < 0.3


@pytest.mark.asyncio
async def test_custom_threshold() -> None:
    strict = StructuredComparator(match_threshold=0.99)
    result = await strict.compare({"a": "hello", "b": "world"}, {"a": "hello", "b": "world!"})
    assert result.is_match is False

    lenient = StructuredComparator(match_threshold=0.3)
    result2 = await lenient.compare({"a": "hello", "b": "world"}, {"a": "hello", "b": "world!"})
    assert result2.is_match is True


@pytest.mark.asyncio
async def test_weight_configuration() -> None:
    structural_only = StructuredComparator(structural_weight=1.0, textual_weight=0.0)
    textual_only = StructuredComparator(structural_weight=0.0, textual_weight=1.0)

    baseline = {"key": "the quick brown fox"}
    candidate = {"key": "the fast brown fox"}

    r1 = await structural_only.compare(baseline, candidate)
    r2 = await textual_only.compare(baseline, candidate)

    assert r1.structural_score == r2.structural_score
    assert r1.textual_score == r2.textual_score
    assert r1.similarity_score != r2.similarity_score


@pytest.mark.asyncio
async def test_field_diffs_content(comparator: StructuredComparator) -> None:
    result = await comparator.compare({"name": "Alice", "age": 30}, {"name": "Bob", "age": 30})
    assert "name" in result.field_diffs
    baseline_val, candidate_val = result.field_diffs["name"]
    assert "Alice" in baseline_val
    assert "Bob" in candidate_val


@pytest.mark.asyncio
async def test_diff_summary_format(comparator: StructuredComparator) -> None:
    result = await comparator.compare({"a": "1", "b": "2", "c": "3"}, {"a": "x", "b": "y", "c": "3"})
    assert "2 field(s) differ" in result.diff_summary
    assert "Structural:" in result.diff_summary
    assert "Textual:" in result.diff_summary


@pytest.mark.asyncio
async def test_comparison_detail_dataclass() -> None:
    detail = ComparisonDetail(
        similarity_score=0.75,
        is_match=False,
        structural_score=0.6,
        textual_score=0.9,
        diff_summary="test",
        field_diffs={"key": ("a", "b")},
    )
    assert detail.similarity_score == 0.75
    assert detail.is_match is False
    assert detail.field_diffs["key"] == ("a", "b")


def test_protocol_conformance() -> None:
    assert isinstance(StructuredComparator(), ResultComparator)


@pytest.mark.asyncio
async def test_list_values_in_text(comparator: StructuredComparator) -> None:
    result = await comparator.compare({"tags": ["python", "ai", "agent"]}, {"tags": ["python", "ai", "agent"]})
    assert result.similarity_score == 1.0
    assert result.is_match is True


@pytest.mark.asyncio
async def test_score_clamped_to_01(comparator: StructuredComparator) -> None:
    result = await comparator.compare({"x": "test"}, {"x": "test"})
    assert 0.0 <= result.similarity_score <= 1.0


@pytest.mark.asyncio
async def test_missing_key_in_one_side(comparator: StructuredComparator) -> None:
    result = await comparator.compare({"a": "1", "b": "2"}, {"a": "1"})
    assert "b" in result.field_diffs
    baseline_val, candidate_val = result.field_diffs["b"]
    assert baseline_val == "2"
    assert candidate_val == "<missing>"
