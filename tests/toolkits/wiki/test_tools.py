"""Tests for Wiki LangChain tools."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.toolkits.wiki import (
    WikiCompiler,
    WikiConfig,
    WikiLinter,
    WikiQueryEngine,
    WikiStructure,
    create_wiki_admin_tools,
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
    """Create agent-facing wiki tools."""
    config = WikiConfig()
    compiler = WikiCompiler(mock_llm, wiki_structure, config)
    query_engine = WikiQueryEngine(mock_llm, wiki_structure, config)
    linter = WikiLinter(mock_llm, wiki_structure, config)

    return create_wiki_tools(compiler, query_engine, linter, wiki_structure)


@pytest.fixture
def wiki_admin_tools(
    mock_llm: MagicMock,
    wiki_structure: WikiStructure,
) -> list:
    """Create compile/maintain wiki tools for admin paths."""
    config = WikiConfig()
    compiler = WikiCompiler(mock_llm, wiki_structure, config)
    linter = WikiLinter(mock_llm, wiki_structure, config)
    return create_wiki_admin_tools(compiler, linter)


def test_create_wiki_tools_returns_two_tools(wiki_tools: list) -> None:
    """Test that create_wiki_tools returns agent-facing tools only."""
    assert len(wiki_tools) == 2

    tool_names = [tool.name for tool in wiki_tools]
    assert "wiki_ingest_tool" in tool_names
    assert "wiki_query_tool" in tool_names
    assert "wiki_compile_tool" not in tool_names
    assert "wiki_maintain_tool" not in tool_names


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
    wiki_admin_tools: list,
    wiki_structure: WikiStructure,
    mock_llm: MagicMock,
) -> None:
    """Test wiki_compile tool."""
    compile_tool = next(tool for tool in wiki_admin_tools if tool.name == "wiki_compile_tool")

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
    wiki_admin_tools: list,
    wiki_structure: WikiStructure,
    mock_llm: MagicMock,
) -> None:
    """Test wiki_compile gracefully handles LLM errors (extracts 0 concepts)."""
    compile_tool = next(tool for tool in wiki_admin_tools if tool.name == "wiki_compile_tool")

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
async def test_wiki_maintain_tool(wiki_admin_tools: list) -> None:
    """Test wiki_maintain tool."""
    maintain_tool = next(tool for tool in wiki_admin_tools if tool.name == "wiki_maintain_tool")

    result = await maintain_tool.ainvoke({})

    assert "Wiki maintenance complete" in result


@pytest.mark.asyncio
async def test_wiki_maintain_error(
    wiki_admin_tools: list,
    mock_llm: MagicMock,
    wiki_structure: WikiStructure,
) -> None:
    """Test wiki_maintain error handling."""
    maintain_tool = next(tool for tool in wiki_admin_tools if tool.name == "wiki_maintain_tool")

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
    tools.extend(create_wiki_admin_tools(mock_compiler, mock_linter))
    return tools, mock_compiler, mock_query_engine, mock_linter


@pytest.mark.asyncio
async def test_wiki_ingest_url(
    wiki_tools: list,
    wiki_structure: WikiStructure,
) -> None:
    """Test wiki_ingest with URL source (covers URL branch)."""
    from unittest.mock import patch

    ingest_tool = next(tool for tool in wiki_tools if tool.name == "wiki_ingest_tool")

    with patch(
        "myrm_agent_harness.toolkits.wiki.wiki_agent_tools._fetch_url_as_markdown",
        new_callable=AsyncMock,
        return_value="# URL Doc\n\nFetched content.",
    ):
        result = await ingest_tool.ainvoke(
            {
                "source": "https://example.com/test.md",
                "filename": "url-test.md",
            }
        )

    assert "Successfully ingested" in result
    assert (wiki_structure.raw_dir / "url-test.md").exists()


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
        """Test that HTML is converted to clean Markdown via secure_get fallback."""

        from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _fetch_url_as_markdown

        html_content = "<html><body><h1>Title</h1><p>Paragraph.</p></body></html>"

        from unittest.mock import AsyncMock, patch

        mock_response = type("MockResponse", (), {"status_code": 200, "text": html_content})()

        with patch(
            "myrm_agent_harness.toolkits.web_fetch.web_fetch_tools.crawl",
            new_callable=AsyncMock,
            side_effect=RuntimeError("FetchEngine unavailable"),
        ), patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await _fetch_url_as_markdown("http://example.com/test")

        assert "# Title" in result
        assert "Paragraph." in result
        assert "<html>" not in result

    @pytest.mark.asyncio
    async def test_raises_on_non_200(self) -> None:
        """Test that non-200 status raises ValueError via secure_get fallback."""
        from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _fetch_url_as_markdown

        from unittest.mock import AsyncMock, patch

        mock_response = type("MockResponse", (), {"status_code": 404, "text": ""})()

        with patch(
            "myrm_agent_harness.toolkits.web_fetch.web_fetch_tools.crawl",
            new_callable=AsyncMock,
            side_effect=RuntimeError("FetchEngine unavailable"),
        ), patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            with pytest.raises(ValueError, match="HTTP 404"):
                await _fetch_url_as_markdown("http://example.com/missing")

    @pytest.mark.asyncio
    async def test_uses_fetch_engine_when_available(self) -> None:
        from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _fetch_url_as_markdown

        mock_doc = MagicMock()
        mock_doc.page_content = "# Crawled\n\nFrom engine."

        with patch(
            "myrm_agent_harness.toolkits.web_fetch.web_fetch_tools.crawl",
            new_callable=AsyncMock,
            return_value=mock_doc,
        ):
            result = await _fetch_url_as_markdown("https://example.com/page")

        assert "From engine" in result


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


@pytest.mark.asyncio
async def test_wiki_ingest_local_txt_with_folder(
    wiki_tools: list,
    wiki_structure: WikiStructure,
    tmp_path: Path,
) -> None:
    """Local non-md files get .md suffix and optional folder_path."""
    ingest_tool = next(tool for tool in wiki_tools if tool.name == "wiki_ingest_tool")

    local_file = tmp_path / "notes.txt"
    local_file.write_text("Plain notes", encoding="utf-8")

    result = await ingest_tool.ainvoke(
        {
            "source": str(local_file),
            "folder_path": "Research/Notes",
        }
    )

    assert "Successfully ingested" in result
    assert (wiki_structure.raw_dir / "Research" / "Notes" / "notes.md").exists()


@pytest.mark.asyncio
async def test_wiki_ingest_binary_document(
    wiki_tools: list,
    wiki_structure: WikiStructure,
    tmp_path: Path,
) -> None:
    """Binary documents route through _parse_binary_document."""
    from unittest.mock import patch

    ingest_tool = next(tool for tool in wiki_tools if tool.name == "wiki_ingest_tool")
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    with patch(
        "myrm_agent_harness.toolkits.wiki.wiki_agent_tools._parse_binary_document",
        new_callable=AsyncMock,
        return_value="# Parsed PDF\n\nBody",
    ):
        result = await ingest_tool.ainvoke({"source": str(pdf_path)})

    assert "Successfully ingested" in result
    assert (wiki_structure.raw_dir / "report.md").exists()


@pytest.mark.asyncio
async def test_wiki_maintain_reports_knowledge_gaps(direct_mock_tools: tuple) -> None:
    """Maintain tool surfaces knowledge_gap issues when present."""
    from myrm_agent_harness.toolkits.wiki.core.types import LintIssue, LintResult

    tools, _, _, mock_linter = direct_mock_tools
    maintain_tool = next(t for t in tools if t.name == "wiki_maintain_tool")

    mock_linter.lint_and_maintain = AsyncMock(
        return_value=LintResult(
            issues_found=1,
            issues_fixed=0,
            connections_discovered=0,
            duration_ms=12,
            issues=[
                LintIssue(
                    issue_type="knowledge_gap",
                    severity="medium",
                    location="concept-x",
                    description="Missing bridge to concept-y",
                )
            ],
        )
    )

    result = await maintain_tool.ainvoke({})

    assert "Knowledge gaps" in result
    assert "concept-x" in result


class TestParseBinaryDocument:
    """Tests for _parse_binary_document helper."""

    @pytest.mark.asyncio
    async def test_parses_supported_file(self, tmp_path: Path) -> None:
        from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _parse_binary_document

        doc_path = tmp_path / "sheet.txt"
        doc_path.write_text("tabular data", encoding="utf-8")

        with patch(
            "myrm_agent_harness.toolkits.file_parsers.is_supported",
            return_value=True,
        ), patch(
            "myrm_agent_harness.toolkits.file_parsers.get_parser",
        ) as get_parser:
            parser = MagicMock()
            parser.parse = AsyncMock(return_value="# Sheet\nData")
            get_parser.return_value = parser
            text = await _parse_binary_document(str(doc_path))

        assert "Sheet" in text

    @pytest.mark.asyncio
    async def test_raises_for_unsupported_or_empty(self, tmp_path: Path) -> None:
        from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _parse_binary_document

        bad_path = tmp_path / "unknown.bin"
        bad_path.write_bytes(b"data")

        with patch(
            "myrm_agent_harness.toolkits.file_parsers.is_supported",
            return_value=False,
        ):
            with pytest.raises(ValueError, match="Unsupported file type"):
                await _parse_binary_document(str(bad_path))


class TestIngestPathTraversalDefense:
    """Real end-to-end path traversal defense: no mock on path security."""

    @pytest.mark.asyncio
    async def test_traversal_filename_stripped_by_tool(
        self, wiki_tools: list, wiki_structure: WikiStructure
    ) -> None:
        """Malicious filename with ../ is stripped to just the leaf name."""
        ingest_tool = next(t for t in wiki_tools if t.name == "wiki_ingest_tool")
        result = await ingest_tool.ainvoke(
            {"source": "Payload content", "filename": "../../../etc/cron.d/evil.md"}
        )
        assert "Successfully ingested" in result
        assert (wiki_structure.raw_dir / "evil.md").exists()
        assert not (wiki_structure.raw_dir.parent / "etc").exists()

    @pytest.mark.asyncio
    async def test_absolute_path_filename_stripped(
        self, wiki_tools: list, wiki_structure: WikiStructure
    ) -> None:
        """Absolute path in filename is stripped to leaf name."""
        ingest_tool = next(t for t in wiki_tools if t.name == "wiki_ingest_tool")
        result = await ingest_tool.ainvoke(
            {"source": "Payload", "filename": "/tmp/hacked.md"}
        )
        assert "Successfully ingested" in result
        assert (wiki_structure.raw_dir / "hacked.md").exists()

    @pytest.mark.asyncio
    async def test_traversal_with_folder_path(
        self, wiki_tools: list, wiki_structure: WikiStructure
    ) -> None:
        """Traversal in filename combined with folder_path is still safe."""
        ingest_tool = next(t for t in wiki_tools if t.name == "wiki_ingest_tool")
        result = await ingest_tool.ainvoke(
            {
                "source": "Content",
                "filename": "../../passwd.md",
                "folder_path": "Research/AI",
            }
        )
        assert "Successfully ingested" in result
        assert (wiki_structure.raw_dir / "research" / "ai" / "passwd.md").exists()

    @pytest.mark.asyncio
    async def test_normal_ingest_still_works(
        self, wiki_tools: list, wiki_structure: WikiStructure
    ) -> None:
        """Normal filenames still work correctly after security hardening."""
        ingest_tool = next(t for t in wiki_tools if t.name == "wiki_ingest_tool")
        result = await ingest_tool.ainvoke(
            {"source": "Normal doc", "filename": "my-notes.md"}
        )
        assert "Successfully ingested" in result
        assert (wiki_structure.raw_dir / "my-notes.md").exists()
        content = (wiki_structure.raw_dir / "my-notes.md").read_text()
        assert content == "Normal doc"

    @pytest.mark.asyncio
    async def test_backslash_traversal(
        self, wiki_tools: list, wiki_structure: WikiStructure
    ) -> None:
        """Windows-style backslash traversal is neutralized."""
        ingest_tool = next(t for t in wiki_tools if t.name == "wiki_ingest_tool")
        result = await ingest_tool.ainvoke(
            {"source": "Content", "filename": "..\\..\\evil.md"}
        )
        assert "Successfully ingested" in result
        assert not (wiki_structure.raw_dir.parent.parent / "evil.md").exists()

    @pytest.mark.asyncio
    async def test_empty_filename_auto_generated(
        self, wiki_tools: list, wiki_structure: WikiStructure
    ) -> None:
        """Empty filename triggers auto-generated hash name, safely."""
        ingest_tool = next(t for t in wiki_tools if t.name == "wiki_ingest_tool")
        result = await ingest_tool.ainvoke({"source": "Auto-named content", "filename": ""})
        assert "Successfully ingested" in result
        raw_files = list(wiki_structure.raw_dir.glob("text_*.md"))
        assert len(raw_files) >= 1

    @pytest.mark.asyncio
    async def test_filename_with_special_chars(
        self, wiki_tools: list, wiki_structure: WikiStructure
    ) -> None:
        """Filenames with spaces/special chars are preserved (no traversal)."""
        ingest_tool = next(t for t in wiki_tools if t.name == "wiki_ingest_tool")
        result = await ingest_tool.ainvoke(
            {"source": "Content", "filename": "my document (v2).md"}
        )
        assert "Successfully ingested" in result
        assert (wiki_structure.raw_dir / "my document (v2).md").exists()

    @pytest.mark.asyncio
    async def test_folder_path_traversal_sanitized(
        self, wiki_tools: list, wiki_structure: WikiStructure
    ) -> None:
        """Traversal in folder_path is sanitized by _sanitize_path."""
        ingest_tool = next(t for t in wiki_tools if t.name == "wiki_ingest_tool")
        result = await ingest_tool.ainvoke(
            {
                "source": "Content",
                "filename": "safe.md",
                "folder_path": "../../../etc",
            }
        )
        assert "Successfully ingested" in result
        assert not (wiki_structure.raw_dir.parent / "etc" / "safe.md").exists()

    @pytest.mark.asyncio
    async def test_double_dot_without_slash_accepted(
        self, wiki_tools: list, wiki_structure: WikiStructure
    ) -> None:
        """Filename '..evil.md' (no slash) is a valid name, not traversal."""
        ingest_tool = next(t for t in wiki_tools if t.name == "wiki_ingest_tool")
        result = await ingest_tool.ainvoke(
            {"source": "Content", "filename": "..evil.md"}
        )
        assert "Successfully ingested" in result
        assert (wiki_structure.raw_dir / "..evil.md").exists()


class TestSplitIfLarge:
    """Tests for _split_if_large helper."""

    def test_returns_single_chunk_for_small_content(self) -> None:
        from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _split_if_large

        chunks = _split_if_large("small doc", "notes.md")
        assert chunks == [("notes.md", "small doc")]

    def test_splits_large_content_into_multiple_chunks(self) -> None:
        from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _split_if_large

        huge = "paragraph\n\n" * 20_000
        chunks = _split_if_large(huge, "Research/big.md")

        assert len(chunks) > 1
        assert all(name.endswith(".md") for name, _ in chunks)
        assert chunks[0][0].startswith("Research/")

