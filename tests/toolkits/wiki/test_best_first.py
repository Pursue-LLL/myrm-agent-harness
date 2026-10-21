import hashlib

import pytest

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig, WikiQueryConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.best_first import (
    RetrievalSeed,
    converge_retrieval_candidates,
    score_claim_overlap,
)
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer
from myrm_agent_harness.toolkits.wiki.retrieval.query import WikiQueryEngine
from myrm_agent_harness.toolkits.wiki.retrieval.tokenizer import extract_query_terms


@pytest.fixture
def wiki_structure(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.fixture
def indexer(wiki_structure):
    return WikiIndexer(wiki_structure, WikiConfig(enable_semantic_search=True))


def test_score_claim_overlap_matches_query_terms() -> None:
    content = """---
claims:
  - id: claim.alpha
    text: Revenue grew fifteen percent year over year
    status: supported
---
"""
    terms = frozenset(extract_query_terms("revenue grew fifteen percent"))
    assert score_claim_overlap(content, terms) > 0.0


def test_score_claim_overlap_prefers_fresh_supported_over_stale_contested(wiki_structure) -> None:
    fresh_raw = wiki_structure.raw_dir / "fresh.md"
    stale_raw = wiki_structure.raw_dir / "stale.md"
    fresh_bytes = b"postgresql production writes fresh"
    stale_bytes = b"postgresql production writes stale"
    fresh_raw.write_bytes(fresh_bytes)
    stale_raw.write_bytes(stale_bytes)
    fresh_pin = hashlib.sha256(fresh_bytes).hexdigest()
    stale_pin = hashlib.sha256(b"original stale content").hexdigest()

    fresh_content = f"""---
claims:
  - id: claim.fresh
    text: Alpha uses PostgreSQL for production writes
    status: supported
    evidence:
      - kind: raw-note
        sourceId: source.fresh
        path: raw/fresh.md
        lines: "1-1"
        weight: 1.0
        confidence: 0.9
        contentSha256: {fresh_pin}
---
"""
    stale_content = f"""---
claims:
  - id: claim.stale
    text: Alpha uses PostgreSQL for production writes
    status: contested
    evidence:
      - kind: raw-note
        sourceId: source.stale
        path: raw/stale.md
        lines: "1-1"
        weight: 1.0
        confidence: 0.9
        contentSha256: {stale_pin}
---
"""
    terms = frozenset(extract_query_terms("postgresql production writes"))
    fresh_score = score_claim_overlap(fresh_content, terms, structure=wiki_structure)
    stale_score = score_claim_overlap(stale_content, terms, structure=wiki_structure)
    assert fresh_score > stale_score


def test_best_first_prefers_fresh_supported_claim_concept(wiki_structure, indexer) -> None:
    fresh_raw = wiki_structure.raw_dir / "fresh.md"
    stale_raw = wiki_structure.raw_dir / "stale.md"
    fresh_bytes = b"postgresql production writes fresh"
    stale_bytes = b"postgresql production writes stale"
    fresh_raw.write_bytes(fresh_bytes)
    stale_raw.write_bytes(stale_bytes)
    fresh_pin = hashlib.sha256(fresh_bytes).hexdigest()
    stale_pin = hashlib.sha256(b"original stale content").hexdigest()

    fresh_path = wiki_structure.get_concept_file_path("AlphaFresh")
    stale_path = wiki_structure.get_concept_file_path("AlphaStale")
    fresh_path.parent.mkdir(parents=True, exist_ok=True)
    fresh_path.write_text(
        f"""---
claims:
  - id: claim.fresh
    text: Alpha uses PostgreSQL for production writes
    status: supported
    evidence:
      - kind: raw-note
        sourceId: source.fresh
        path: raw/fresh.md
        lines: "1-1"
        weight: 1.0
        confidence: 0.9
        contentSha256: {fresh_pin}
---
## Compiled Truth
Fresh alpha claim.
""",
        encoding="utf-8",
    )
    stale_path.write_text(
        f"""---
claims:
  - id: claim.stale
    text: Alpha uses PostgreSQL for production writes
    status: contested
    evidence:
      - kind: raw-note
        sourceId: source.stale
        path: raw/stale.md
        lines: "1-1"
        weight: 1.0
        confidence: 0.9
        contentSha256: {stale_pin}
---
## Compiled Truth
Stale contested alpha claim.
""",
        encoding="utf-8",
    )

    query_config = WikiQueryConfig(best_first_max_expansions=0)
    results = converge_retrieval_candidates(
        query="postgresql production writes",
        query_config=query_config,
        structure=wiki_structure,
        indexer=indexer,
        seeds=[
            RetrievalSeed("AlphaFresh", 1.0, "index"),
            RetrievalSeed("AlphaStale", 1.0, "index"),
        ],
        max_results=2,
    )
    assert results[0] == "AlphaFresh"
    assert results[1] == "AlphaStale"


def test_best_first_prefers_high_weight_neighbor(wiki_structure, indexer) -> None:
    for name in ("AlphaNode", "BetaNode", "GammaNode"):
        path = wiki_structure.get_concept_file_path(name)
        path.write_text(f"## Compiled Truth\n{name}.", encoding="utf-8")

    indexer.upsert_edges("AlphaNode", ["BetaNode", "GammaNode"])
    with indexer._get_conn() as conn:
        conn.execute(
            "UPDATE wiki_edges SET weight = ? WHERE source = ? AND target = ?", (10.0, "AlphaNode", "BetaNode")
        )
        conn.execute(
            "UPDATE wiki_edges SET weight = ? WHERE source = ? AND target = ?", (1.0, "AlphaNode", "GammaNode")
        )

    query_config = WikiQueryConfig(best_first_max_expansions=8)
    results = converge_retrieval_candidates(
        query="",
        query_config=query_config,
        structure=wiki_structure,
        indexer=indexer,
        seeds=[RetrievalSeed("AlphaNode", 1.0, "index")],
        max_results=2,
    )
    assert results == ["AlphaNode", "BetaNode"]


def _write_pages(wiki_structure: WikiStructure, names: list[str]) -> None:
    for name in names:
        path = wiki_structure.get_concept_file_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"## Compiled Truth\n{name}.", encoding="utf-8")


def _converge(wiki_structure, indexer, seeds: list[RetrievalSeed], *, max_results: int = 5, **config: int) -> list[str]:
    return converge_retrieval_candidates(
        query="",
        query_config=WikiQueryConfig(**config),
        structure=wiki_structure,
        indexer=indexer,
        seeds=seeds,
        max_results=max_results,
    )


def test_best_first_hub_page_does_not_discard_other_seeds_and_neighbours(wiki_structure, indexer) -> None:
    topics = [f"Topics/T{i:02d}" for i in range(40)]
    _write_pages(wiki_structure, [*topics, "Hub/Map", "Other/DirectHit"])
    indexer.upsert_edges("Hub/Map", topics)

    results = _converge(
        wiki_structure,
        indexer,
        [RetrievalSeed("Hub/Map", 0.9, "fts"), RetrievalSeed("Other/DirectHit", 0.8, "fts")],
    )

    assert len(results) == 5
    assert results[:2] == ["Hub/Map", "Other/DirectHit"]
    assert all(name.startswith("Topics/") for name in results[2:])


def test_best_first_missing_neighbours_do_not_spend_the_budget(wiki_structure, indexer) -> None:
    _write_pages(wiki_structure, ["Dev/Deploy", "Real/One", "Real/Two", "Other/DirectHit"])
    ghosts = [f"ghost-{i}" for i in range(40)]
    indexer.upsert_edges("Dev/Deploy", [*ghosts, "Real/One", "Real/Two"])

    results = _converge(
        wiki_structure,
        indexer,
        [RetrievalSeed("Dev/Deploy", 0.9, "fts"), RetrievalSeed("Other/DirectHit", 0.8, "fts")],
    )

    assert set(results) == {"Dev/Deploy", "Other/DirectHit", "Real/One", "Real/Two"}


def test_best_first_budget_bounds_queued_neighbours(wiki_structure, indexer) -> None:
    topics = [f"Topics/T{i:02d}" for i in range(10)]
    _write_pages(wiki_structure, [*topics, "Hub/Map"])
    indexer.upsert_edges("Hub/Map", topics)
    seeds = [RetrievalSeed("Hub/Map", 0.9, "fts")]

    budgeted = _converge(wiki_structure, indexer, seeds, max_results=20, best_first_max_expansions=3)
    assert budgeted[0] == "Hub/Map"
    assert len(budgeted) == 4
    assert set(budgeted[1:]) <= set(topics)
    assert _converge(wiki_structure, indexer, seeds, max_results=20, best_first_max_expansions=0) == ["Hub/Map"]


@pytest.mark.asyncio
async def test_raw_claim_mode_prioritizes_matching_claim(wiki_structure) -> None:
    from unittest.mock import AsyncMock

    from langchain_core.messages import AIMessage

    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content="answer")

    claim_path = wiki_structure.get_concept_file_path("Finance/Revenue")
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    claim_path.write_text(
        """---
claims:
  - id: claim.revenue
    text: Annual revenue increased by fifteen percent
    status: supported
---
## Compiled Truth
Annual revenue increased by fifteen percent
""",
        encoding="utf-8",
    )

    noise_path = wiki_structure.get_concept_file_path("Finance/Noise")
    noise_path.write_text(
        "## Compiled Truth\nAnnual revenue noise without structured claims.",
        encoding="utf-8",
    )

    config = WikiConfig(enable_semantic_search=False)
    auto_engine = WikiQueryEngine(
        llm=llm,
        structure=wiki_structure,
        config=config,
        query_config=WikiQueryConfig(query_mode="auto"),
    )
    raw_engine = WikiQueryEngine(
        llm=llm,
        structure=wiki_structure,
        config=config,
        query_config=WikiQueryConfig(query_mode="raw_claim"),
    )

    question = "annual revenue increased fifteen percent"
    auto_result = await auto_engine.query(question)
    raw_result = await raw_engine.query(question)

    assert any("finance/revenue" in article.lower() for article in auto_result.related_articles)
    assert raw_result.related_articles
    assert "finance/revenue" in str(raw_result.related_articles[0]).lower()
