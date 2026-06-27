"""PDF file reader for file_read_tool

Uses pdf_content_extractor for unified smart extraction:
- Text-first via pdfplumber (with table extraction)
- Image fallback via pypdfium2 when text is sparse
- Returns LangChain content blocks for multimodal models, plain text otherwise
- Large documents (>RAG_PAGE_THRESHOLD pages) are auto-ingested into wiki
  knowledge base for RAG retrieval instead of being silently truncated

[INPUT]
- toolkits.file_parsers.pdf_content_extractor::PDFExtractConfig (POS: Smart PDF extraction orchestrator. Auto-selects Text/Hybrid(embedded image)/Image(full-page render fallback) strategy. Supports Table Encapsulation to prevent RAG chunking from splitting tables, using L0 summaries to ensure retrieval accuracy.)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)

[OUTPUT]
- is_pdf_path: Detect if path is a PDF file
- read_pdf_as_content_blocks: Read PDF and return smart-extracted content.
- register_large_doc_ingest_callback / unregister_large_doc_ingest_callback:
  Module-level callback registry for wiki auto-ingest on large PDFs.

[POS]
PDF file reader for file_read_tool. Implements Large Document Smart RAG Diverter:
when a PDF exceeds RAG_PAGE_THRESHOLD pages, the full text is asynchronously
ingested into the wiki knowledge base (via registered callback), and the agent
receives a structured hint to use wiki_query for precise retrieval instead of
reading the entire document into context.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
from collections.abc import Callable, Coroutine
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from langchain_core.messages.content import ContentBlock, create_image_block, create_text_block

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)

PDF_EXTENSIONS: frozenset[str] = frozenset({".pdf"})

_FALLBACK_MAX_CHARS = 100_000

RAG_PAGE_THRESHOLD = 20
RAG_MAX_PAGES_LIMIT = 2000

LargeDocIngestCallback = Callable[[str, str, str], Coroutine[Any, Any, None]]

_ingest_callback: LargeDocIngestCallback | None = None


def register_large_doc_ingest_callback(cb: LargeDocIngestCallback) -> None:
    """Register the wiki ingest callback for large document auto-indexing.

    The callback signature: async def cb(filename: str, full_text: str, doc_hash: str) -> None
    """
    global _ingest_callback
    _ingest_callback = cb


def unregister_large_doc_ingest_callback() -> None:
    """Unregister the wiki ingest callback."""
    global _ingest_callback
    _ingest_callback = None


def is_pdf_path(path: str) -> bool:
    """Detect if path is a PDF file"""
    suffix = PurePosixPath(path).suffix.lower()
    return suffix in PDF_EXTENSIONS


async def _write_to_temp(raw_bytes: bytes) -> str:
    """Write PDF bytes to a temp file and return the temp path.

    Needed because pdf_content_extractor requires a filesystem path.
    """

    def _write() -> str:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(raw_bytes)
            tmp.flush()
            return tmp.name

    return await asyncio.to_thread(_write)


async def _fire_and_forget_ingest(filename: str, full_text: str, doc_hash: str) -> None:
    """Trigger background wiki ingest without blocking the caller."""
    cb = _ingest_callback
    if cb is None:
        return
    try:
        await cb(filename, full_text, doc_hash)
    except Exception:
        logger.warning("Background wiki ingest failed for %s (non-blocking)", filename, exc_info=True)


async def _schedule_rag_ingest(
    path: str,
    raw_bytes: bytes,
    result: "PDFExtractResult",  # noqa: F821
    cfg_cls: type,
    extract_fn: "Callable[..., Coroutine[Any, Any, Any]]",
) -> None:
    """Extract full text (if truncated) and schedule background wiki ingest.

    Runs entirely in background via create_task — any exception is caught
    and logged to avoid unhandled task exceptions.
    """
    try:
        if result.page_count > RAG_MAX_PAGES_LIMIT:
            logger.warning(
                "PDF %s has %d pages (>%d), skipping RAG ingest",
                path, result.page_count, RAG_MAX_PAGES_LIMIT,
            )
            return

        doc_hash = hashlib.sha256(raw_bytes[:8192]).hexdigest()[:16]
        filename = PurePosixPath(path).name
        full_text = result.text

        default_max = cfg_cls().max_pages
        if result.page_count > default_max:
            try:
                tmp = await _write_to_temp(raw_bytes)
                try:
                    full_result = await extract_fn(tmp, cfg_cls(max_pages=RAG_MAX_PAGES_LIMIT))
                finally:
                    os.unlink(tmp)
                full_text = full_result.text
            except Exception:
                logger.warning("Full PDF re-extraction failed for %s, using truncated text", path)

        await _fire_and_forget_ingest(filename, full_text, doc_hash)
    except Exception:
        logger.warning("RAG ingest scheduling failed for %s (non-blocking)", path, exc_info=True)


async def read_pdf_as_content_blocks(
    path: str, executor: CodeExecutor, supports_vision: bool
) -> str | list[ContentBlock]:
    """Read PDF and return smart-extracted content.

    For documents exceeding RAG_PAGE_THRESHOLD pages, the full text is
    asynchronously ingested into the wiki knowledge base and the agent
    receives a hint to use wiki_query for precise retrieval.
    """
    try:
        raw_bytes = await executor.read_file_bytes(path)
    except FileNotFoundError:
        raise
    except Exception as e:
        logger.warning("Failed to read PDF bytes: %s, error: %s", path, e)
        return f"[PDF file: {path}] (Failed to read: {e})"

    try:
        from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
            PDFExtractConfig,
            extract_pdf_content,
        )

        tmp_path = await _write_to_temp(raw_bytes)
        try:
            result = await extract_pdf_content(
                tmp_path, PDFExtractConfig(max_pages=RAG_PAGE_THRESHOLD)
            )
        finally:
            os.unlink(tmp_path)

    except (ImportError, TypeError):
        logger.warning("pdf_content_extractor not available for: %s", path)
        return f"[PDF file: {path}] (PDF extraction module not available)"
    except Exception as e:
        logger.warning("PDF extraction failed for %s: %s", path, e)
        return f"[PDF file: {path}] (Extraction failed: {e})"

    text = result.text
    if not text.strip() and not result.images:
        return f"[PDF file: {path}] (No extractable content — may be encrypted)"

    is_large_doc = result.page_count > RAG_PAGE_THRESHOLD
    rag_triggered = is_large_doc and _ingest_callback is not None

    if rag_triggered:
        asyncio.create_task(
            _schedule_rag_ingest(path, raw_bytes, result, PDFExtractConfig, extract_pdf_content)
        )

    if len(text) > _FALLBACK_MAX_CHARS:
        text = text[:_FALLBACK_MAX_CHARS] + f"\n\n... [truncated at {_FALLBACK_MAX_CHARS} chars]"

    rag_hint = ""
    if rag_triggered:
        rag_hint = (
            f"\n\n[RAG Auto-Index] This document has {result.page_count} pages. "
            f"Only the first {RAG_PAGE_THRESHOLD} pages are shown above. "
            f"The full document has been auto-indexed into the knowledge base. "
            f"Use the `wiki_query` tool to search for specific content from any page."
        )

    if supports_vision and result.images:
        blocks: list[ContentBlock] = []
        if text.strip():
            blocks.append(create_text_block(f"[PDF: {path}]\n{text}{rag_hint}"))
        for img in result.images:
            blocks.append(create_image_block(base64=img.data, mime_type=img.mime_type))
        return blocks

    if text.strip():
        return f"[PDF: {path}]\n{text}{rag_hint}"

    return f"[PDF file: {path}] (No extractable text — may be image-only)"
