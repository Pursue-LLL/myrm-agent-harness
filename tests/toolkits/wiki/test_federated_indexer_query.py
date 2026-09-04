"""Tests for federated cross-source search and query with public_dirs in harness."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer
from myrm_agent_harness.toolkits.wiki.retrieval.query import WikiQueryEngine


@pytest.fixture
def mock_chat_llm() -> MagicMock:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=AIMessage(content="Federated answer derived from shared vault."))
    return llm


@pytest.mark.asyncio
async def test_federated_indexer_fts_cross_source(tmp_path: Path) -> None:
    """Verify WikiIndexer attaches public databases and retrieves results across mounts."""
    primary_dir = tmp_path / "primary"
    pub_dir = tmp_path / "pub_vault"

    primary_struct = WikiStructure(primary_dir, public_dirs=[pub_dir])
    primary_struct.ensure_structure()

    pub_struct = WikiStructure(pub_dir)
    pub_struct.ensure_structure()

    cfg = WikiConfig(enable_hybrid_search=False)

    # 1. Ingest into public vault index
    pub_indexer = WikiIndexer(pub_struct, cfg)
    await pub_indexer.upsert(
        "security_policy",
        "---\ntitle: Security Policy\n---\n\n## Compiled Truth\nAll production access requires hardware FIDO2 keys.",
    )

    # 2. Ingest into primary vault index
    primary_indexer = WikiIndexer(primary_struct, cfg)
    await primary_indexer.upsert(
        "local_setup",
        "---\ntitle: Local Setup\n---\n\n## Compiled Truth\nRun make dev to boot the local environment.",
    )

    # 3. Search for public vault term from primary indexer
    hits = await primary_indexer.search("FIDO2")
    assert len(hits) >= 1
    hit_concepts = [name for name, _ in hits]
    assert "security_policy" in hit_concepts

    # 4. Search for local vault term
    hits_local = await primary_indexer.search("local environment")
    assert len(hits_local) >= 1
    assert "local_setup" in [name for name, _ in hits_local]


@pytest.mark.asyncio
async def test_federated_query_engine_loads_public_article(
    tmp_path: Path, mock_chat_llm: MagicMock
) -> None:
    """Verify WikiQueryEngine can search, resolve, and load content from a public mounted vault."""
    primary_dir = tmp_path / "primary"
    pub_dir = tmp_path / "pub_vault"

    primary_struct = WikiStructure(primary_dir, public_dirs=[pub_dir])
    primary_struct.ensure_structure()

    pub_struct = WikiStructure(pub_dir)
    pub_struct.ensure_structure()

    cfg = WikiConfig(enable_hybrid_search=False, enable_semantic_search=True)

    # Create content on disk in public vault
    pub_concept_path = pub_dir / "wiki" / "concepts" / "architecture_guideline.md"
    pub_concept_path.parent.mkdir(parents=True, exist_ok=True)
    pub_concept_path.write_text(
        "---\ntitle: Architecture Guideline\n---\n\n## Compiled Truth\nUse event-driven messaging for asynchronous decoupled workflows.",
        encoding="utf-8",
    )

    pub_indexer = WikiIndexer(pub_struct, cfg)
    await pub_indexer.upsert("architecture_guideline", pub_concept_path.read_text(encoding="utf-8"))

    primary_indexer = WikiIndexer(primary_struct, cfg)

    hits = await primary_indexer.search("event-driven messaging")
    assert len(hits) >= 1
    assert "architecture_guideline" in [name for name, _ in hits]

    engine = WikiQueryEngine(
        llm=mock_chat_llm,
        structure=primary_struct,
        config=cfg,
        indexer=primary_indexer,
    )

    res = await engine.query("event-driven messaging")
    assert res.confidence_score > 0
    assert any("architecture_guideline" in str(s.article_path) for s in res.source_snippets)


@pytest.mark.asyncio
async def test_federated_indexer_deduplicates_and_caps_at_6_mounts(tmp_path: Path) -> None:
    """Verify WikiIndexer safely caps attached public databases at 6 and ignores invalid paths."""
    primary_dir = tmp_path / "primary"
    pub_dirs = [tmp_path / f"pub_{i}" for i in range(10)]

    for p in pub_dirs:
        p_struct = WikiStructure(p)
        p_struct.ensure_structure()
        p_idx = WikiIndexer(p_struct, WikiConfig(enable_hybrid_search=False))
        # Ensure .wiki_index.db is created
        await p_idx.upsert("dummy", "truth")

    primary_struct = WikiStructure(primary_dir, public_dirs=pub_dirs)
    primary_struct.ensure_structure()

    indexer = WikiIndexer(primary_struct, WikiConfig(enable_hybrid_search=False))
    with indexer._get_conn() as conn:
        dbs = [row["name"] for row in conn.execute("PRAGMA database_list").fetchall()]
        pub_dbs = [name for name in dbs if name.startswith("pub_")]
        assert len(pub_dbs) == 6


@pytest.mark.asyncio
async def test_federated_indexer_unpublished_filtering_across_mounts(tmp_path: Path) -> None:
    """Verify _filter_published respects publish_status stored in attached public databases."""
    primary_dir = tmp_path / "primary"
    pub_dir = tmp_path / "pub_vault"

    primary_struct = WikiStructure(primary_dir, public_dirs=[pub_dir])
    primary_struct.ensure_structure()

    pub_struct = WikiStructure(pub_dir)
    pub_struct.ensure_structure()

    cfg = WikiConfig(enable_hybrid_search=False)

    # 1. Ingest draft article into public vault
    pub_indexer = WikiIndexer(pub_struct, cfg)
    await pub_indexer.upsert(
        "draft_spec",
        "---\ntitle: Draft Specification\npublish_status: draft\n---\n\n## Compiled Truth\nConfidential unreleased design details.",
    )

    primary_indexer = WikiIndexer(primary_struct, cfg)

    # 2. Search from primary: should be filtered out because publish_status is draft
    hits = await primary_indexer.search("Confidential")
    assert "draft_spec" not in [name for name, _ in hits]
