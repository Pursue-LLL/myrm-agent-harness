"""Tests for wiki asset indexer."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.asset_index import WikiAssetIndexer


class _StubCaptionProvider:
    def __init__(self, captions: dict[str, str]) -> None:
        self._captions = captions
        self.calls: list[str] = []

    async def caption_file(self, path: Path) -> str:
        self.calls.append(path.name)
        return self._captions.get(path.name, f"Caption for {path.stem}")


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path / "vault")
    structure.ensure_structure()
    return structure


@pytest.fixture
def assets_dir(wiki_structure: WikiStructure) -> Path:
    assets = wiki_structure.wiki_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    return assets


@pytest.mark.asyncio
async def test_asset_index_sha256_skip(wiki_structure: WikiStructure, assets_dir: Path) -> None:
    image = assets_dir / "diagram.png"
    image.write_bytes(b"fake-png-bytes")

    provider = _StubCaptionProvider({})
    config = WikiConfig(enable_asset_index=True, enable_hybrid_search=False)
    indexer = WikiAssetIndexer(wiki_structure, config, caption_provider=provider)

    first = await indexer.index_file(image)
    second = await indexer.index_file(image)

    assert first is True
    assert second is False
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_asset_search_fts(wiki_structure: WikiStructure, assets_dir: Path) -> None:
    image = assets_dir / "payment-flow.png"
    image.write_bytes(b"payment-diagram")

    provider = _StubCaptionProvider({"payment-flow.png": "Checkout payment sequence with gateway"})
    config = WikiConfig(enable_asset_index=True, enable_hybrid_search=False)
    indexer = WikiAssetIndexer(wiki_structure, config, caption_provider=provider)
    await indexer.index_file(image)

    hits = await indexer.search("payment gateway sequence", limit=5)
    assert hits
    assert hits[0].filename == "payment-flow.png"
    assert "Checkout payment" in hits[0].caption


@pytest.mark.asyncio
async def test_scan_image_references(wiki_structure: WikiStructure, assets_dir: Path) -> None:
    concept_path = wiki_structure.concepts_dir / "Payment.md"
    concept_path.parent.mkdir(parents=True, exist_ok=True)
    concept_path.write_text("# Payment\n\n![diagram](payment-flow.png)\n", encoding="utf-8")

    config = WikiConfig(enable_asset_index=True)
    indexer = WikiAssetIndexer(wiki_structure, config, caption_provider=_StubCaptionProvider({}))
    refs = indexer.scan_image_references()

    assert refs["payment-flow.png"] == ["Payment"]


@pytest.mark.asyncio
async def test_purge_orphan_entries(wiki_structure: WikiStructure, assets_dir: Path) -> None:
    image = assets_dir / "removed-diagram.png"
    image.write_bytes(b"orphan-test")

    provider = _StubCaptionProvider({"removed-diagram.png": "Diagram that will be deleted from disk"})
    config = WikiConfig(enable_asset_index=True, enable_hybrid_search=False)
    indexer = WikiAssetIndexer(wiki_structure, config, caption_provider=provider)
    await indexer.index_file(image)

    hits = await indexer.search("deleted diagram", limit=3)
    assert hits

    image.unlink()
    purged = await indexer.purge_orphan_entries()
    assert purged == 1

    hits_after = await indexer.search("deleted diagram", limit=3)
    assert not hits_after


@pytest.mark.asyncio
async def test_asset_recall_gate_meets_baseline(wiki_structure: WikiStructure, assets_dir: Path) -> None:
    """CI anchor: caption FTS must retrieve indexed asset by semantic query."""
    image = assets_dir / "architecture-diagram.png"
    image.write_bytes(b"diagram-bytes")

    provider = _StubCaptionProvider(
        {"architecture-diagram.png": "Microservice architecture diagram with API gateway and payment service"}
    )
    config = WikiConfig(enable_asset_index=True, enable_hybrid_search=False)
    indexer = WikiAssetIndexer(wiki_structure, config, caption_provider=provider)
    await indexer.index_file(image)

    hits = await indexer.search("payment service architecture diagram", limit=3)
    assert hits, "asset recall gate: expected at least one hit"
    assert hits[0].filename == "architecture-diagram.png"
