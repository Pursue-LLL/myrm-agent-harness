"""Tests for wiki publish gate (WPG-MVP)."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.claims_contract import parse_claims_from_content
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    PUBLISH_STATUS_KEY,
    WikiPublishStatus,
    repair_publication_on_disk,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.publication import (
    publish_concept_article,
    repair_publication_status,
)
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer
from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path / "wiki")
    structure.ensure_structure()
    return structure


@pytest.mark.asyncio
async def test_publish_concept_article_stamps_frontmatter_and_indexes(wiki_structure: WikiStructure) -> None:
    content = "---\ntype: concept\n---\n\n## Compiled Truth\nHello world.\n"
    indexer = WikiIndexer(wiki_structure)

    await publish_concept_article(wiki_structure, indexer, "demo/article", content)

    saved = wiki_structure.get_concept_file_path("demo/article").read_text(encoding="utf-8")
    metadata, _body = parse_frontmatter(saved)
    assert metadata[PUBLISH_STATUS_KEY] == WikiPublishStatus.PUBLISHED.value
    assert "published_at" in metadata

    results = await indexer.search("Hello", limit=5)
    assert any(name == "demo/article" for name, _score in results)


@pytest.mark.asyncio
async def test_publish_concept_article_preserves_nested_claims(wiki_structure: WikiStructure) -> None:
    content = """---
type: concept
claims:
  - id: claim.demo.item
    text: Demo fact
    status: supported
    confidence: 0.8
    evidence:
      - kind: raw-source
        sourceId: source.demo
        path: notes.md
        lines: ""
        weight: 1.0
        confidence: 0.7
---

## Compiled Truth
Body.
"""
    await publish_concept_article(wiki_structure, None, "demo/claims", content)

    saved = wiki_structure.get_concept_file_path("demo/claims").read_text(encoding="utf-8")
    claims = parse_claims_from_content(saved)
    assert len(claims) == 1
    assert claims[0].id == "claim.demo.item"
    metadata, _body = parse_frontmatter(saved)
    assert metadata[PUBLISH_STATUS_KEY] == WikiPublishStatus.PUBLISHED.value


@pytest.mark.asyncio
async def test_draft_status_excluded_from_search(wiki_structure: WikiStructure) -> None:
    draft_content = "---\ntype: concept\npublish_status: draft\n---\n\n## Compiled Truth\nSecret draft content.\n"
    indexer = WikiIndexer(wiki_structure)
    await indexer.upsert("draft/page", draft_content)

    results = await indexer.search("Secret draft", limit=5)
    assert results == []


def test_repair_publication_grandfathers_missing_status(wiki_structure: WikiStructure) -> None:
    article = wiki_structure.get_concept_file_path("legacy/page")
    article.parent.mkdir(parents=True, exist_ok=True)
    article.write_text("---\ntype: concept\n---\n\n## Compiled Truth\nLegacy body.\n", encoding="utf-8")

    result = repair_publication_on_disk(wiki_structure)
    assert result.files_repaired == 1

    metadata, _body = parse_frontmatter(article.read_text(encoding="utf-8"))
    assert metadata[PUBLISH_STATUS_KEY] == WikiPublishStatus.PUBLISHED.value


def test_repair_publication_skips_intentional_draft(wiki_structure: WikiStructure) -> None:
    draft = "---\ntype: concept\npublish_status: draft\n---\n\n## Compiled Truth\nStale demoted body.\n"
    article = wiki_structure.get_concept_file_path("Team/Budget")
    article.parent.mkdir(parents=True, exist_ok=True)
    article.write_text(draft, encoding="utf-8")

    result = repair_publication_on_disk(wiki_structure)
    assert result.files_repaired == 0
    assert result.files_skipped_intentional_draft == 1

    metadata, _body = parse_frontmatter(article.read_text(encoding="utf-8"))
    assert metadata[PUBLISH_STATUS_KEY] == WikiPublishStatus.DRAFT.value


def test_repair_publication_skips_blocked(wiki_structure: WikiStructure) -> None:
    blocked = "---\ntype: concept\npublish_status: blocked\n---\n\n## Compiled Truth\nBlocked body.\n"
    article = wiki_structure.get_concept_file_path("blocked/page")
    article.parent.mkdir(parents=True, exist_ok=True)
    article.write_text(blocked, encoding="utf-8")

    result = repair_publication_on_disk(wiki_structure)
    assert result.files_repaired == 0
    assert result.files_skipped_intentional_draft == 1

    metadata, _body = parse_frontmatter(article.read_text(encoding="utf-8"))
    assert metadata[PUBLISH_STATUS_KEY] == WikiPublishStatus.BLOCKED.value


@pytest.mark.asyncio
async def test_repair_publication_status_keeps_draft_out_of_search(wiki_structure: WikiStructure) -> None:
    draft = "---\ntype: concept\npublish_status: draft\n---\n\n## Compiled Truth\nDo not republish.\n"
    article = wiki_structure.get_concept_file_path("stale/topic")
    article.parent.mkdir(parents=True, exist_ok=True)
    article.write_text(draft, encoding="utf-8")

    indexer = WikiIndexer(wiki_structure)
    await indexer.upsert("stale/topic", draft)

    result = await repair_publication_status(wiki_structure, indexer)
    assert result.files_skipped_intentional_drafts == 1
    assert result.files_repaired == 0

    metadata, _body = parse_frontmatter(article.read_text(encoding="utf-8"))
    assert metadata[PUBLISH_STATUS_KEY] == WikiPublishStatus.DRAFT.value
    assert await indexer.search("Do not republish", limit=5) == []


@pytest.mark.asyncio
async def test_reindex_concepts_after_move_deduplication(wiki_structure: WikiStructure) -> None:
    from myrm_agent_harness.toolkits.wiki.pipeline.publication.path_change import (
        ConceptPathMapping,
        reindex_concepts_after_move,
    )

    indexer = WikiIndexer(wiki_structure)

    # Prepare concept A and concept B
    path_a = wiki_structure.get_concept_file_path("topic_a_new")
    path_a.parent.mkdir(parents=True, exist_ok=True)
    path_a.write_text("---\ntype: concept\npublish_status: published\n---\n\n## Content A\nHello from A.\n", encoding="utf-8")

    path_b = wiki_structure.get_concept_file_path("topic_b")
    path_b.parent.mkdir(parents=True, exist_ok=True)
    path_b.write_text("---\ntype: concept\npublish_status: published\n---\n\n## Content B\nHello from B.\n", encoding="utf-8")

    # Mappings move topic_a -> topic_a_new
    mappings = [ConceptPathMapping(old_concept="topic_a", new_concept="topic_a_new")]

    # Referrers contains topic_a_new (already in mappings) AND duplicate topic_b
    referrers = ["topic_a_new", "topic_b", path_b]

    count = await reindex_concepts_after_move(wiki_structure, indexer, mappings, modified_referrers=referrers)

    # 1 for topic_a_new in mappings + 1 for topic_b in referrers = 2 (duplicates skipped)
    assert count == 2

    # Search works for both
    res_a = await indexer.search("Hello from A", limit=5)
    assert any(name == "topic_a_new" for name, _ in res_a)
    res_b = await indexer.search("Hello from B", limit=5)
    assert any(name == "topic_b" for name, _ in res_b)


@pytest.mark.asyncio
async def test_reindex_concepts_after_move_edge_cases(wiki_structure: WikiStructure) -> None:
    from myrm_agent_harness.toolkits.wiki.pipeline.publication.path_change import (
        ConceptPathMapping,
        reindex_concepts_after_move,
    )

    indexer = WikiIndexer(wiki_structure)

    # 1. Non-existent file
    m_missing = ConceptPathMapping(old_concept="ghost_old", new_concept="ghost_new")

    # 2. Sidecar path
    sidecar_path, _ = wiki_structure.get_directory_sidecar_paths("cat")
    sidecar_path.write_text("---\ntype: concept\n---\nSidecar content", encoding="utf-8")
    m_sidecar = ConceptPathMapping(old_concept="cat_old", new_concept="cat/.abstract")

    # 3. Invalid frontmatter in mappings
    invalid_map_page = wiki_structure.get_concept_file_path("map_invalid")
    invalid_map_page.write_text("No frontmatter in map", encoding="utf-8")
    m_invalid = ConceptPathMapping(old_concept="inv_old", new_concept="map_invalid")

    # 4. Valid page
    valid_page = wiki_structure.get_concept_file_path("valid_note")
    valid_page.write_text("---\ntype: concept\npublish_status: published\n---\nValid", encoding="utf-8")
    m_valid = ConceptPathMapping(old_concept="v_old", new_concept="valid_note")
    m_duplicate = ConceptPathMapping(old_concept="v_old2", new_concept="valid_note")

    # 5. Invalid frontmatter in referrer
    invalid_ref_page = wiki_structure.get_concept_file_path("ref_invalid")
    invalid_ref_page.write_text("No frontmatter in ref", encoding="utf-8")

    # Referrers: external path, sidecar, invalid frontmatter with .md suffix, non-existent
    ext_path = wiki_structure.base_dir / "external.md"
    ext_path.write_text("external", encoding="utf-8")

    referrers = [
        ext_path,  # ValueError on relative_to
        sidecar_path,  # _is_directory_sidecar
        "ref_invalid.md",  # invalid frontmatter with .md suffix
        "missing_referrer",  # not exists
    ]

    count = await reindex_concepts_after_move(
        wiki_structure,
        indexer,
        [m_missing, m_sidecar, m_invalid, m_valid, m_duplicate],
        modified_referrers=referrers,
    )

    # Only m_valid should be reindexed
    assert count == 1


@pytest.mark.asyncio
async def test_reindex_concepts_after_move_io_error_and_async_edges(
    wiki_structure: WikiStructure,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from myrm_agent_harness.toolkits.wiki.pipeline.publication.path_change import (
        ConceptPathMapping,
        reindex_concepts_after_move,
    )

    indexer = WikiIndexer(wiki_structure)

    # Mock extract_and_upsert_edges to return an awaitable coroutine
    async def fake_extract_and_upsert_edges(concept: str, content: str) -> None:
        pass

    monkeypatch.setattr(indexer, "extract_and_upsert_edges", fake_extract_and_upsert_edges)

    map_err_path = wiki_structure.get_concept_file_path("map_err")
    map_err_path.write_text("dummy", encoding="utf-8")

    map_ok_path = wiki_structure.get_concept_file_path("map_ok")
    map_ok_path.write_text("---\ntype: concept\npublish_status: published\n---\nOk", encoding="utf-8")

    ref_err_path = wiki_structure.get_concept_file_path("ref_err")
    ref_err_path.write_text("dummy", encoding="utf-8")

    ref_ok_path = wiki_structure.get_concept_file_path("ref_ok")
    ref_ok_path.write_text("---\ntype: concept\npublish_status: published\n---\nRef Ok", encoding="utf-8")

    real_read_text = Path.read_text

    def simulated_read_text(self: Path, encoding: str = "utf-8", errors: str | None = None) -> str:
        if "err" in self.name:
            raise OSError("Simulated disk error")
        return real_read_text(self, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", simulated_read_text)

    mappings = [
        ConceptPathMapping(old_concept="old_map_err", new_concept="map_err"),
        ConceptPathMapping(old_concept="old_map_ok", new_concept="map_ok"),
    ]
    referrers = [ref_err_path, ref_ok_path]

    count = await reindex_concepts_after_move(
        wiki_structure,
        indexer,
        mappings,
        modified_referrers=referrers,
    )

    assert count == 2



