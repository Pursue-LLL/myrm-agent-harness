"""LangChain tools for Wiki toolkit.

[INPUT]
langchain_core.tools::tool (POS: LangChain tool decorator)
.pipeline.compiler::WikiCompiler (POS: Wiki compilation core engine)
.maintenance.linter::WikiLinter (POS: Wiki health maintenance core engine)
.retrieval.query::WikiQueryEngine (POS: Wiki query and enhancement engine)
.core.structure::WikiStructure (POS: Wiki file system abstraction layer)
myrm_agent_harness.toolkits.web_fetch.markdown_generator::MarkdownGenerator (POS: HTML to Markdown converter)

[OUTPUT]
create_wiki_tools(): creates 4 LangChain tools (ingest, compile, query, maintain)

[POS]
LangChain tool integration layer for Wiki toolkit. Wraps WikiCompiler, WikiQueryEngine,
and WikiLinter into 4 LangChain StructuredTools for Agent use. Provides end-to-end
automation: ingest triggers compilation, query archives high-value results for knowledge
compounding, and URL fetching uses proper HTML-to-Markdown conversion.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .core.structure import WikiStructure
from .maintenance.linter import WikiLinter
from .pipeline.compiler import WikiCompiler
from .retrieval.query import WikiQueryEngine

logger = get_agent_logger(__name__)

_BINARY_DOC_EXTENSIONS = frozenset({".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"})
_LARGE_DOC_CHUNK_THRESHOLD = 80_000


def create_wiki_tools(
    compiler: WikiCompiler,
    query_engine: WikiQueryEngine,
    linter: WikiLinter,
    structure: WikiStructure,
) -> list:
    """
    Create all wiki tools.

    Args:
        compiler: WikiCompiler instance
        query_engine: WikiQueryEngine instance
        linter: WikiLinter instance
        structure: WikiStructure instance

    Returns:
        List of LangChain tools
    """

    @tool("wiki_ingest_tool")
    async def wiki_ingest(
        source: Annotated[str, "URL or file path to ingest"],
        filename: Annotated[str, "Optional custom filename"] = "",
        folder_path: Annotated[
            str, "Optional logical folder path to categorize this document (e.g., 'Research/AI')"
        ] = "",
    ) -> str:
        """
        Ingest a document into the wiki raw/ directory.

        Supports:
        - Web URLs (will download and convert to markdown)
        - Local file paths (will copy to raw/)
        - Plain text or markdown content

        Use this when users want to add documents to their knowledge base.
        If a folder_path is provided, the document will be placed in that subdirectory.
        """
        logger.info(f"Ingesting: {source[:100]}")

        try:
            if source.startswith("http://") or source.startswith("https://"):
                content = await _fetch_url_as_markdown(source)
                filename = filename or f"web_{hashlib.sha256(source.encode()).hexdigest()[:12]}.md"
            elif len(source) < 260 and "\n" not in source and Path(source).exists():
                src_path = Path(source)
                ext = src_path.suffix.lower()
                if ext in _BINARY_DOC_EXTENSIONS:
                    content = await _parse_binary_document(str(src_path))
                else:
                    content = src_path.read_text(encoding="utf-8")
                filename = filename or src_path.name
                if not filename.endswith(".md"):
                    filename = Path(filename).stem + ".md"
            else:
                content = source
                filename = filename or f"text_{hashlib.sha256(source.encode()).hexdigest()[:12]}.md"

            if folder_path:
                safe_folder = structure._sanitize_path(folder_path)
                full_path = f"{safe_folder}/{filename}"
            else:
                full_path = filename

            chunks = _split_if_large(content, full_path)
            ingested_count = 0

            for chunk_path, chunk_content in chunks:
                raw_path = structure.get_raw_file_path(chunk_path)
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(chunk_content, encoding="utf-8")
                compiler.enqueue_file(raw_path)
                ingested_count += 1

            logger.info(f"Ingested {ingested_count} chunk(s) for: {full_path}")
            suffix = f" ({ingested_count} chunks)" if ingested_count > 1 else ""
            return f"Successfully ingested document: {full_path}{suffix}. Compilation queued."

        except Exception as e:
            logger.error(f"Failed to ingest {source}: {e}")
            return f"Failed to ingest document: {e}"

    @tool("wiki_compile_tool")
    async def wiki_compile() -> str:
        """
        Force-compile all pending raw documents into wiki articles.

        Normally compilation runs automatically after ingestion.
        Use this to manually trigger a full compilation pass, or to
        recompile after bulk-importing documents outside the wiki tools.

        Generates concept articles, index, and cross-references.
        Uses incremental compilation (skips unchanged documents).
        """
        logger.info("Compiling wiki")

        try:
            result = await compiler.compile_all()

            return (
                f"Wiki compilation complete:\n"
                f"- Concepts: {result.concepts_count}\n"
                f"- Articles: {result.articles_generated}\n"
                f"- Backlinks: {result.backlinks_created}\n"
                f"- Duration: {result.duration_ms}ms"
            )

        except Exception as e:
            logger.error(f"Compilation failed: {e}")
            return f"Compilation failed: {e}"

    @tool("wiki_query_tool")
    async def wiki_query(question: Annotated[str, "Question to ask the wiki"]) -> dict | str:
        """
        Query the wiki knowledge base.

        Searches relevant wiki articles and returns the context.
        Use this when users ask questions about topics in their knowledge base.
        """
        logger.info(f"Querying wiki: {question[:100]}")

        try:
            result = await query_engine.query(question)

            if not result.related_articles:
                return "No relevant information found in wiki. Consider ingesting more documents."

            from myrm_agent_harness.utils.context_format import wrap_with_external_sources_tag

            wrapped_context = wrap_with_external_sources_tag(result.answer, source="LLM-Wiki")

            sources = []
            for path_str in result.related_articles:
                p = Path(path_str)
                sources.append(
                    {
                        "type": "knowledge",
                        "kb_name": "LLM-Wiki",
                        "filename": p.stem,
                        "score": result.confidence_score,
                    }
                )

            if result.should_archive:
                try:
                    _archive_query_result(structure, compiler, question, result.answer)
                except Exception as archive_err:
                    logger.warning(f"Query archive failed (non-blocking): {archive_err}")

            return {"content": wrapped_context, "metadata": {"sources": sources}}

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return f"Query failed: {e}"

    @tool("wiki_maintain_tool")
    async def wiki_maintain() -> str:
        """
        Run wiki health checks and automatic maintenance.

        Performs:
        - Broken link detection
        - Completeness checks (find short/incomplete articles)
        - Consistency checks (find contradictions)
        - Automatic repairs (enhance incomplete articles)
        - Connection discovery (find potential cross-references)
        - Knowledge graph gap analysis (isolated/bridge concepts)

        Use this periodically to keep the wiki healthy.
        Recommended frequency: once per day or after major updates.
        """
        logger.info("Running wiki maintenance")

        try:
            result = await linter.lint_and_maintain()

            output = (
                f"Wiki maintenance complete:\n"
                f"- Issues found: {result.issues_found}\n"
                f"- Issues fixed: {result.issues_fixed}\n"
                f"- New connections: {result.connections_discovered}\n"
                f"- Duration: {result.duration_ms}ms"
            )

            gaps = [i for i in result.issues if i.issue_type == "knowledge_gap"]
            if gaps:
                top = [f"{g.location}: {g.description}" for g in gaps[:5]]
                output += f"\n- Knowledge gaps ({len(gaps)}): " + "; ".join(top)

            return output

        except Exception as e:
            logger.error(f"Maintenance failed: {e}")
            return f"Maintenance failed: {e}"

    return [wiki_ingest, wiki_compile, wiki_query, wiki_maintain]


def _archive_query_result(
    structure: WikiStructure,
    compiler: WikiCompiler,
    question: str,
    answer: str,
) -> None:
    """Archive a high-quality Q&A pair back into raw/ for knowledge compounding."""
    content = f"# Query\n\n{question}\n\n# Answer\n\n{answer}"
    doc_hash = hashlib.sha256(question.encode()).hexdigest()[:12]
    filename = f"query_archive_{doc_hash}.md"

    raw_path = structure.get_raw_file_path(filename)
    if raw_path.exists():
        return

    raw_path.write_text(content, encoding="utf-8")
    compiler.enqueue_file(raw_path)
    logger.info(f"Archived query result for knowledge compounding: {filename}")


async def _parse_binary_document(file_path: str) -> str:
    """Parse binary document (PDF/DOCX/XLSX/PPTX) into Markdown text via file_parsers."""
    from myrm_agent_harness.toolkits.file_parsers import get_parser, is_supported

    if not is_supported(file_path):
        raise ValueError(f"Unsupported file type: {Path(file_path).suffix}")

    parser = get_parser(file_path)
    text = await parser.parse(file_path)
    if not text or not text.strip():
        raise ValueError(f"Parser returned empty content for: {file_path}")
    return text


def _split_if_large(
    content: str, base_path: str
) -> list[tuple[str, str]]:
    """Split large content into chunks for better wiki compilation.

    Returns list of (relative_path, content) tuples. For small documents,
    returns a single entry with the original path.
    """
    if len(content) <= _LARGE_DOC_CHUNK_THRESHOLD:
        return [(base_path, content)]

    from myrm_agent_harness.toolkits.retriever.splitter import TextChunker

    chunker = TextChunker(min_chunk_tokens=200)
    docs = chunker.chunk_text(content, document_metadata={"title": Path(base_path).stem})

    if len(docs) <= 1:
        return [(base_path, content)]

    stem = Path(base_path).stem
    parent = str(Path(base_path).parent) if Path(base_path).parent != Path(".") else ""
    results: list[tuple[str, str]] = []

    for i, doc in enumerate(docs, 1):
        chunk_name = f"{stem}_chunk{i:03d}.md"
        chunk_path = f"{parent}/{chunk_name}" if parent else chunk_name
        results.append((chunk_path, doc.page_content))

    logger.info(f"Split large document into {len(results)} chunks: {stem}")
    return results


async def _fetch_url_as_markdown(url: str) -> str:
    """Fetch URL and convert HTML to clean Markdown using the web_fetch toolkit's MarkdownGenerator."""
    import aiohttp

    from myrm_agent_harness.toolkits.web_fetch.markdown_generator import MarkdownGenerator

    headers = {"User-Agent": "Myrm-Agent-Wiki/1.0 (knowledge-ingestion)"}
    async with (
        aiohttp.ClientSession(headers=headers) as session,
        session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response,
    ):
        if response.status != 200:
            raise ValueError(f"Failed to fetch {url}: HTTP {response.status}")
        html = await response.text()

    generator = MarkdownGenerator()
    result = generator.generate_markdown(html, base_url=url, citations=False)
    return result.raw_markdown or f"# {url}\n\n(empty page)"
