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


def test_best_first_prefers_high_weight_neighbor(wiki_structure, indexer) -> None:
    for name in ("AlphaNode", "BetaNode", "GammaNode"):
        path = wiki_structure.get_concept_file_path(name)
        path.write_text(f"## Compiled Truth\n{name}.", encoding="utf-8")

    indexer.upsert_edges("AlphaNode", ["BetaNode", "GammaNode"])
    with indexer._get_conn() as conn:
        conn.execute("UPDATE wiki_edges SET weight = ? WHERE source = ? AND target = ?", (10.0, "AlphaNode", "BetaNode"))
        conn.execute("UPDATE wiki_edges SET weight = ? WHERE source = ? AND target = ?", (1.0, "AlphaNode", "GammaNode"))

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
