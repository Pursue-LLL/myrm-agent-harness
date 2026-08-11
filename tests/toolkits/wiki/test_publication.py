"""Tests for wiki publish gate (WPG-MVP)."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter
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
    draft_content = (
        "---\ntype: concept\npublish_status: draft\n---\n\n## Compiled Truth\nSecret draft content.\n"
    )
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
    draft = (
        "---\ntype: concept\npublish_status: draft\n---\n\n## Compiled Truth\nStale demoted body.\n"
    )
    article = wiki_structure.get_concept_file_path("Team/Budget")
    article.parent.mkdir(parents=True, exist_ok=True)
    article.write_text(draft, encoding="utf-8")

    result = repair_publication_on_disk(wiki_structure)
    assert result.files_repaired == 0
    assert result.files_skipped_intentional_draft == 1

    metadata, _body = parse_frontmatter(article.read_text(encoding="utf-8"))
    assert metadata[PUBLISH_STATUS_KEY] == WikiPublishStatus.DRAFT.value


def test_repair_publication_skips_blocked(wiki_structure: WikiStructure) -> None:
    blocked = (
        "---\ntype: concept\npublish_status: blocked\n---\n\n## Compiled Truth\nBlocked body.\n"
    )
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
    draft = (
        "---\ntype: concept\npublish_status: draft\n---\n\n## Compiled Truth\nDo not republish.\n"
    )
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
