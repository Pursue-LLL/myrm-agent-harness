from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.query import WikiQueryEngine


@pytest.fixture
def wiki_structure(tmp_path):
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.ainvoke.return_value = AIMessage(content="This is the answer from the wiki.")
    return llm


@pytest.mark.asyncio
async def test_wiki_query_engine_fallback(wiki_structure, mock_llm):
    config = WikiConfig(enable_semantic_search=False)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

    # Create some dummy concepts
    concept_path = wiki_structure.get_concept_file_path("Test Concept")
    concept_path.write_text("## Compiled Truth\nHere is a test about gravity.", encoding="utf-8")

    result = await engine.query("What is test?")
    assert result.question == "What is test?"
    assert "Here is a test about gravity" in result.answer
    assert len(result.related_articles) == 1
    assert "test-concept.md" in str(result.related_articles[0])


@pytest.mark.asyncio
async def test_wiki_query_engine_fts5(wiki_structure, mock_llm):
    config = WikiConfig(enable_semantic_search=True)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

    # Upsert to FTS5
    article_path = wiki_structure.get_concept_file_path("Test Concept")
    article_path.write_text("## Compiled Truth\nHere is a test about gravity.", encoding="utf-8")
    await engine._indexer.upsert("Test Concept", "## Compiled Truth\nHere is a test about gravity.")

    result = await engine.query("What is gravity?")
    assert len(result.related_articles) == 1
    assert "test-concept.md" in str(result.related_articles[0])


@pytest.mark.asyncio
async def test_wiki_query_engine_no_results(wiki_structure, mock_llm):
    config = WikiConfig(enable_semantic_search=True)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

    result = await engine.query("Unknown concept")
    assert result.answer == "No relevant information found in wiki. Consider ingesting more documents."
    assert len(result.related_articles) == 0


@pytest.mark.asyncio
async def test_graph_expansion(wiki_structure, mock_llm):
    """_expand_via_graph discovers 1-hop neighbors via weighted edges."""
    config = WikiConfig(enable_semantic_search=True)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

    for name in ("AlphaNode", "BetaNode", "GammaNode"):
        p = wiki_structure.get_concept_file_path(name)
        p.write_text(f"## Compiled Truth\n{name} content.", encoding="utf-8")

    await engine._indexer.upsert("AlphaNode", "## Compiled Truth\nAlphaNode content.")
    engine._indexer.upsert_edges("AlphaNode", ["BetaNode", "GammaNode"])

    expanded = engine._expand_via_graph(["AlphaNode"], max_results=10)
    assert "AlphaNode" in expanded
    assert "BetaNode" in expanded
    assert "GammaNode" in expanded


@pytest.mark.asyncio
async def test_keyword_search_fallback(wiki_structure, mock_llm):
    """When FTS5 returns nothing, _keyword_search should find concepts by content overlap."""
    config = WikiConfig(enable_semantic_search=False)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

    p1 = wiki_structure.get_concept_file_path("DeepLearning")
    p1.write_text("## Compiled Truth\nDeep learning uses neural networks.", encoding="utf-8")
    p2 = wiki_structure.get_concept_file_path("Cooking")
    p2.write_text("## Compiled Truth\nCooking is about food preparation.", encoding="utf-8")

    result = await engine.query("What is deep learning?")
    assert any("deep" in str(a).lower() for a in result.related_articles)


@pytest.mark.asyncio
async def test_load_articles_context_extraction(wiki_structure, mock_llm):
    """_load_articles_context extracts YAML frontmatter + Compiled Truth section."""
    config = WikiConfig(enable_semantic_search=False)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

    p = wiki_structure.get_concept_file_path("TestArticle")
    p.write_text(
        "---\ntitle: Test\nsources: [a.md]\n---\n\n## Compiled Truth\nThe real content.\n\n## Raw Notes\nShould be excluded.",
        encoding="utf-8",
    )

    context = await engine._load_articles_context([p])
    assert "The real content" in context
    assert "Raw Notes" not in context
    assert "sources:" in context
