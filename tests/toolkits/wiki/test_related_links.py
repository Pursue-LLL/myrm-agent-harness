"""Related Concepts section SSOT: one writer that never touches the rest of the page."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.wiki import WikiConfig, WikiStructure
from myrm_agent_harness.toolkits.wiki.core.link_resolver import WikiLinkResolver
from myrm_agent_harness.toolkits.wiki.core.related_links import RELATED_HEADING, merge_related_links
from myrm_agent_harness.toolkits.wiki.core.section_contract import get_section_inner
from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
from myrm_agent_harness.toolkits.wiki.pipeline.postprocess import generate_backlinks

TRUTH_THEN_TIMELINE = (
    "---\ntype: concept\n---\n\n## Compiled Truth\nAlpha facts.\n\n## Timeline\n- 2026-01-01: first event\n"
)
RELATED_BEFORE_TIMELINE = (
    "---\ntype: concept\n---\n\n## Compiled Truth\nAlpha facts.\n\n"
    "## Related Concepts\n\n- [[Old Link]]\n\n"
    "## Timeline\n- 2026-01-01: first event\n- 2026-02-01: evidence added after the related block\n"
)


@pytest.fixture
def structure(tmp_path: Path) -> WikiStructure:
    wiki = WikiStructure(tmp_path / "wiki-root")
    wiki.ensure_structure()
    return wiki


def _merge(structure: WikiStructure, content: str, names: list[str], source: str = "alpha") -> tuple[str, int]:
    return merge_related_links(content, names, source=source, resolver=WikiLinkResolver(structure))


def test_merge_creates_the_section_after_every_existing_section(structure: WikiStructure) -> None:
    merged, added = _merge(structure, TRUTH_THEN_TIMELINE, ["Beta"])

    assert added == 1
    assert merged.index("## Timeline") < merged.index(RELATED_HEADING)
    assert "- [[Beta]]" in (get_section_inner(merged, RELATED_HEADING) or "")
    assert "- 2026-01-01: first event" in merged


def test_merge_keeps_the_sections_that_follow_the_related_block(structure: WikiStructure) -> None:
    merged, added = _merge(structure, RELATED_BEFORE_TIMELINE, ["Beta"])

    assert added == 1
    assert merged.count(RELATED_HEADING) == 1
    inner = get_section_inner(merged, RELATED_HEADING) or ""
    assert "[[Old Link]]" in inner
    assert "[[Beta]]" in inner
    assert "- 2026-02-01: evidence added after the related block" in merged


def test_merge_keeps_text_a_person_wrote_in_the_section(structure: WikiStructure) -> None:
    content = TRUTH_THEN_TIMELINE + "\n## Related Concepts\n\nSee my notes on gardening.\n\n- [[Old Link]]\n"

    merged, added = _merge(structure, content, ["Beta"])

    assert added == 1
    inner = get_section_inner(merged, RELATED_HEADING) or ""
    assert "See my notes on gardening." in inner
    assert inner.index("[[Old Link]]") < inner.index("[[Beta]]")


def test_merge_skips_a_name_that_resolves_to_a_page_the_section_already_links(structure: WikiStructure) -> None:
    structure.get_concept_file_path("rust/ownership").write_text("# Ownership\n", encoding="utf-8")
    content = TRUTH_THEN_TIMELINE + "\n## Related Concepts\n\n- [[Ownership]]\n"

    merged, added = _merge(structure, content, ["rust/ownership", "RUST/Ownership"])

    assert added == 0
    assert merged == content


def test_merge_dedupes_names_that_resolve_to_no_page_by_case(structure: WikiStructure) -> None:
    merged, added = _merge(structure, TRUTH_THEN_TIMELINE, ["Future Topic", "future topic", "FUTURE TOPIC"])

    assert added == 1
    assert merged.count("[[") == 1


def test_merge_ignores_blank_names_and_returns_the_page_untouched(structure: WikiStructure) -> None:
    merged, added = _merge(structure, TRUTH_THEN_TIMELINE, ["", "   "])

    assert added == 0
    assert merged == TRUTH_THEN_TIMELINE


@pytest.mark.asyncio
async def test_generate_backlinks_keeps_the_sections_after_the_related_block(structure: WikiStructure) -> None:
    article = structure.get_concept_file_path("Alpha")
    article.write_text(RELATED_BEFORE_TIMELINE, encoding="utf-8")
    concepts = [ConceptInfo(name="Alpha", definition="d", mentions=1, source_files=[], related_concepts=["Beta"])]

    count = await generate_backlinks(structure, WikiConfig(), concepts, MagicMock())

    saved = article.read_text(encoding="utf-8")
    assert count == 1
    assert saved.count(RELATED_HEADING) == 1
    assert "[[Beta]]" in (get_section_inner(saved, RELATED_HEADING) or "")
    assert "- 2026-02-01: evidence added after the related block" in saved


@pytest.mark.asyncio
async def test_generate_backlinks_leaves_an_unchanged_page_and_its_edges_alone(structure: WikiStructure) -> None:
    article = structure.get_concept_file_path("Alpha")
    article.write_text(TRUTH_THEN_TIMELINE, encoding="utf-8")
    concepts = [ConceptInfo(name="Alpha", definition="d", mentions=1, source_files=[], related_concepts=["Beta"])]
    indexer = MagicMock()

    first = await generate_backlinks(structure, WikiConfig(), concepts, indexer)
    after_first = article.read_text(encoding="utf-8")
    second = await generate_backlinks(structure, WikiConfig(), concepts, indexer)

    assert (first, second) == (1, 0)
    assert article.read_text(encoding="utf-8") == after_first
    assert indexer.extract_and_upsert_edges.call_count == 1
