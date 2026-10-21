"""Tests for Evidence Closure v2: confidence SSOT and retrieval trace wiring."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.best_first import score_claim_overlap
from myrm_agent_harness.toolkits.wiki.retrieval.query import WikiQueryEngine
from myrm_agent_harness.toolkits.wiki.retrieval.tokenizer import extract_query_terms


@pytest.fixture
def wiki_structure(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content="answer")
    return llm


def test_score_claim_overlap_applies_explicit_confidence(wiki_structure) -> None:
    content = """---
claims:
  - id: claim.alpha
    text: Revenue grew fifteen percent year over year
    status: supported
    confidence: 0.95
---
"""
    low_confidence = """---
claims:
  - id: claim.beta
    text: Revenue grew fifteen percent year over year
    status: supported
---
"""
    terms = frozenset(extract_query_terms("revenue grew fifteen percent"))
    high_score = score_claim_overlap(content, terms, structure=wiki_structure)
    baseline_score = score_claim_overlap(low_confidence, terms, structure=wiki_structure)
    assert high_score > baseline_score


@pytest.mark.asyncio
async def test_query_confidence_is_not_hardcoded_one(wiki_structure, mock_llm) -> None:
    config = WikiConfig(enable_semantic_search=False)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

    concept_path = wiki_structure.get_concept_file_path("Budget")
    concept_path.parent.mkdir(parents=True, exist_ok=True)
    concept_path.write_text(
        """---
claims:
  - id: claim.budget
    text: Budget is fifty million for Q3
    status: supported
    confidence: 0.92
---
## Compiled Truth
Budget is fifty million for Q3.
""",
        encoding="utf-8",
    )

    result = await engine.query("budget fifty million Q3")
    assert result.confidence_score > 0.0
    assert result.confidence_score < 1.0


@pytest.mark.asyncio
async def test_query_engine_prefers_fresh_supported_over_stale_contested(wiki_structure, mock_llm) -> None:
    config = WikiConfig(enable_semantic_search=False)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

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
    confidence: 0.91
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
    confidence: 0.92
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

    result = await engine.query("postgresql production writes")
    assert result.related_articles
    assert "AlphaFresh" in result.related_articles[0] or "alphafresh" in result.related_articles[0].lower()


@pytest.mark.asyncio
async def test_query_exposes_retrieval_trace_with_index_hit(wiki_structure, mock_llm) -> None:
    config = WikiConfig(enable_semantic_search=False)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

    index_path = wiki_structure.get_index_file_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        """## concept
- [[Finance/Budget]] — Quarterly budget planning and approvals
""",
        encoding="utf-8",
    )

    concept_path = wiki_structure.get_concept_file_path("Finance/Budget")
    concept_path.parent.mkdir(parents=True, exist_ok=True)
    concept_path.write_text(
        """---
claims:
  - id: claim.budget
    text: Budget approval happens every quarter
    status: supported
---
## Compiled Truth
Budget approval happens every quarter.
""",
        encoding="utf-8",
    )

    result = await engine.query("budget approval quarter")
    assert result.retrieval_trace is not None
    assert result.retrieval_trace.index_hits
    assert result.retrieval_trace.selected_concepts
