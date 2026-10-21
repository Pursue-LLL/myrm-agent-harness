"""Tests for OKF index-first routing helpers."""

from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.index_routing import (
    format_index_route_context,
    match_index_entries,
    parse_index_entries,
    score_index_entry,
)


def test_parse_index_entries_groups_by_page_type() -> None:
    content = """# Wiki Index

## concept

- [[MachineLearning/Transformers]] — Neural network architecture using self-attention
- [[Cooking/Pasta]] — Italian noodle dishes

## entity

- [[Company/Acme]] — Example vendor
"""
    entries = parse_index_entries(content)
    assert len(entries) == 3
    assert entries[0].link_name == "MachineLearning/Transformers"
    assert entries[0].page_type == "concept"
    assert entries[2].page_type == "entity"


def test_score_index_entry_prefers_link_name() -> None:
    entry = parse_index_entries(
        "- [[MachineLearning/Transformers]] — Neural network architecture using self-attention"
    )[0]
    high = score_index_entry("transformers architecture", entry)
    low = score_index_entry("unrelated cooking topic", entry)
    assert high > low
    assert high >= 0.25


def test_score_index_entry_supports_cjk_query() -> None:
    entry = parse_index_entries("- [[ProjectA/API]] — 密钥轮换与审计流程")[0]
    score = score_index_entry("API 密钥轮换", entry)
    assert score >= 0.25


def test_match_index_entries_filters_by_min_score() -> None:
    entries = parse_index_entries(
        """## concept
- [[Alpha/One]] — Alpha topic summary
- [[Beta/Two]] — Beta topic summary
"""
    )
    matches = match_index_entries("alpha one", entries, max_hits=3, min_score=0.25)
    assert len(matches) == 1
    assert matches[0][0].link_name == "Alpha/One"


def test_format_index_route_context_includes_scores() -> None:
    entries = parse_index_entries("- [[Foo/Bar]] — Foo summary")[0:1]
    block = format_index_route_context([(entries[0], 0.75)])
    assert "Index routing (L0)" in block
    assert "[[Foo/Bar]]" in block
    assert "match=0.75" in block
