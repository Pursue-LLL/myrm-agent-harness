"""Tests for wiki vector reindex SSOT."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.retriever.embedding.window_policy import EmbedInputTooLargeError
from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import WikiPublishStatus
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.asset_index import AssetIndexResult
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer
from myrm_agent_harness.toolkits.wiki.retrieval.reindex_vectors import (
    WikiVectorReindexResult,
    _iter_sidecar_files,
    reindex_published_vectors,
)


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


def _make_indexer(
    *,
    sidecars: bool = True,
    assets: bool = False,
) -> MagicMock:
    indexer = MagicMock()
    indexer._config = WikiConfig(enable_directory_sidecars=sidecars, enable_asset_index=assets)
    indexer.upsert = AsyncMock()
    indexer.extract_and_upsert_edges = MagicMock(return_value=None)
    indexer.upsert_sidecar = AsyncMock()
    return indexer


def _embed_too_large(parent_key: str = "note") -> EmbedInputTooLargeError:
    return EmbedInputTooLargeError(
        token_count=900,
        limit=512,
        model="test-model",
        parent_key=parent_key,
    )


def test_iter_sidecar_files_lists_l0_and_l1(wiki_structure: WikiStructure) -> None:
    engine_dir = wiki_structure.concepts_dir / "engine"
    engine_dir.mkdir(parents=True)
    (engine_dir / ".abstract.md").write_text("Engine abstract", encoding="utf-8")
    (engine_dir / ".overview.md").write_text("Engine overview", encoding="utf-8")

    entries = _iter_sidecar_files(wiki_structure)

    assert ("engine", 0, engine_dir / ".abstract.md") in entries
    assert ("engine", 1, engine_dir / ".overview.md") in entries


def test_iter_sidecar_files_empty_when_concepts_dir_missing(tmp_path: Path) -> None:
    structure = WikiStructure(tmp_path)

    assert _iter_sidecar_files(structure) == []


def test_wiki_vector_reindex_result_properties() -> None:
    result = WikiVectorReindexResult(
        concepts_scanned=5,
        concepts_reindexed=3,
        skipped_drafts=2,
        sidecars_reindexed=1,
        assets_indexed=4,
        assets_failed=0,
        failed=0,
        errors=(),
    )

    assert result.scanned == 5
    assert result.reindexed == 8


@pytest.mark.asyncio
async def test_reindex_skips_drafts_and_rebuilds_sidecars(wiki_structure: WikiStructure) -> None:
    published_path = wiki_structure.get_concept_file_path("published-note")
    published_path.write_text(
        "---\npublish_status: published\n---\n\n## Compiled Truth\nPublished body",
        encoding="utf-8",
    )
    draft_path = wiki_structure.get_concept_file_path("draft-note")
    draft_path.write_text(
        f"---\npublish_status: {WikiPublishStatus.DRAFT.value}\n---\n\n## Compiled Truth\nDraft body",
        encoding="utf-8",
    )
    engine_dir = wiki_structure.concepts_dir / "engine"
    engine_dir.mkdir(parents=True)
    (engine_dir / ".abstract.md").write_text("Sidecar abstract", encoding="utf-8")

    indexer = _make_indexer(sidecars=True, assets=False)

    result = await reindex_published_vectors(wiki_structure, indexer)

    assert result.concepts_scanned == 2
    assert result.concepts_reindexed == 1
    assert result.skipped_drafts == 1
    assert result.sidecars_reindexed == 1
    indexer.upsert.assert_awaited_once()
    indexer.upsert_sidecar.assert_awaited_once_with(
        "engine",
        level=0,
        content="Sidecar abstract",
    )


@pytest.mark.asyncio
async def test_reindex_runs_asset_indexer_when_enabled(wiki_structure: WikiStructure) -> None:
    concept_path = wiki_structure.get_concept_file_path("note-a")
    concept_path.write_text("## Compiled Truth\nBody", encoding="utf-8")

    indexer = _make_indexer(sidecars=False, assets=True)

    asset_indexer = MagicMock()
    asset_indexer.index_all = AsyncMock(return_value=AssetIndexResult(indexed=2, skipped=1, failed=0))

    result = await reindex_published_vectors(
        wiki_structure,
        indexer,
        asset_indexer=asset_indexer,
    )

    assert result.assets_indexed == 2
    assert result.reindexed == 3
    asset_indexer.index_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_reindex_skips_federated_public_concepts(tmp_path: Path) -> None:
    public_root = tmp_path / "public_mount"
    fed_concepts = public_root / "wiki" / "concepts"
    fed_concepts.mkdir(parents=True)
    (fed_concepts / "fed-note.md").write_text(
        "---\npublish_status: published\n---\n\n## Compiled Truth\nFederated",
        encoding="utf-8",
    )
    structure = WikiStructure(tmp_path, public_dirs=[public_root])
    structure.ensure_structure()
    indexer = _make_indexer(sidecars=False, assets=False)

    result = await reindex_published_vectors(structure, indexer)

    assert result.concepts_scanned == 0
    indexer.upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_reindex_creates_indexer_when_none(wiki_structure: WikiStructure) -> None:
    concept_path = wiki_structure.get_concept_file_path("note-b")
    concept_path.write_text(
        "---\npublish_status: published\n---\n\n## Compiled Truth\nBody",
        encoding="utf-8",
    )
    created = _make_indexer(sidecars=False, assets=False)

    with patch(
        "myrm_agent_harness.toolkits.wiki.retrieval.reindex_vectors.WikiIndexer",
        return_value=created,
    ) as wiki_indexer_cls:
        wiki_indexer_cls._resolve_publish_status = WikiIndexer._resolve_publish_status
        result = await reindex_published_vectors(wiki_structure, None)

    wiki_indexer_cls.assert_called_once_with(wiki_structure)
    assert result.concepts_reindexed == 1


@pytest.mark.asyncio
async def test_reindex_awaits_async_edge_extraction(wiki_structure: WikiStructure) -> None:
    concept_path = wiki_structure.get_concept_file_path("edge-note")
    concept_path.write_text("## Compiled Truth\nBody", encoding="utf-8")
    indexer = _make_indexer(sidecars=False, assets=False)
    edge_mock = AsyncMock(return_value=None)
    indexer.extract_and_upsert_edges = MagicMock(return_value=edge_mock())

    await reindex_published_vectors(wiki_structure, indexer)

    edge_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_reindex_concept_embed_input_too_large(wiki_structure: WikiStructure) -> None:
    concept_path = wiki_structure.get_concept_file_path("oversized")
    concept_path.write_text("## Compiled Truth\nBody", encoding="utf-8")
    indexer = _make_indexer(sidecars=False, assets=False)
    indexer.upsert = AsyncMock(side_effect=_embed_too_large("oversized"))

    result = await reindex_published_vectors(wiki_structure, indexer)

    assert result.failed == 1
    assert len(result.errors) == 1
    assert result.errors[0].startswith("concept:oversized:")
    assert "900" in result.errors[0]
    assert "512" in result.errors[0]


@pytest.mark.asyncio
async def test_reindex_concept_os_error(wiki_structure: WikiStructure) -> None:
    concept_path = wiki_structure.get_concept_file_path("io-fail")
    concept_path.write_text("## Compiled Truth\nBody", encoding="utf-8")
    indexer = _make_indexer(sidecars=False, assets=False)
    indexer.upsert = AsyncMock(side_effect=OSError("disk full"))

    result = await reindex_published_vectors(wiki_structure, indexer)

    assert result.failed == 1
    assert result.errors[0].startswith("concept:")
    assert "disk full" in result.errors[0]


@pytest.mark.asyncio
async def test_reindex_concept_unexpected_error(wiki_structure: WikiStructure) -> None:
    concept_path = wiki_structure.get_concept_file_path("boom")
    concept_path.write_text("## Compiled Truth\nBody", encoding="utf-8")
    indexer = _make_indexer(sidecars=False, assets=False)
    indexer.upsert = AsyncMock(side_effect=RuntimeError("upsert failed"))

    result = await reindex_published_vectors(wiki_structure, indexer)

    assert result.failed == 1
    assert result.errors == ("concept:boom: upsert failed",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("side_effect", "error_prefix"),
    [
        (_embed_too_large(), "sidecar:L0:root:"),
        (OSError("read failed"), "sidecar:L0:root:"),
        (RuntimeError("sidecar failed"), "sidecar:L0:root:"),
    ],
)
async def test_reindex_sidecar_errors(
    wiki_structure: WikiStructure,
    side_effect: BaseException,
    error_prefix: str,
) -> None:
    root_sidecar = wiki_structure.concepts_dir / ".abstract.md"
    root_sidecar.write_text("Root abstract", encoding="utf-8")
    indexer = _make_indexer(sidecars=True, assets=False)
    indexer.upsert_sidecar = AsyncMock(side_effect=side_effect)

    result = await reindex_published_vectors(wiki_structure, indexer)

    assert result.failed == 1
    assert result.errors[0].startswith(error_prefix)


@pytest.mark.asyncio
async def test_reindex_asset_partial_failure(wiki_structure: WikiStructure) -> None:
    concept_path = wiki_structure.get_concept_file_path("asset-note")
    concept_path.write_text("## Compiled Truth\nBody", encoding="utf-8")
    indexer = _make_indexer(sidecars=False, assets=True)
    asset_indexer = MagicMock()
    asset_indexer.index_all = AsyncMock(return_value=AssetIndexResult(indexed=1, skipped=0, failed=2))

    result = await reindex_published_vectors(
        wiki_structure,
        indexer,
        asset_indexer=asset_indexer,
    )

    assert result.assets_failed == 2
    assert result.failed == 2
    assert result.errors == ("assets: 2 caption index failure(s)",)


@pytest.mark.asyncio
async def test_reindex_asset_index_raises(wiki_structure: WikiStructure) -> None:
    concept_path = wiki_structure.get_concept_file_path("asset-crash")
    concept_path.write_text("## Compiled Truth\nBody", encoding="utf-8")
    indexer = _make_indexer(sidecars=False, assets=True)
    asset_indexer = MagicMock()
    asset_indexer.index_all = AsyncMock(side_effect=RuntimeError("asset boom"))

    result = await reindex_published_vectors(
        wiki_structure,
        indexer,
        asset_indexer=asset_indexer,
    )

    assert result.failed == 1
    assert result.errors == ("assets: asset boom",)
