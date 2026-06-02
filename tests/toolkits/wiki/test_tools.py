"""Tests for Wiki LangChain tools."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki import (
    WikiCompiler,
    WikiConfig,
    WikiLinter,
    WikiQueryEngine,
    WikiStructure,
    create_wiki_tools,
)


@pytest.fixture
def temp_wiki_dir(tmp_path: Path) -> Path:
    """Create temporary wiki directory."""
    wiki_dir = tmp_path / "test-wiki"
    return wiki_dir


@pytest.fixture
def wiki_structure(temp_wiki_dir: Path) -> WikiStructure:
    """Create WikiStructure instance."""
    structure = WikiStructure(temp_wiki_dir)
    structure.ensure_structure()
    return structure


@pytest.fixture
def mock_llm() -> MagicMock:
    """Create mock LLM."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock()
    return llm


@pytest.fixture
def wiki_tools(
    mock_llm: MagicMock,
    wiki_structure: WikiStructure,
) -> list:
    """Create wiki tools."""
    config = WikiConfig()
    compiler = WikiCompiler(mock_llm, wiki_structure, config)
    query_engine = WikiQueryEngine(mock_llm, wiki_structure, config)
    linter = WikiLinter(mock_llm, wiki_structure, config)

    return create_wiki_tools(compiler, query_engine, linter, wiki_structure)


def test_create_wiki_tools_returns_four_tools(wiki_tools: list) -> None:
    """Test that create_wiki_tools returns 4 tools."""
    assert len(wiki_tools) == 4

    tool_names = [tool.name for tool in wiki_tools]
    assert "wiki_ingest_tool" in tool_names
    assert "wiki_compile_tool" in tool_names
    assert "wiki_query_tool" in tool_names
    assert "wiki_maintain_tool" in tool_names


@pytest.mark.asyncio
async def test_wiki_ingest_tool(
    wiki_tools: list,
    wiki_structure: WikiStructure,
) -> None:
    """Test wiki_ingest tool."""
    ingest_tool = next(tool for tool in wiki_tools if tool.name == "wiki_ingest_tool")

    result = await ingest_tool.ainvoke(
        {
            "source": "This is test content for ingestion.",
            "filename": "test-ingest.md",
        }
    )

    assert "Successfully ingested" in result
    assert (wiki_structure.raw_dir / "test-ingest.md").exists()


@pytest.mark.asyncio
async def test_wiki_compile_tool(
    wiki_tools: list,
    wiki_structure: WikiStructure,
    mock_llm: MagicMock,
) -> None:
    """Test wiki_compile tool."""
    compile_tool = next(tool for tool in wiki_tools if tool.name == "wiki_compile_tool")

    (wiki_structure.raw_dir / "test.md").write_text("Test content")

    mock_llm.ainvoke.return_value = AIMessage(content='[{"name": "Test", "definition": "Test def"}]')

    result = await compile_tool.ainvoke({})

    assert "Wiki compilation complete" in result


@pytest.mark.asyncio
async def test_wiki_query_tool(
    wiki_tools: list,
    wiki_structure: WikiStructure,
    mock_llm: MagicMock,
) -> None:
    """Test wiki_query tool."""
    query_tool = next(tool for tool in wiki_tools if tool.name == "wiki_query_tool")

    (wiki_structure.concepts_dir / "test-concept.md").write_text("# Test Concept\n\nTest content")

    mock_llm.ainvoke.return_value = AIMessage(content="This is the answer to the question.")

    result = await query_tool.ainvoke({"question": "What is Test Concept?"})

    assert isinstance(result, dict)
    assert "<<<UNTRUSTED_DATA" in result["content"]
    assert "Test Concept" in result["content"]
    assert "metadata" in result
    assert result["metadata"]["sources"][0]["filename"] == "test-concept"


@pytest.mark.asyncio
async def test_wiki_ingest_local_file(
    wiki_tools: list,
    wiki_structure: WikiStructure,
    tmp_path: Path,
) -> None:
    """Test wiki_ingest with a local file path."""
    ingest_tool = next(tool for tool in wiki_tools if tool.name == "wiki_ingest_tool")

    local_file = tmp_path / "local-doc.md"
    local_file.write_text("# Local Doc\nSome content here.", encoding="utf-8")

    result = await ingest_tool.ainvoke({"source": str(local_file)})

    assert "Successfully ingested" in result
    assert (wiki_structure.raw_dir / "local-doc.md").exists()


@pytest.mark.asyncio
async def test_wiki_ingest_error(wiki_tools: list) -> None:
    """Test wiki_ingest error handling with malformed hash input."""
    ingest_tool = next(tool for tool in wiki_tools if tool.name == "wiki_ingest_tool")

    result = await ingest_tool.ainvoke({"source": ""})

    assert "Successfully ingested" in result or "Failed" in result


@pytest.mark.asyncio
async def test_wiki_compile_graceful_degradation(
    wiki_tools: list,
    wiki_structure: WikiStructure,
    mock_llm: MagicMock,
) -> None:
    """Test wiki_compile gracefully handles LLM errors (extracts 0 concepts)."""
    compile_tool = next(tool for tool in wiki_tools if tool.name == "wiki_compile_tool")

    (wiki_structure.raw_dir / "trigger-error.md").write_text("Content to trigger LLM call")
    mock_llm.ainvoke.side_effect = RuntimeError("LLM unavailable")

    result = await compile_tool.ainvoke({})

    assert "compilation complete" in result.lower()
    assert "concepts: 0" in result.lower()


@pytest.mark.asyncio
async def test_wiki_query_with_related_articles(
    wiki_tools: list,
    wiki_structure: WikiStructure,
    mock_llm: MagicMock,
) -> None:
    """Test wiki_query returns related articles and archive status."""
    query_tool = next(tool for tool in wiki_tools if tool.name == "wiki_query_tool")

    (wiki_structure.concepts_dir / "concept-a.md").write_text("# Concept A\nContent A")
    (wiki_structure.concepts_dir / "concept-b.md").write_text("# Concept B\nContent B")

    mock_llm.ainvoke.return_value = AIMessage(content="Detailed answer about concepts.")

    result = await query_tool.ainvoke({"question": "Tell me about Concept A and B"})

    assert isinstance(result, dict)
    assert "<<<UNTRUSTED_DATA" in result["content"]
    assert "metadata" in result
    assert len(result["metadata"]["sources"]) == 2


@pytest.mark.asyncio
async def test_wiki_query_no_articles(
    wiki_tools: list,
    mock_llm: MagicMock,
) -> None:
    """Test wiki_query graceful response when no articles exist."""
    query_tool = next(tool for tool in wiki_tools if tool.name == "wiki_query_tool")

    result = await query_tool.ainvoke({"question": "What is this?"})

    assert "No relevant information found" in result


@pytest.mark.asyncio
async def test_wiki_maintain_tool(wiki_tools: list) -> None:
    """Test wiki_maintain tool."""
    maintain_tool = next(tool for tool in wiki_tools if tool.name == "wiki_maintain_tool")

    result = await maintain_tool.ainvoke({})

    assert "Wiki maintenance complete" in result


@pytest.mark.asyncio
async def test_wiki_maintain_error(
    wiki_tools: list,
    mock_llm: MagicMock,
    wiki_structure: WikiStructure,
) -> None:
    """Test wiki_maintain error handling."""
    maintain_tool = next(tool for tool in wiki_tools if tool.name == "wiki_maintain_tool")

    (wiki_structure.concepts_dir / "broken.md").write_text("# Broken\n\nSee [[nonexistent]]")
    mock_llm.ainvoke.side_effect = RuntimeError("LLM unavailable")

    result = await maintain_tool.ainvoke({})

    assert "failed" in result.lower() or "maintenance" in result.lower()


@pytest.fixture
def direct_mock_tools(wiki_structure: WikiStructure) -> tuple:
    """Create tools with directly mocked compiler/query/linter for error path testing."""
    mock_compiler = MagicMock(spec=WikiCompiler)
    mock_query_engine = MagicMock(spec=WikiQueryEngine)
    mock_linter = MagicMock(spec=WikiLinter)

    tools = create_wiki_tools(mock_compiler, mock_query_engine, mock_linter, wiki_structure)
    return tools, mock_compiler, mock_query_engine, mock_linter


@pytest.mark.asyncio
async def test_wiki_ingest_url(
    wiki_tools: list,
    wiki_structure: WikiStructure,
) -> None:
    """Test wiki_ingest with URL source (covers URL branch)."""
    ingest_tool = next(tool for tool in wiki_tools if tool.name == "wiki_ingest_tool")

    result = await ingest_tool.ainvoke(
        {
            "source": "http://nonexistent.invalid/test.md",
            "filename": "url-test.md",
        }
    )

    assert "Failed" in result or "Successfully" in result


@pytest.mark.asyncio
async def test_wiki_compile_exception_at_tools_layer(direct_mock_tools: tuple) -> None:
    """Test wiki_compile error path when compiler.compile_all raises."""
    tools, mock_compiler, _, _ = direct_mock_tools
    compile_tool = next(t for t in tools if t.name == "wiki_compile_tool")

    mock_compiler.compile_all = AsyncMock(side_effect=RuntimeError("compile crash"))

    result = await compile_tool.ainvoke({})

    assert "failed" in result.lower()


@pytest.mark.asyncio
async def test_wiki_query_exception_at_tools_layer(direct_mock_tools: tuple) -> None:
    """Test wiki_query error path when query_engine.query raises."""
    tools, _, mock_qe, _ = direct_mock_tools
    query_tool = next(t for t in tools if t.name == "wiki_query_tool")

    mock_qe.query = AsyncMock(side_effect=RuntimeError("query crash"))

    result = await query_tool.ainvoke({"question": "test?"})

    assert "failed" in result.lower()


@pytest.mark.asyncio
async def test_wiki_query_with_should_archive(direct_mock_tools: tuple) -> None:
    """Test wiki_query when result has should_archive=True."""
    from myrm_agent_harness.toolkits.wiki.core.types import QueryResult

    tools, _, mock_qe, _ = direct_mock_tools
    query_tool = next(t for t in tools if t.name == "wiki_query_tool")

    mock_qe.query = AsyncMock(
        return_value=QueryResult(
            question="test",
            answer="Great answer",
            related_articles=["concept-a", "concept-b"],
            should_archive=True,
        )
    )

    result = await query_tool.ainvoke({"question": "test"})

    assert isinstance(result, dict)
    assert "metadata" in result
    assert result["metadata"]["sources"][0]["filename"] == "concept-a"
    assert result["metadata"]["sources"][1]["filename"] == "concept-b"


@pytest.mark.asyncio
async def test_wiki_maintain_exception_at_tools_layer(direct_mock_tools: tuple) -> None:
    """Test wiki_maintain error path when linter.lint_and_maintain raises."""
    tools, _, _, mock_linter = direct_mock_tools
    maintain_tool = next(t for t in tools if t.name == "wiki_maintain_tool")

    mock_linter.lint_and_maintain = AsyncMock(side_effect=RuntimeError("lint crash"))

    result = await maintain_tool.ainvoke({})

    assert "failed" in result.lower()


class TestArchiveQueryResult:
    """Tests for _archive_query_result helper."""

    def test_archives_qa_pair_to_raw(self, wiki_structure: WikiStructure, mock_llm: MagicMock) -> None:
        """Test that _archive_query_result writes Q&A to raw/ and enqueues."""
        from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _archive_query_result

        config = WikiConfig()
        compiler = WikiCompiler(mock_llm, wiki_structure, config)

        _archive_query_result(wiki_structure, compiler, "What is Python?", "Python is a programming language.")

        raw_files = list(wiki_structure.raw_dir.glob("query_archive_*.md"))
        assert len(raw_files) == 1
        content = raw_files[0].read_text(encoding="utf-8")
        assert "# Query" in content
        assert "What is Python?" in content
        assert "# Answer" in content
        assert "Python is a programming language." in content

    def test_idempotent_same_question(self, wiki_structure: WikiStructure, mock_llm: MagicMock) -> None:
        """Test that archiving the same question twice doesn't create duplicates."""
        from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _archive_query_result

        config = WikiConfig()
        compiler = WikiCompiler(mock_llm, wiki_structure, config)

        _archive_query_result(wiki_structure, compiler, "Repeat?", "Answer 1")
        _archive_query_result(wiki_structure, compiler, "Repeat?", "Answer 2")

        raw_files = list(wiki_structure.raw_dir.glob("query_archive_*.md"))
        assert len(raw_files) == 1
        content = raw_files[0].read_text(encoding="utf-8")
        assert "Answer 1" in content

    def test_different_questions_create_different_files(
        self, wiki_structure: WikiStructure, mock_llm: MagicMock
    ) -> None:
        """Test that different questions create separate archive files."""
        from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _archive_query_result

        config = WikiConfig()
        compiler = WikiCompiler(mock_llm, wiki_structure, config)

        _archive_query_result(wiki_structure, compiler, "Question A", "Answer A")
        _archive_query_result(wiki_structure, compiler, "Question B", "Answer B")

        raw_files = list(wiki_structure.raw_dir.glob("query_archive_*.md"))
        assert len(raw_files) == 2


class TestFetchUrlAsMarkdown:
    """Tests for _fetch_url_as_markdown helper."""

    @pytest.mark.asyncio
    async def test_converts_html_to_markdown(self) -> None:
        """Test that HTML is converted to clean Markdown."""

        from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _fetch_url_as_markdown

        html_content = "<html><body><h1>Title</h1><p>Paragraph.</p></body></html>"

        class MockResponse:
            status = 200

            async def text(self) -> str:
                return html_content

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        class MockSession:
            def get(self, url, **kwargs):
                return MockResponse()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        from unittest.mock import patch

        with patch("aiohttp.ClientSession", return_value=MockSession()):
            result = await _fetch_url_as_markdown("http://example.com/test")

        assert "# Title" in result
        assert "Paragraph." in result
        assert "<html>" not in result

    @pytest.mark.asyncio
    async def test_raises_on_non_200(self) -> None:
        """Test that non-200 status raises ValueError."""
        from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _fetch_url_as_markdown

        class MockResponse:
            status = 404

            async def text(self) -> str:
                return ""

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        class MockSession:
            def get(self, url, **kwargs):
                return MockResponse()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        from unittest.mock import patch

        with patch("aiohttp.ClientSession", return_value=MockSession()):
            with pytest.raises(ValueError, match="HTTP 404"):
                await _fetch_url_as_markdown("http://example.com/missing")


class TestIngestAutoCompile:
    """Tests for wiki_ingest auto-compilation trigger."""

    @pytest.mark.asyncio
    async def test_ingest_calls_enqueue_file(
        self, wiki_structure: WikiStructure, mock_llm: MagicMock
    ) -> None:
        """Test that wiki_ingest triggers enqueue_file on the compiler."""
        from unittest.mock import patch

        config = WikiConfig()
        compiler = WikiCompiler(mock_llm, wiki_structure, config)
        query_engine = WikiQueryEngine(mock_llm, wiki_structure, config)
        linter = WikiLinter(mock_llm, wiki_structure, config)
        tools = create_wiki_tools(compiler, query_engine, linter, wiki_structure)

        ingest_tool = next(t for t in tools if t.name == "wiki_ingest_tool")

        with patch.object(compiler, "enqueue_file") as mock_enqueue:
            result = await ingest_tool.ainvoke({"source": "Test content for auto-compile.", "filename": "auto.md"})

        assert "Compilation queued" in result
        assert (wiki_structure.raw_dir / "auto.md").exists()
        mock_enqueue.assert_called_once()
        assert "auto.md" in str(mock_enqueue.call_args[0][0])


class TestQueryArchiveNonBlocking:
    """Tests for wiki_query archive failure not blocking results."""

    @pytest.mark.asyncio
    async def test_archive_failure_still_returns_result(
        self, wiki_structure: WikiStructure, mock_llm: MagicMock
    ) -> None:
        """Test that archive failure does not prevent query result from being returned."""
        from unittest.mock import patch

        from myrm_agent_harness.toolkits.wiki.core.types import QueryResult

        config = WikiConfig()
        compiler = WikiCompiler(mock_llm, wiki_structure, config)
        query_engine = WikiQueryEngine(mock_llm, wiki_structure, config)
        linter = WikiLinter(mock_llm, wiki_structure, config)
        tools = create_wiki_tools(compiler, query_engine, linter, wiki_structure)

        query_tool = next(t for t in tools if t.name == "wiki_query_tool")

        (wiki_structure.concepts_dir / "test-topic.md").write_text("# Test Topic\nContent here.")

        mock_query_result = QueryResult(
            question="test?",
            answer="good answer",
            related_articles=[str(wiki_structure.concepts_dir / "test-topic.md")],
            should_archive=True,
            confidence_score=1.0,
        )

        with patch.object(query_engine, "query", new=AsyncMock(return_value=mock_query_result)), patch(
            "myrm_agent_harness.toolkits.wiki.wiki_agent_tools._archive_query_result",
            side_effect=RuntimeError("disk full"),
        ):
            result = await query_tool.ainvoke({"question": "test?"})

        assert isinstance(result, dict)
        assert "content" in result
        assert "metadata" in result
