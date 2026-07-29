"""LangChain tools for Wiki toolkit.

[INPUT]
langchain_core.tools::tool (POS: LangChain tool decorator)
.pipeline.compiler::WikiCompiler (POS: Wiki compilation core engine)
.maintenance.linter::WikiLinter (POS: Wiki health maintenance core engine)
.retrieval.query::WikiQueryEngine (POS: Wiki query and enhancement engine)
.core.structure::WikiStructure (POS: Wiki file system abstraction layer)
toolkits.web_fetch::web_fetch_tools (POS: Global FetchEngine singleton — YouTube/Bilibili subtitle extraction, multi-tier fallback)
toolkits.web_fetch.markdown_generator::MarkdownGenerator (POS: HTML to Markdown converter, fallback path)
core.security.http.secure_fetch::secure_get (POS: SSRF-protected outbound HTTP, fallback path)

[OUTPUT]
create_wiki_tools(): creates 3 LangChain agent tools (ingest, query, apply)
create_wiki_admin_tools(): creates compile/maintain tools for REST and tests
_wiki_source_entry(): builds chat citation metadata incl. claim snapshot_status and source_key

[POS]
LangChain tool integration layer for Wiki toolkit. Wraps WikiCompiler, WikiQueryEngine,
and WikiLinter into agent-facing StructuredTools for Agent use. Provides end-to-end
automation: ingest triggers compilation, query archives high-value results for knowledge
compounding, and URL fetching uses FetchEngine (YouTube/Bilibili subtitle extraction, multi-tier fallback).
Query metadata forwards layered citations and read-time evidence snapshot_status for Chat/Settings UI.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .core.structure import WikiStructure
from .core.types import SourceSnippet
from .maintenance.linter import WikiLinter
from .pipeline.compiler import WikiCompiler
from .pipeline.apply import WikiApplyError, WikiApplyOp, WikiApplyRequest, apply_wiki_mutation
from .retrieval.indexer import WikiIndexer
from .retrieval.query import WikiQueryEngine

logger = get_agent_logger(__name__)

_BINARY_DOC_EXTENSIONS = frozenset({".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"})
_LARGE_DOC_CHUNK_THRESHOLD = 80_000


def _wiki_source_dedup_key(snip: SourceSnippet) -> str:
    if snip.claim_id and snip.evidence_path:
        return (
            f"kb:LLM-Wiki:{snip.article_path}:claim:{snip.claim_id}:evidence:{snip.evidence_path}:{snip.line_range}"
        )
    return f"kb:LLM-Wiki:{snip.article_path}:{snip.section}:{snip.level}"


def _wiki_source_entry(snip: SourceSnippet, *, confidence_score: float) -> dict[str, object]:
    display_name = snip.article_name or Path(snip.article_path).stem or "wiki-source"
    entry: dict[str, object] = {
        "type": "knowledge",
        "kb_name": "LLM-Wiki",
        "filename": display_name,
        "score": confidence_score,
        "path": snip.article_path,
        "source_key": _wiki_source_dedup_key(snip),
    }
    if snip.snippet:
        entry["snippet"] = snip.snippet
    if snip.section:
        entry["section"] = snip.section
    if snip.level:
        entry["level"] = snip.level
    if snip.claim_id:
        entry["claim_id"] = snip.claim_id
    if snip.evidence_path:
        entry["evidence_path"] = snip.evidence_path
    if snip.line_range:
        entry["line_range"] = snip.line_range
    if snip.claim_status:
        entry["claim_status"] = snip.claim_status
    if snip.evidence_snapshot_status:
        entry["snapshot_status"] = snip.evidence_snapshot_status
    return entry


def create_wiki_tools(
    compiler: WikiCompiler,
    query_engine: WikiQueryEngine,
    linter: WikiLinter,
    structure: WikiStructure,
) -> list:
    """
    Create agent-facing wiki tools (ingest + query only).

    Compile/maintain are Settings/REST operations and are not exposed to the LLM.
    """
    return create_wiki_agent_tools(compiler, query_engine, structure)


def create_wiki_agent_tools(
    compiler: WikiCompiler,
    query_engine: WikiQueryEngine,
    structure: WikiStructure,
) -> list:
    """Create LangChain tools exposed to the agent at Turn1."""

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

            filename = Path(filename).name

            if folder_path:
                safe_folder = structure._sanitize_path(folder_path)
                full_path = f"{safe_folder}/{filename}"
            else:
                full_path = filename

            chunks = _split_if_large(content, full_path)
            ingested_count = 0

            from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate import (
                RawConflictPolicy,
                RawGateError,
                RawPublishRequest,
                publish_raw,
            )

            for chunk_path, chunk_content in chunks:
                try:
                    result = await publish_raw(
                        structure,
                        RawPublishRequest(
                            relative_path=chunk_path,
                            content=chunk_content,
                            conflict_policy=RawConflictPolicy.FAIL,
                        ),
                        caller="agent",
                    )
                except RawGateError as exc:
                    if exc.code == "raw_conflict":
                        return (
                            f"Raw source already exists with different content: {chunk_path}. "
                            "Use Settings Wiki import to supersede or choose a different filename."
                        )
                    if exc.code == "raw_security_blocked":
                        return (
                            f"Raw source rejected due to sensitive content: {chunk_path}. "
                            "Remove credentials before ingesting."
                        )
                    return f"Failed to ingest document: {exc.message}"

                if result.security_blocked:
                    return (
                        f"Raw source rejected due to sensitive content: {chunk_path}. "
                        "Remove credentials before ingesting."
                    )

                if result.written:
                    compiler.enqueue_file(result.absolute_path)
                    ingested_count += 1

            logger.info(f"Ingested {ingested_count} chunk(s) for: {full_path}")
            suffix = f" ({ingested_count} chunks)" if ingested_count > 1 else ""
            return f"Successfully ingested document: {full_path}{suffix}. Compilation queued."

        except Exception as e:
            logger.error(f"Failed to ingest {source}: {e}")
            return f"Failed to ingest document: {e}"

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

            sources_by_key: dict[str, dict[str, object]] = {}
            ordered_keys: list[str] = []

            for snip in result.source_snippets:
                key = _wiki_source_dedup_key(snip)
                if key in sources_by_key:
                    entry = sources_by_key[key]
                    if snip.snippet:
                        entry["snippet"] = snip.snippet
                    if snip.evidence_snapshot_status:
                        entry["snapshot_status"] = snip.evidence_snapshot_status
                    continue
                sources_by_key[key] = _wiki_source_entry(snip, confidence_score=result.confidence_score)
                ordered_keys.append(key)

            snippet_paths = {snip.article_path for snip in result.source_snippets}
            for path_str in result.related_articles:
                if path_str in snippet_paths:
                    continue
                path_key = f"kb:LLM-Wiki:{path_str}::L2"
                if path_key in sources_by_key:
                    continue
                p = Path(path_str)
                sources_by_key[path_key] = {
                    "type": "knowledge",
                    "kb_name": "LLM-Wiki",
                    "filename": p.stem,
                    "score": result.confidence_score,
                    "path": path_str,
                    "source_key": path_key,
                }
                ordered_keys.append(path_key)

            sources = [sources_by_key[key] for key in ordered_keys]

            if result.should_archive:
                try:
                    await _archive_query_result(structure, compiler, question, result.answer)
                except Exception as archive_err:
                    logger.warning(f"Query archive failed (non-blocking): {archive_err}")

            return {"content": wrapped_context, "metadata": {"sources": sources}}

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return f"Query failed: {e}"

    @tool("wiki_apply_tool")
    async def wiki_apply(
        op: Annotated[
            str,
            "Operation: update_metadata, patch_compiled_truth, append_timeline, or create_note",
        ],
        concept_name: Annotated[str, "Concept path, e.g. 'research/react-hooks'"],
        compiled_truth: Annotated[str, "New Compiled Truth section body"] = "",
        timeline_entry: Annotated[str, "Timeline bullet to append"] = "",
        body: Annotated[str, "Body content for create_note"] = "",
        tags: Annotated[str, "Comma-separated tags for update_metadata/create_note"] = "",
        aliases: Annotated[str, "Comma-separated aliases for update_metadata/create_note"] = "",
        sources: Annotated[str, "Comma-separated source refs for update_metadata/create_note"] = "",
        clear_confidence: Annotated[bool, "Clear frontmatter confidence on update_metadata"] = False,
    ) -> str:
        """
        Apply a narrow, structured mutation to a wiki concept page.

        Protects managed sections (Compiled Truth, Timeline, claims frontmatter).
        Do not use whole-page rewrites; pick the smallest op that fits.
        """
        try:
            apply_op = WikiApplyOp(op.strip().lower())
        except ValueError:
            allowed = ", ".join(
                member.value
                for member in WikiApplyOp
                if member != WikiApplyOp.REPLACE_FULL_DOCUMENT
            )
            return f"Invalid op '{op}'. Allowed: {allowed}"

        def _split_csv(raw: str) -> tuple[str, ...] | None:
            if not raw.strip():
                return None
            return tuple(part.strip() for part in raw.split(",") if part.strip())

        request = WikiApplyRequest(
            op=apply_op,
            concept_name=concept_name.strip(),
            compiled_truth=compiled_truth,
            timeline_entry=timeline_entry,
            body=body,
            tags=_split_csv(tags),
            aliases=_split_csv(aliases),
            sources=_split_csv(sources),
            clear_confidence=clear_confidence,
            provenance="agent",
        )
        indexer = WikiIndexer(structure)
        try:
            result = await apply_wiki_mutation(structure, indexer, request, caller="agent")
        except WikiApplyError as exc:
            return f"Wiki apply failed ({exc.code}): {exc.message}"

        suffix = ""
        if result.created:
            suffix = " (created)"
        elif result.appended is False and apply_op == WikiApplyOp.APPEND_TIMELINE:
            suffix = " (duplicate skipped)"
        return f"{result.message}{suffix}"

    return [wiki_ingest, wiki_query, wiki_apply]


def create_wiki_admin_tools(
    compiler: WikiCompiler,
    linter: WikiLinter,
) -> list:
    """Create compile/maintain tools for REST endpoints and unit tests (not Turn1)."""

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
                f"- Articles generated: {result.articles_generated}\n"
                f"- Published: {result.articles_published}\n"
                f"- Pending review: {result.articles_pending}\n"
                f"- Blocked: {result.articles_blocked}\n"
                f"- Backlinks: {result.backlinks_created}\n"
                f"- Duration: {result.duration_ms}ms"
            )

        except Exception as e:
            logger.error(f"Compilation failed: {e}")
            return f"Compilation failed: {e}"

    @tool("wiki_maintain_tool")
    async def wiki_maintain() -> str:
        """
        Run wiki health checks and automatic maintenance.

        Performs:
        - Broken link detection
        - Completeness checks (report short/incomplete articles; no auto LLM rewrite)
        - Consistency checks (find contradictions)
        - Frontmatter type repairs (via publish gate)
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

    return [wiki_compile, wiki_maintain]


async def _archive_query_result(
    structure: WikiStructure,
    compiler: WikiCompiler,
    question: str,
    answer: str,
) -> None:
    """Archive a high-quality Q&A pair back into raw/ for knowledge compounding."""
    content = f"# Query\n\n{question}\n\n# Answer\n\n{answer}"
    doc_hash = hashlib.sha256(question.encode()).hexdigest()[:12]
    filename = f"query_archive_{doc_hash}.md"

    from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate import (
        RawConflictPolicy,
        RawPublishRequest,
        publish_raw,
    )

    result = await publish_raw(
        structure,
        RawPublishRequest(
            relative_path=filename,
            content=content,
            conflict_policy=RawConflictPolicy.PUT_IF_ABSENT,
        ),
        caller="agent",
    )
    if not result.written:
        return

    compiler.enqueue_file(result.absolute_path)
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
    """Fetch URL via FetchEngine (YouTube/Bilibili subtitle extraction, multi-tier fallback)."""
    try:
        from myrm_agent_harness.toolkits.web_fetch import web_fetch_tools

        doc = await web_fetch_tools.crawl(url)
        if doc and doc.page_content:
            return doc.page_content
        logger.debug("FetchEngine returned empty for %s, falling back to secure_get", url)
    except Exception:
        logger.debug("FetchEngine failed for %s, falling back to secure_get", url)

    from myrm_agent_harness.core.security.http.secure_fetch import secure_get
    from myrm_agent_harness.toolkits.web_fetch.markdown_generator import MarkdownGenerator

    headers = {"User-Agent": "Myrm-Agent-Wiki/1.0 (knowledge-ingestion)"}
    response = await secure_get(url, timeout=30.0, headers=headers)
    if response.status_code != 200:
        raise ValueError(f"Failed to fetch {url}: HTTP {response.status_code}")

    generator = MarkdownGenerator()
    result = generator.generate_markdown(response.text, base_url=url, citations=False)
    return result.raw_markdown or f"# {url}\n\n(empty page)"
