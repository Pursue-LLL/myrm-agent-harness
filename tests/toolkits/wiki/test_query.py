from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig, WikiQueryConfig
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
async def test_wiki_query_engine_uses_directory_sidecars(wiki_structure, mock_llm):
    config = WikiConfig(enable_semantic_search=True)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

    article_path = wiki_structure.get_concept_file_path("ProjectA/API")
    article_path.write_text("## Compiled Truth\nAPI supports key rotation.", encoding="utf-8")

    await engine._indexer.upsert("ProjectA/API", "## Compiled Truth\nAPI supports key rotation.")
    await engine._indexer.upsert_sidecar(
        "projecta",
        level=0,
        content="ProjectA service abstraction summary.",
    )
    await engine._indexer.upsert_sidecar(
        "projecta",
        level=1,
        content="ProjectA API and deployment overview.",
    )

    result = await engine.query("How does projecta api work?")
    assert "Directory projecta (L0)" in result.answer
    assert "Directory projecta (L1)" in result.answer
    assert any("projecta/api.md" in article.lower() for article in result.related_articles)
    assert any(s.level == "L0" and s.article_path.endswith("/.abstract.md") for s in result.source_snippets)
    assert any(s.level == "L1" and s.article_path.endswith("/.overview.md") for s in result.source_snippets)
    assert any(s.level == "L2" for s in result.source_snippets)


@pytest.mark.asyncio
async def test_wiki_query_engine_respects_zero_sidecar_directory_budget(wiki_structure, mock_llm):
    config = WikiConfig(enable_semantic_search=True)
    query_config = WikiQueryConfig(max_sidecar_directories=0)
    engine = WikiQueryEngine(
        llm=mock_llm,
        structure=wiki_structure,
        config=config,
        query_config=query_config,
    )

    article_path = wiki_structure.get_concept_file_path("ProjectB/Guide")
    article_path.write_text("## Compiled Truth\nGuide content.", encoding="utf-8")
    await engine._indexer.upsert("ProjectB/Guide", "## Compiled Truth\nGuide content.")
    await engine._indexer.upsert_sidecar("projectb", level=0, content="ProjectB summary.")

    result = await engine.query("ProjectB")
    assert "Directory projectb (L0)" not in result.answer
    assert any("projectb/guide.md" in article.lower() for article in result.related_articles)
    assert all(s.level != "L0" for s in result.source_snippets)


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
    """_load_articles_context extracts YAML frontmatter + Compiled Truth section and citation snippets."""
    config = WikiConfig(enable_semantic_search=False)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

    p = wiki_structure.get_concept_file_path("TestArticle")
    p.write_text(
        "---\ntitle: Test\nsources: [a.md]\n---\n\n## Compiled Truth\nThe real content.\n\n## Raw Notes\nShould be excluded.",
        encoding="utf-8",
    )

    context, snippets = await engine._load_articles_context([p])
    assert "The real content" in context
    assert "Raw Notes" not in context
    assert "sources:" in context
    assert len(snippets) == 1
    assert snippets[0].snippet == "The real content."
    assert snippets[0].section == "Compiled Truth"
    assert snippets[0].article_name == "testarticle"


@pytest.mark.asyncio
async def test_load_articles_context_emits_sidecar_snippets(wiki_structure, mock_llm):
    config = WikiConfig(enable_semantic_search=True)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

    p = wiki_structure.get_concept_file_path("TeamA/Runbook")
    p.write_text("## Compiled Truth\nRunbook details.", encoding="utf-8")
    await engine._indexer.upsert("TeamA/Runbook", "## Compiled Truth\nRunbook details.")
    await engine._indexer.upsert_sidecar("teama", level=0, content="TeamA abstract summary.")
    await engine._indexer.upsert_sidecar("teama", level=1, content="TeamA overview notes.")

    _context, snippets = await engine._load_articles_context([p])
    levels = {snippet.level for snippet in snippets}
    assert {"L0", "L1", "L2"} <= levels
    assert any(snippet.article_path == "teama/.abstract.md" for snippet in snippets)
    assert any(snippet.article_path == "teama/.overview.md" for snippet in snippets)


class TestExtractSnippet:
    """Unit tests for WikiQueryEngine._extract_snippet static method."""

    def test_basic_paragraph(self):
        content = "## Compiled Truth\nFirst paragraph here."
        snippet, section = WikiQueryEngine._extract_snippet(content)
        assert snippet == "First paragraph here."
        assert section == "Compiled Truth"

    def test_empty_content(self):
        snippet, section = WikiQueryEngine._extract_snippet("")
        assert snippet == ""
        assert section == ""

    def test_only_headings(self):
        content = "## Section A\n## Section B\n"
        snippet, section = WikiQueryEngine._extract_snippet(content)
        assert snippet == ""
        assert section == "Section A"

    def test_yaml_frontmatter_stripped(self):
        content = "---\ntitle: Test\n---\n\n## Summary\nActual content."
        snippet, section = WikiQueryEngine._extract_snippet(content)
        assert "title:" not in snippet
        assert snippet == "Actual content."
        assert section == "Summary"

    def test_truncation_at_max_chars(self):
        long_text = "## Info\n" + "A" * 600
        snippet, section = WikiQueryEngine._extract_snippet(long_text, max_chars=500)
        assert snippet.endswith("…")
        raw_part = snippet[:-1]
        assert len(raw_part) <= 500
        assert section == "Info"

    def test_stops_at_first_paragraph_break(self):
        content = "## Topic\nFirst line.\n\nSecond paragraph."
        snippet, section = WikiQueryEngine._extract_snippet(content)
        assert snippet == "First line."
        assert section == "Topic"

    @pytest.mark.asyncio
    async def test_query_populates_source_snippets(self, wiki_structure, mock_llm):
        config = WikiConfig(enable_semantic_search=False)
        engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

        p = wiki_structure.get_concept_file_path("Revenue")
        p.write_text("## Compiled Truth\nRevenue grew by 15.3% year over year.", encoding="utf-8")

        result = await engine.query("What is revenue growth?")
        assert len(result.source_snippets) == 1
        assert "15.3%" in result.source_snippets[0].snippet
        assert result.source_snippets[0].section == "Compiled Truth"


@pytest.mark.asyncio
async def test_load_articles_context_no_compiled_truth(wiki_structure, mock_llm):
    """When article has no Compiled Truth section, full content is used as fallback."""
    config = WikiConfig(enable_semantic_search=False)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

    p = wiki_structure.get_concept_file_path("PlainArticle")
    p.write_text("Just plain text without any section headers.", encoding="utf-8")

    context, snippets = await engine._load_articles_context([p])
    assert "plain text" in context
    assert len(snippets) == 1
    assert "plain text" in snippets[0].snippet


@pytest.mark.asyncio
async def test_load_articles_context_missing_file(wiki_structure, mock_llm):
    """_load_articles_context gracefully handles missing files."""
    config = WikiConfig(enable_semantic_search=False)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

    missing = wiki_structure.get_concept_file_path("NonExistent")
    context, snippets = await engine._load_articles_context([missing])
    assert context == ""
    assert snippets == []


def test_expand_via_graph_empty_seeds(wiki_structure, mock_llm):
    """_expand_via_graph with empty seeds returns empty list."""
    config = WikiConfig(enable_semantic_search=True)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)
    assert engine._expand_via_graph([], max_results=10) == []


@pytest.mark.asyncio
async def test_keyword_search_unreadable_file(wiki_structure, mock_llm):
    """_keyword_search gracefully skips unreadable files."""
    config = WikiConfig(enable_semantic_search=False)
    engine = WikiQueryEngine(llm=mock_llm, structure=wiki_structure, config=config)

    bad_path = Path(wiki_structure.concepts_dir / "broken.md")
    bad_path.write_text("Valid content about quantum physics.", encoding="utf-8")
    bad_path.chmod(0o000)

    try:
        results = engine._keyword_search("quantum", [bad_path], top_n=5)
        assert results == []
    finally:
        bad_path.chmod(0o644)
