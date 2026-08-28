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
retrieval.source_citations::build_wiki_query_sources (POS: Shared wiki citation metadata builder)

[POS]
LangChain tool integration layer for Wiki toolkit. Wraps WikiCompiler, WikiQueryEngine,
and WikiLinter into agent-facing StructuredTools for Agent use. Provides end-to-end
automation: ingest triggers compilation, query archives high-value results for knowledge
compounding, and URL fetching uses FetchEngine (YouTube/Bilibili subtitle extraction, multi-tier fallback).
Query metadata forwards layered citations, asset hit metadata, and read-time evidence snapshot_status for Chat/Settings UI.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Annotated

from langchain_core.tools import tool

from myrm_agent_harness.utils.locale import is_chinese
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .core.frontmatter_contract import WikiProvenance
from .core.structure import WikiStructure
from .maintenance.linter import WikiLinter
from .pipeline.apply import (
    WikiApplyError,
    WikiApplyOp,
    WikiApplyRequest,
    apply_wiki_mutation,
)
from .pipeline.compiler import WikiCompiler
from .retrieval.indexer import WikiIndexer
from .retrieval.query import WikiQueryEngine
from .retrieval.source_citations import (
    attach_wiki_scope_id,
    build_wiki_query_sources,
    format_evidence_cards_context,
)

logger = get_agent_logger(__name__)

_BINARY_DOC_EXTENSIONS = frozenset(
    {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"}
)
_LARGE_DOC_CHUNK_THRESHOLD = 80_000

# ---------------------------------------------------------------------------
# Wiki Tools Multilingual Descriptions (EN / ZH)
# ---------------------------------------------------------------------------

WIKI_INGEST_DESCRIPTION_EN = """Ingest documents into the Wiki knowledge base (supports Web URLs, local files like PDF/Word/Excel/Markdown, or raw text).

Use this when users want to add reference materials or documents to their knowledge base.
If folder_path is provided, the document is categorized under that subdirectory.
Supported inputs:
- Web URLs: fetched and converted to markdown
- Local file paths: text/markdown or parsed binary documents (PDF, DOCX, XLSX, PPTX)
- Raw text: saved as a markdown document
Automatically parsed and queued for knowledge compilation.
"""

WIKI_INGEST_DESCRIPTION_ZH = """将文档录入 Wiki 知识库（支持网页 URL、本地 PDF/Word/Excel/Markdown 等文件或纯文本内容）。

适用场景：用户希望向个人/团队知识库添加参考资料或文档。
若提供 folder_path，文档将归类至该逻辑子目录下。
支持输入类型：
- 网页 URL：抓取并转换为 Markdown
- 本地文件路径：文本/Markdown 或自动解析的二进制文档（PDF、DOCX、XLSX、PPTX）
- 纯文本内容：直接保存为 Markdown 文档
自动解析并加入知识库编译索引队列。
"""

WIKI_QUERY_DESCRIPTION_EN = """Query the Wiki knowledge base.

Searches relevant wiki articles and returns grounded context with source citations.
Search here first when answering questions about project concepts, domain knowledge, team notes, or compiled research.
"""

WIKI_QUERY_DESCRIPTION_ZH = """检索 Wiki 知识库。

搜索相关 Wiki 概念词条与文档，返回带有来源引用的可信上下文。
在回答有关项目概念、领域知识、团队笔记或沉淀研究的问题时优先在此搜索。
"""

WIKI_APPLY_DESCRIPTION_EN = """Apply a narrow, structured mutation to a wiki concept page.

Protects managed sections (Compiled Truth, Timeline, claims frontmatter).
Do not use whole-page rewrites; pick the smallest op that fits:
- create_note: Create a new structured note (requires concept_name and body; optional tags/aliases/sources)
- patch_compiled_truth: Update the core facts section (requires concept_name and compiled_truth)
- append_timeline: Append a milestone bullet (requires concept_name and timeline_entry)
- update_metadata: Update frontmatter tags, aliases, or source citations (requires concept_name and tags/aliases/sources)
"""

WIKI_APPLY_DESCRIPTION_ZH = """对 Wiki 概念页面应用结构化更新。

保护受管区域（核心事实 Compiled Truth、时间线 Timeline、元数据 frontmatter）。
请勿全量重写整个页面，按需选择最轻量的操作：
- create_note: 创建新结构化笔记（需 concept_name 与 body；可选 tags/aliases/sources）
- patch_compiled_truth: 局部修正核心事实段落（需 concept_name 与 compiled_truth）
- append_timeline: 追加里程碑时间线条目（需 concept_name 与 timeline_entry）
- update_metadata: 更新标签、别名或引用来源（需 concept_name 与 tags/aliases/sources）
"""


def resolve_wiki_ingest_description(locale: str | None = None) -> str:
    """Resolve localized description for wiki_ingest_tool."""
    return WIKI_INGEST_DESCRIPTION_ZH if is_chinese(locale) else WIKI_INGEST_DESCRIPTION_EN


def resolve_wiki_query_description(locale: str | None = None) -> str:
    """Resolve localized description for wiki_query_tool."""
    return WIKI_QUERY_DESCRIPTION_ZH if is_chinese(locale) else WIKI_QUERY_DESCRIPTION_EN


def resolve_wiki_apply_description(locale: str | None = None) -> str:
    """Resolve localized description for wiki_apply_tool."""
    return WIKI_APPLY_DESCRIPTION_ZH if is_chinese(locale) else WIKI_APPLY_DESCRIPTION_EN


def create_wiki_tools(
    compiler: WikiCompiler,
    query_engine: WikiQueryEngine,
    linter: WikiLinter,
    structure: WikiStructure,
    *,
    wiki_scope_id: str | None = None,
    locale: str | None = None,
) -> list:
    """
    Create agent-facing wiki tools (ingest + query + apply).

    Compile/maintain are Settings/REST operations and are not exposed to the LLM.
    """
    return create_wiki_agent_tools(
        compiler,
        query_engine,
        structure,
        wiki_scope_id=wiki_scope_id,
        locale=locale,
    )


def create_wiki_agent_tools(
    compiler: WikiCompiler,
    query_engine: WikiQueryEngine,
    structure: WikiStructure,
    *,
    wiki_scope_id: str | None = None,
    locale: str | None = None,
) -> list:
    """Create LangChain tools exposed to the agent at Turn1."""

    @tool("wiki_ingest_tool", description=resolve_wiki_ingest_description(locale))
    async def wiki_ingest(
        source: Annotated[str, "URL or file path to ingest (supports Web URLs, local documents like PDF/Word/Excel/Markdown, or raw text)"],
        filename: Annotated[str, "Optional custom filename for the ingested document"] = "",
        folder_path: Annotated[
            str,
            "Optional logical folder path to categorize this document (e.g., 'Research/AI')",
        ] = "",
    ) -> str:
        logger.info(f"Ingesting: {source[:100]}")

        try:
            if source.startswith("http://") or source.startswith("https://"):
                content = await _fetch_url_as_markdown(source)
                resolved_filename = (
                    filename
                    or f"web_{hashlib.sha256(source.encode()).hexdigest()[:12]}.md"
                )
                resolved_filename = Path(resolved_filename).name
                if folder_path:
                    safe_folder = structure._sanitize_path(folder_path)
                    full_path = f"{safe_folder}/{resolved_filename}"
                else:
                    full_path = resolved_filename

                from myrm_agent_harness.toolkits.wiki.pipeline.ingress import (
                    UrlMarkdownIngressRequest,
                    publish_url_markdown_ingress,
                )

                chunks = _split_if_large(content, full_path)
                ingested_count = 0
                display_path = full_path

                for idx, (chunk_path, chunk_content) in enumerate(chunks):
                    ingress_result = await publish_url_markdown_ingress(
                        structure,
                        UrlMarkdownIngressRequest(
                            url=source,
                            filename=resolved_filename,
                            folder_path=folder_path,
                            relative_path=chunk_path if len(chunks) > 1 else "",
                            localize_public_assets=idx == 0,
                        ),
                        markdown=chunk_content,
                    )
                    if ingress_result.conflict:
                        return (
                            f"Raw source already exists with different content: "
                            f"{ingress_result.relative_path}. "
                            "Use Settings Wiki import to supersede or choose a different filename."
                        )
                    if ingress_result.security_blocked:
                        return (
                            f"Raw source rejected due to sensitive content: "
                            f"{ingress_result.relative_path}. "
                            "Remove credentials before ingesting."
                        )
                    if ingress_result.written:
                        compiler.enqueue_file(
                            structure.get_raw_file_path(ingress_result.relative_path)
                        )
                        ingested_count += 1
                        display_path = ingress_result.relative_path

                if ingested_count == 0:
                    return "Failed to ingest document: no content was written to raw/"

                logger.info(f"Ingested {ingested_count} chunk(s) for: {display_path}")
                suffix = f" ({ingested_count} chunks)" if ingested_count > 1 else ""
                return f"Successfully ingested document: {display_path}{suffix}. Compilation queued."
            elif len(source) < 260 and "\n" not in source and Path(source).exists():
                src_path = Path(source)
                from myrm_agent_harness.toolkits.file_parsers import is_supported

                if is_supported(str(src_path)):
                    content = await _parse_binary_document(str(src_path))
                else:
                    try:
                        content = src_path.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        content = src_path.read_text(encoding="utf-8", errors="replace")
                filename = filename or src_path.name
                if not filename.endswith(".md"):
                    filename = Path(filename).stem + ".md"
            else:
                content = source
                filename = (
                    filename
                    or f"text_{hashlib.sha256(source.encode()).hexdigest()[:12]}.md"
                )

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
            return "Failed to ingest document"

    @tool("wiki_query_tool", description=resolve_wiki_query_description(locale))
    async def wiki_query(
        question: Annotated[str, "Question to ask the wiki knowledge base (e.g. concept definitions, architecture patterns, team facts)"],
    ) -> dict | str:
        logger.info(f"Querying wiki: {question[:100]}")

        try:
            result = await query_engine.query(question)

            if (
                not result.source_snippets
                and not result.related_articles
                and result.confidence_score == 0.0
            ):
                return "No relevant information found in wiki. Consider ingesting more documents."

            from myrm_agent_harness.utils.context_format import (
                wrap_with_external_sources_tag,
            )

            evidence_context = format_evidence_cards_context(
                result.answer,
                result.source_snippets,
                structure=structure,
            )

            wrapped_context = wrap_with_external_sources_tag(
                evidence_context, source="LLM-Wiki"
            )

            sources = attach_wiki_scope_id(
                build_wiki_query_sources(result, structure=structure),
                wiki_scope_id,
            )

            # Archive only when high confidence and verified source snippets exist to prevent synthetic contamination
            if (
                result.should_archive
                and result.confidence_score >= 0.8
                and result.source_snippets
            ):
                try:
                    await _archive_query_result(
                        structure, compiler, question, result.answer
                    )
                except Exception as archive_err:
                    logger.warning(
                        f"Query archive failed (non-blocking): {archive_err}"
                    )

            return {"content": wrapped_context, "metadata": {"sources": sources}}

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return "Query failed"

    @tool("wiki_apply_tool", description=resolve_wiki_apply_description(locale))
    async def wiki_apply(
        op: Annotated[
            str,
            "Operation: 'create_note' (new note with body), 'patch_compiled_truth' (update core facts with compiled_truth), 'append_timeline' (add event with timeline_entry), or 'update_metadata' (tags/aliases)",
        ],
        concept_name: Annotated[str, "Concept path, e.g. 'research/react-hooks' or 'team/onboarding'"],
        compiled_truth: Annotated[str, "For patch_compiled_truth: New Compiled Truth section content"] = "",
        timeline_entry: Annotated[str, "For append_timeline: Milestone or event bullet to append"] = "",
        body: Annotated[str, "For create_note: Main note content"] = "",
        tags: Annotated[
            str, "Comma-separated tags for update_metadata or create_note (e.g. 'frontend,react')"
        ] = "",
        aliases: Annotated[
            str, "Comma-separated aliases for update_metadata or create_note (e.g. 'Hooks,React Hooks')"
        ] = "",
        sources: Annotated[
            str, "Comma-separated source references for update_metadata or create_note"
        ] = "",
        clear_confidence: Annotated[
            bool, "For update_metadata: Reset frontmatter confidence score"
        ] = False,
    ) -> str:
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
            provenance=WikiProvenance.AGENT,
        )
        indexer = WikiIndexer(structure)
        try:
            result = await apply_wiki_mutation(
                structure, indexer, request, caller="agent"
            )
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
            return "Compilation failed"

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
            return "Maintenance failed"

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


def _split_if_large(content: str, base_path: str) -> list[tuple[str, str]]:
    """Split large content into chunks for better wiki compilation.

    Returns list of (relative_path, content) tuples. For small documents,
    returns a single entry with the original path.
    """
    if len(content) <= _LARGE_DOC_CHUNK_THRESHOLD:
        return [(base_path, content)]

    from myrm_agent_harness.toolkits.retriever.splitter import TextChunker

    chunker = TextChunker(min_chunk_tokens=200)
    docs = chunker.chunk_text(
        content, document_metadata={"title": Path(base_path).stem}
    )

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
        logger.debug(
            "FetchEngine returned empty for %s, falling back to secure_get", url
        )
    except Exception:
        logger.debug("FetchEngine failed for %s, falling back to secure_get", url)

    from myrm_agent_harness.core.security.http.secure_fetch import secure_get
    from myrm_agent_harness.toolkits.web_fetch.markdown_generator import (
        MarkdownGenerator,
    )

    headers = {"User-Agent": "Myrm-Agent-Wiki/1.0 (knowledge-ingestion)"}
    response = await secure_get(url, timeout=30.0, headers=headers)
    if response.status_code != 200:
        raise ValueError(f"Failed to fetch {url}: HTTP {response.status_code}")

    generator = MarkdownGenerator()
    result = generator.generate_markdown(response.text, base_url=url, citations=False)
    return result.raw_markdown or f"# {url}\n\n(empty page)"
