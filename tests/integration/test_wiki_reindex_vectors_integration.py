"""Integration: wiki vector reindex SSOT with real WikiIndexer (no reindex mock)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.retriever.embedding.cloud_embedding import CloudEmbedding
from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import WikiPublishStatus
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer
from myrm_agent_harness.toolkits.wiki.retrieval.reindex_vectors import reindex_published_vectors


def _published_markdown(body: str) -> str:
    return f"---\npublish_status: published\n---\n\n## Compiled Truth\n{body}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reindex_refreshes_fts_and_sidecars_skips_drafts(tmp_path: Path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    config = WikiConfig(
        enable_hybrid_search=False,
        enable_directory_sidecars=True,
        enable_asset_index=False,
    )
    indexer = WikiIndexer(structure, config)

    published_path = structure.get_concept_file_path("alpha-note")
    published_path.write_text(_published_markdown("Old alpha truth"), encoding="utf-8")
    await indexer.upsert("alpha-note", published_path.read_text(encoding="utf-8"))

    draft_path = structure.get_concept_file_path("draft-note")
    draft_path.write_text(
        f"---\npublish_status: {WikiPublishStatus.DRAFT.value}\n---\n\n## Compiled Truth\nDraft body",
        encoding="utf-8",
    )

    engine_dir = structure.concepts_dir / "engine"
    engine_dir.mkdir(parents=True)
    sidecar_path = engine_dir / ".abstract.md"
    sidecar_path.write_text("Engine sidecar v1", encoding="utf-8")
    await indexer.upsert_sidecar("engine", level=0, content="Engine sidecar v1")

    published_path.write_text(_published_markdown("New alpha truth after reindex"), encoding="utf-8")
    sidecar_path.write_text("Engine sidecar v2 after reindex", encoding="utf-8")

    result = await reindex_published_vectors(structure, indexer)

    assert result.concepts_scanned == 2
    assert result.concepts_reindexed == 1
    assert result.skipped_drafts == 1
    assert result.sidecars_reindexed == 1
    assert result.failed == 0

    truth = indexer.get_truth("alpha-note")
    assert truth is not None
    assert "New alpha truth after reindex" in truth

    sidecar_hits = await indexer.search_sidecars("sidecar v2 after reindex", limit=5)
    assert sidecar_hits
    assert sidecar_hits[0][0] == "engine"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reindex_embed_window_violation_surfaces_in_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    config = WikiConfig(enable_hybrid_search=True, enable_directory_sidecars=False)

    vector_store = AsyncMock()
    vector_store.collection_exists.return_value = False
    vector_store.create_collection = AsyncMock()
    vector_store.ensure_collection = AsyncMock()
    vector_store.upsert = AsyncMock()
    vector_store.delete_by_filter = AsyncMock()

    embedding = CloudEmbedding(model="BAAI/bge-large-zh-v1.5", api_key="integration-test-key")

    from myrm_agent_harness.toolkits.retriever.embedding.window_policy import (
        EmbedInputTooLargeError,
    )

    async def _reject_window(embedding_self, texts):
        raise EmbedInputTooLargeError(
            token_count=900,
            limit=512,
            model="BAAI/bge-large-zh-v1.5",
            parent_key="huge-note",
        )

    monkeypatch.setattr(CloudEmbedding, "embed_batch", _reject_window)
    indexer = WikiIndexer(structure, config, vector_store=vector_store, embedding=embedding)

    huge_body = "token " * 3000
    concept_path = structure.get_concept_file_path("huge-note")
    concept_path.write_text(_published_markdown(huge_body), encoding="utf-8")

    result = await reindex_published_vectors(structure, indexer)

    assert result.concepts_scanned == 1
    assert result.concepts_reindexed == 0
    assert result.failed == 1
    assert result.errors
    assert result.errors[0].startswith("concept:huge-note:")
    assert "exceeds" in result.errors[0]
