from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.claims_contract import parse_claims_from_content
from myrm_agent_harness.toolkits.wiki.core.config import WikiCompileConfig, WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


@pytest.fixture
def wiki_structure(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content="## Compiled Truth\nGenerated article content.")
    return llm


@pytest.fixture
def mock_indexer():
    indexer = AsyncMock(spec=WikiIndexer)
    indexer.upsert = AsyncMock()
    return indexer


@pytest.mark.asyncio
async def test_wiki_compiler_generate_article(wiki_structure, mock_llm, mock_indexer):
    config = WikiConfig()
    compile_config = WikiCompileConfig(require_approval=False)
    compiler = WikiCompiler(mock_llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    # We mock _generate_article directly since process() might involve multiple steps
    # We can test process but let's test the core generation first
    class DummyConcept:
        name = "Test Concept"
        reason = "test"
        source_files = ("test.md",)

    await compiler._generate_article(DummyConcept())

    # Verify file is written with structured claims
    article_path = wiki_structure.get_concept_file_path("Test Concept")
    assert article_path.exists()
    saved = article_path.read_text(encoding="utf-8")
    assert "Generated article content." in saved
    claims = parse_claims_from_content(saved)
    assert len(claims) == 1
    assert claims[0].evidence[0].path == "test.md"

    # Verify indexer is called
    mock_indexer.upsert.assert_awaited_once()
    upsert_content = mock_indexer.upsert.await_args.args[1]
    assert "Generated article content." in upsert_content
    assert parse_claims_from_content(upsert_content)


@pytest.mark.asyncio
async def test_wiki_compiler_require_approval(wiki_structure, mock_llm, mock_indexer):
    config = WikiConfig()
    compile_config = WikiCompileConfig(require_approval=True)
    compiler = WikiCompiler(mock_llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    class DummyConcept:
        name = "Test Concept"
        reason = "test"
        source_files = ("test.md",)

    await compiler._generate_article(DummyConcept())

    # File should not exist directly
    article_path = wiki_structure.get_concept_file_path("Test Concept")
    assert not article_path.exists()

    # Indexer should NOT be called directly
    mock_indexer.upsert.assert_not_called()

    # Instead, check if pending edit was added
    from myrm_agent_harness.toolkits.wiki.pipeline.pending import WikiPendingEditsManager

    mgr = WikiPendingEditsManager(wiki_structure)
    edits = mgr.get_pending_edits()
    assert len(edits) == 1
    assert edits[0]["concept_name"] == "Test Concept"
    assert parse_claims_from_content(edits[0]["proposed_content"])


@pytest.mark.asyncio
async def test_generate_articles_batch_records_embed_pause(wiki_structure, mock_llm, mock_indexer):
    from myrm_agent_harness.toolkits.retriever.embedding.window_policy import EmbedInputTooLargeError
    from myrm_agent_harness.toolkits.wiki.core.types import ConceptInfo
    from myrm_agent_harness.toolkits.wiki.pipeline.resilience import EMBED_WINDOW_VIOLATION

    compiler = WikiCompiler(
        mock_llm,
        wiki_structure,
        WikiConfig(),
        WikiCompileConfig(require_approval=False, min_concept_mentions=1),
        indexer=mock_indexer,
    )

    async def _raise_embed(concept: ConceptInfo) -> str:
        raise EmbedInputTooLargeError(
            token_count=900,
            limit=512,
            model="test-embed",
            parent_key=concept.name,
        )

    compiler._generate_article = _raise_embed  # type: ignore[method-assign]

    concepts = [
        ConceptInfo(name="Big Doc", definition="large compiled truth", mentions=1, source_files=["a.md"])
    ]
    stats = await compiler._generate_articles_batch(concepts)

    assert stats.embed_pause_kind == EMBED_WINDOW_VIOLATION
    assert "900" in stats.embed_pause_reason
    assert stats.blocked == 1
