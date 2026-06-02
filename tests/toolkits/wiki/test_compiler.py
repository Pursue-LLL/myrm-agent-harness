from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

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
        source_files = ["test.md"]

    await compiler._generate_article(DummyConcept())

    # Verify file is written
    article_path = wiki_structure.get_concept_file_path("Test Concept")
    assert article_path.exists()
    assert "Generated article content." in article_path.read_text(encoding="utf-8")

    # Verify indexer is called
    mock_indexer.upsert.assert_awaited_once_with("Test Concept", "## Compiled Truth\nGenerated article content.")


@pytest.mark.asyncio
async def test_wiki_compiler_require_approval(wiki_structure, mock_llm, mock_indexer):
    config = WikiConfig()
    compile_config = WikiCompileConfig(require_approval=True)
    compiler = WikiCompiler(mock_llm, wiki_structure, config, compile_config, indexer=mock_indexer)

    class DummyConcept:
        name = "Test Concept"
        reason = "test"
        source_files = ["test.md"]

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
