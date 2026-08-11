"""Regression tests for Wiki Publish Gate invariants."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import PUBLISH_STATUS_KEY, WikiPublishStatus
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.maintenance.linter import WikiLinter
from myrm_agent_harness.toolkits.wiki.pipeline.pending import WikiPendingEditsManager
from myrm_agent_harness.toolkits.wiki.pipeline.publication import (
    ConceptPathMapping,
    publish_concept_article,
    reindex_concepts_after_move,
)
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer
from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path / "wiki")
    structure.ensure_structure()
    return structure


@pytest.mark.asyncio
async def test_frontmatter_auto_fix_uses_publish_gate(wiki_structure: WikiStructure, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_llm = MagicMock()
    config = WikiConfig(enable_auto_maintenance=True)
    linter = WikiLinter(mock_llm, wiki_structure, config)

    article = wiki_structure.get_concept_file_path("gate/fix-type")
    article.parent.mkdir(parents=True, exist_ok=True)
    article.write_text("# Missing type\n\n## Compiled Truth\nBody.\n", encoding="utf-8")

    publish_mock = AsyncMock()
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.wiki.maintenance.linter.publish_concept_article",
        publish_mock,
    )

    from myrm_agent_harness.toolkits.wiki.core.types import LintIssue

    issue = LintIssue(
        issue_type="invalid_frontmatter_type",
        severity="medium",
        location=str(article),
        description="Missing type",
        can_auto_fix=True,
    )
    await linter._auto_fix_issue(issue)

    publish_mock.assert_awaited_once()
    args = publish_mock.await_args.args
    assert args[2] == "gate/fix-type"


@pytest.mark.asyncio
async def test_link_enrichment_uses_publish_gate(wiki_structure: WikiStructure, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_llm = MagicMock()
    config = WikiConfig(enable_auto_maintenance=True, enable_backlinks=True)
    linter = WikiLinter(mock_llm, wiki_structure, config)

    alpha = wiki_structure.get_concept_file_path("Alpha")
    alpha.write_text(
        "---\ntype: concept\n---\n\n# Alpha\n\n## Compiled Truth\nMachine learning overview.\n",
        encoding="utf-8",
    )
    beta = wiki_structure.get_concept_file_path("Beta")
    beta.write_text(
        "---\ntype: concept\n---\n\n# Beta\n\n## Compiled Truth\nRelated ML topic.\n",
        encoding="utf-8",
    )

    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content='["Beta"]'))

    publish_mock = AsyncMock()
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.wiki.maintenance.linter.publish_concept_article",
        publish_mock,
    )

    count = await linter._discover_connections()
    assert count >= 1
    publish_mock.assert_awaited()
    rel = publish_mock.await_args.args[2]
    assert rel.lower() == "alpha"


@pytest.mark.asyncio
async def test_publish_stamps_frontmatter_on_disk(wiki_structure: WikiStructure) -> None:

    content = "---\ntype: concept\n---\n\n## Compiled Truth\nPublished body.\n"
    await publish_concept_article(wiki_structure, None, "live/page", content)

    saved = wiki_structure.get_concept_file_path("live/page").read_text(encoding="utf-8")
    metadata, _body = parse_frontmatter(saved)
    assert metadata[PUBLISH_STATUS_KEY] == WikiPublishStatus.PUBLISHED.value


@pytest.mark.asyncio
async def test_stage_pending_demotes_stale_published(wiki_structure: WikiStructure) -> None:
    raw_file = wiki_structure.get_raw_file_path("notes.md")
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text("# Notes\nBudget 50M\n", encoding="utf-8")

    published = (
        "---\ntype: concept\npublish_status: published\nsources:\n  - notes.md\n---\n\n"
        "## Compiled Truth\nBudget 100M.\n"
    )
    article_path = wiki_structure.get_concept_file_path("Team/Budget")
    article_path.parent.mkdir(parents=True, exist_ok=True)
    article_path.write_text(published, encoding="utf-8")

    old_ts = time.time() - 3600
    os.utime(article_path, (old_ts, old_ts))

    raw_file.write_text("# Notes\nBudget 50M\n", encoding="utf-8")
    os.utime(raw_file, (time.time(), time.time()))

    indexer = WikiIndexer(wiki_structure)
    await indexer.upsert("Team/Budget", published)
    assert await indexer.search("Budget 100M", limit=5)

    pending_mgr = WikiPendingEditsManager(wiki_structure, indexer)
    proposed = (
        "---\ntype: concept\nsources:\n  - notes.md\n---\n\n"
        "## Compiled Truth\nBudget 50M.\n"
    )
    await pending_mgr.stage_pending_edit("Team/Budget", proposed, source_files=["notes.md"])

    saved = article_path.read_text(encoding="utf-8")
    metadata, _body = parse_frontmatter(saved)
    assert metadata[PUBLISH_STATUS_KEY] == WikiPublishStatus.DRAFT.value
    assert await indexer.search("Budget 100M", limit=5) == []


@pytest.mark.asyncio
async def test_reindex_after_move_preserves_publish_status(wiki_structure: WikiStructure) -> None:
    content = (
        "---\ntype: concept\npublish_status: published\n---\n\n"
        "## Compiled Truth\nMove-safe body.\n"
    )
    old_path = wiki_structure.get_concept_file_path("Old/Topic")
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_text(content, encoding="utf-8")

    new_path = wiki_structure.get_concept_file_path("Archive/Topic")
    new_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.rename(new_path)

    indexer = WikiIndexer(wiki_structure)
    await indexer.upsert("Old/Topic", content)

    reindexed = await reindex_concepts_after_move(
        wiki_structure,
        indexer,
        [ConceptPathMapping(old_concept="Old/Topic", new_concept="Archive/Topic")],
    )
    assert reindexed == 1
    assert await indexer.search("Move-safe", limit=5)
    assert await indexer.search("Old/Topic", limit=5) == []

    saved = new_path.read_text(encoding="utf-8")
    metadata, _body = parse_frontmatter(saved)
    assert metadata[PUBLISH_STATUS_KEY] == WikiPublishStatus.PUBLISHED.value


@pytest.mark.asyncio
async def test_reindex_after_move_skips_directory_sidecars(wiki_structure: WikiStructure) -> None:
    sidecar_dir = wiki_structure.concepts_dir / "Team"
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = sidecar_dir / WikiStructure.DIRECTORY_ABSTRACT_FILENAME
    content = "---\ntype: overview\n---\n\n## Compiled Truth\nSidecar abstract.\n"
    sidecar_path.write_text(content, encoding="utf-8")

    dest_dir = wiki_structure.concepts_dir / "Archive"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / WikiStructure.DIRECTORY_ABSTRACT_FILENAME
    sidecar_path.rename(dest_path)

    indexer = WikiIndexer(wiki_structure)
    await indexer.upsert("Team/.abstract", content)

    reindexed = await reindex_concepts_after_move(
        wiki_structure,
        indexer,
        [ConceptPathMapping(old_concept="Team/.abstract", new_concept="Archive/.abstract")],
    )
    assert reindexed == 0
    assert await indexer.search("Sidecar abstract", limit=5) == []
