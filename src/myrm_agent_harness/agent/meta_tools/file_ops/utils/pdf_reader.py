"""PDF file reader for file_read_tool

Uses pdf_content_extractor for unified smart extraction:
- Text-first via pdfplumber (with table extraction)
- Image fallback via pypdfium2 when text is sparse
- Returns LangChain content blocks for multimodal models, plain text otherwise
- Large documents (>RAG_PAGE_THRESHOLD pages, up to RAG_MAX_PAGES_LIMIT) are read in
  full and auto-ingested into the wiki knowledge base for RAG retrieval, instead of
  being silently truncated

[INPUT]
- toolkits.file_parsers.pdf.pdf_content_extractor::PDFExtractConfig (POS: Smart PDF extraction orchestrator. Auto-selects Text/Hybrid(embedded image)/Image(full-page render fallback) strategy; scanned PDFs (sparse text) get best-effort OCR fallback via RapidOCR so text-only consumers still get readable text. Supports Table Encapsulation to prevent RAG chunking from splitting tables, using L0 summaries to ensure retrieval accuracy.)
- toolkits.llms.vision.fallback_engine::create_vision_fallback_engine (POS: Auxiliary vision chain builder; describes delivered page images as text for text-only models.)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)

[OUTPUT]
- is_pdf_path: Detect if path is a PDF file
- read_pdf_as_content_blocks: Read PDF and return smart-extracted content (supports parse_mode="structure" for structural heading outlines).
- register_large_doc_ingest_callback / unregister_large_doc_ingest_callback:
  Module-level callback registry for wiki auto-ingest on large PDFs.

[POS]
PDF file reader for file_read_tool. Delivery mirrors the sibling readers: a
vision-capable model receives the page images as blocks, a text-only model with a
vision fallback configured receives them as text descriptions, and only when no
vision route exists does it degrade to plain text. Implements Large Document Smart
RAG Diverter: a PDF exceeding RAG_PAGE_THRESHOLD pages but still within
RAG_MAX_PAGES_LIMIT is read in full and asynchronously ingested into the wiki
knowledge base (via registered callback); the agent receives a hint to use
wiki_query for precise retrieval instead of reading the whole document into context.
Documents past RAG_MAX_PAGES_LIMIT are neither ingested nor advertised as ingested:
the hint only reports the pages that were actually delivered.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import tempfile
from collections.abc import Callable, Coroutine
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from langchain_core.messages.content import ContentBlock, create_image_block, create_text_block

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor
    from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_content_extractor import (
        PDFExtractConfig,
        PDFExtractResult,
    )

logger = logging.getLogger(__name__)

PDF_EXTENSIONS: frozenset[str] = frozenset({".pdf"})

_FALLBACK_MAX_CHARS = 100_000

RAG_PAGE_THRESHOLD = 20
RAG_MAX_PAGES_LIMIT = 2000

# Bounds the structure outline injected into context for very long documents.
STRUCTURE_OUTLINE_MAX_ENTRIES = 200

LargeDocIngestCallback = Callable[[str, str, str], Coroutine[object, object, None]]

_ingest_callback: LargeDocIngestCallback | None = None

# Holds references to fire-and-forget RAG ingest tasks so the event loop
# does not garbage-collect them mid-flight.
_pending_ingest_tasks: set[asyncio.Task[None]] = set()


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
    result: PDFExtractResult,
    cfg_cls: type[PDFExtractConfig],
    extract_fn: Callable[[str, PDFExtractConfig], Coroutine[object, object, PDFExtractResult]],
) -> None:
    """Re-read the whole document when the first pass was partial, then ingest it.

    Its caller reads at most ``RAG_PAGE_THRESHOLD`` pages for context; everything the
    wiki should know has to come from this pass, so the trigger is the delivered
    coverage (``parsed_pages``), never a page-count guess. The re-read is text-only
    because these page images were deliberately kept out of the model's context and
    must not be rendered just to be thrown away.

    Runs entirely in background via create_task — any exception is caught
    and logged to avoid unhandled task exceptions.
    """
    try:
        if result.page_count > RAG_MAX_PAGES_LIMIT:
            logger.warning(
                "PDF %s has %d pages (>%d), skipping RAG ingest",
                path,
                result.page_count,
                RAG_MAX_PAGES_LIMIT,
            )
            return

        doc_hash = hashlib.sha256(raw_bytes[:8192]).hexdigest()[:16]
        filename = PurePosixPath(path).name
        full_text = result.text

        if result.parsed_pages < result.page_count:
            try:
                tmp = await _write_to_temp(raw_bytes)
                try:
                    full_result = await extract_fn(
                        tmp, cfg_cls(max_pages=RAG_MAX_PAGES_LIMIT, extract_embedded_images=False)
                    )
                finally:
                    os.unlink(tmp)
                full_text = full_result.text
            except Exception:
                logger.warning("Full PDF re-extraction failed for %s, using the delivered text", path)

        if not full_text.strip():
            logger.info("PDF %s delivered no text, skipping RAG ingest", path)
            return

        await _fire_and_forget_ingest(filename, full_text, doc_hash)
    except Exception:
        logger.warning("RAG ingest scheduling failed for %s (non-blocking)", path, exc_info=True)


async def read_pdf_as_content_blocks(
    path: str,
    executor: CodeExecutor,
    supports_vision: bool,
    *,
    vision_fallback_model_cfg: object | None = None,
    vision_fallback_model_cfgs: object | None = None,
    parse_mode: str | None = None,
) -> str | list[ContentBlock]:
    """Read PDF and return smart-extracted content or structural outline.

    A vision-capable model receives the delivered page images as content blocks. A
    text-only model with an auxiliary vision chain configured receives the same pages
    as text descriptions, so scanned pages are never dropped silently just because the
    primary model cannot see images.

    When parse_mode='structure', extracts the document bookmarks and chapter
    hierarchy without full text extraction or OCR, enabling progressive disclosure.
    For documents exceeding RAG_PAGE_THRESHOLD pages in normal mode, the full text is
    asynchronously ingested into the wiki knowledge base and the agent
    receives a hint to use wiki_query for precise retrieval.
    """
    try:
        raw_bytes = await executor.read_file_bytes(path)
    except FileNotFoundError:
        raise
    except Exception as e:
        logger.warning("Failed to read PDF bytes: %s, error: %s", path, e)
        return f"[PDF file: {path}] (Failed to read)"

    if parse_mode == "structure":
        tmp_path = await _write_to_temp(raw_bytes)
        try:
            from myrm_agent_harness.toolkits.file_parsers.pdf.pdf import PDFPlumberParser

            parser = PDFPlumberParser(extract_tables=False)
            res = await asyncio.to_thread(parser.parse_sync, tmp_path)
            headings = res.headings
            page_count = res.metadata.get("page_count", 0)

            outline_lines = [f"[DOCUMENT STRUCTURE OUTLINE: {PurePosixPath(path).name} (Total Pages: {page_count})]:"]
            if headings:
                for heading in headings[:STRUCTURE_OUTLINE_MAX_ENTRIES]:
                    indent = "  " * heading.level
                    outline_lines.append(f"{indent}- Page {heading.page_num}: {heading.title}")
                omitted = len(headings) - STRUCTURE_OUTLINE_MAX_ENTRIES
                if omitted > 0:
                    outline_lines.append(f"  … ({omitted} more headings omitted; use wiki_query for full detail)")
            else:
                outline_lines.append("  (No structural headings detected in PDF)")

            return "\n".join(outline_lines)
        except Exception as e:
            logger.warning("PDF structure outline extraction failed for %s: %s", path, e)
            return f"[PDF file: {path}] (Failed to extract structure outline: {e})"
        finally:
            import contextlib

            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    try:
        from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_content_extractor import (
            PDFExtractConfig,
            extract_pdf_content,
        )

        tmp_path = await _write_to_temp(raw_bytes)
        try:
            result = await extract_pdf_content(tmp_path, PDFExtractConfig(max_pages=RAG_PAGE_THRESHOLD))
        finally:
            os.unlink(tmp_path)

    except (ImportError, TypeError):
        logger.warning("pdf_content_extractor not available for: %s", path)
        return f"[PDF file: {path}] (PDF extraction module not available)"
    except Exception as e:
        logger.warning("PDF extraction failed for %s: %s", path, e)
        return f"[PDF file: {path}] (Extraction failed)"

    text = result.text
    if not text.strip() and not result.images:
        return f"[PDF file: {path}] (No extractable content — may be encrypted)"

    is_large_doc = result.page_count > RAG_PAGE_THRESHOLD
    wiki_wired = _ingest_callback is not None
    rag_triggered = is_large_doc and wiki_wired and result.page_count <= RAG_MAX_PAGES_LIMIT

    if rag_triggered:
        task = asyncio.create_task(_schedule_rag_ingest(path, raw_bytes, result, PDFExtractConfig, extract_pdf_content))
        _pending_ingest_tasks.add(task)
        task.add_done_callback(_pending_ingest_tasks.discard)

    if len(text) > _FALLBACK_MAX_CHARS:
        text = text[:_FALLBACK_MAX_CHARS] + f"\n\n... [truncated at {_FALLBACK_MAX_CHARS} chars]"

    rag_hint = ""
    if rag_triggered:
        opened_pages = min(result.parsed_pages, RAG_PAGE_THRESHOLD)
        # Pages outside this window were never inspected here, so their readability is
        # unknown at this point; and any page without a text layer is indexed as an empty
        # entry. Promising "any page" would send the model after content the knowledge base
        # never received, so the caveat is unconditional rather than derived from the window.
        rag_hint = (
            f"\n\n[RAG Auto-Index] This document has {result.page_count} pages. "
            f"Only the first {opened_pages} pages are shown above. "
            f"The full document ({result.page_count} pages) has been auto-indexed into the knowledge base. "
            f"Use the `wiki_query` tool to search content beyond these pages; "
            f"pages that are scanned images carry no searchable text."
        )
    elif is_large_doc and wiki_wired:
        rag_hint = (
            f"\n\n[Partial Read] This document has {result.page_count} pages, "
            f"beyond the {RAG_MAX_PAGES_LIMIT}-page auto-index limit. "
            f"Only the first {min(result.parsed_pages, RAG_PAGE_THRESHOLD)} pages are shown above "
            f"and the rest was not indexed. Use the `file_read` `parse_mode='structure'` outline "
            f"to locate a section before reading it."
        )
    elif is_large_doc:
        # No knowledge base to divert to, so the read really is windowed. Without this the
        # model would treat the first RAG_PAGE_THRESHOLD pages as the whole document.
        rag_hint = (
            f"\n\n[Partial Read] This document has {result.page_count} pages; "
            f"only the first {min(result.parsed_pages, RAG_PAGE_THRESHOLD)} pages were read. "
            f"Use the `file_read` `parse_mode='structure'` outline to locate a section, "
            f"then read it."
        )

    coverage_note = _build_coverage_note(result)

    if supports_vision and result.images:
        blocks: list[ContentBlock] = []
        if text.strip() or coverage_note:
            blocks.append(create_text_block(f"[PDF: {path}]\n{coverage_note}{text}{rag_hint}"))
        for img in result.images:
            blocks.append(create_image_block(base64=img.data, mime_type=img.mime_type))
        return blocks

    if result.images and (vision_fallback_model_cfg is not None or vision_fallback_model_cfgs is not None):
        described = await _describe_pdf_pages(
            executor, result, path, vision_fallback_model_cfg, vision_fallback_model_cfgs
        )
        if described:
            blocks = []
            if text.strip() or coverage_note:
                blocks.append(create_text_block(f"[PDF: {path}]\n{coverage_note}{text}{rag_hint}"))
            blocks.append(create_text_block(described))
            return blocks

    if text.strip() or coverage_note:
        return f"[PDF: {path}]\n{coverage_note}{text}{rag_hint}"

    return f"[PDF file: {path}] (No extractable text — may be image-only)"


def _format_page_ranges(pages: list[int]) -> str:
    """Compact ``1-3, 7`` form for a page list, so the note stays cheap in context.

    Sorts and de-duplicates rather than trusting the caller: page numbers arrive from set
    arithmetic and from the extractor, and an unsorted list would render as ``5, 1``.
    """
    ordered = sorted(set(pages))
    if not ordered:
        return ""
    ranges: list[str] = []
    start = prev = ordered[0]
    for page in ordered[1:]:
        if page == prev + 1:
            prev = page
            continue
        ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
        start = prev = page
    ranges.append(f"{start}-{prev}" if start != prev else f"{start}")
    return ", ".join(ranges)


def _build_coverage_note(result: PDFExtractResult) -> str:
    """Prefix that states which pages the delivered text cannot cover, or ``""``.

    The text layer returns nothing for a scanned page, so without this the model would
    read a partial document and answer as if it had seen all of it. Rendered next to the
    page count it tells the model which pages to treat as unread, and that a vision route
    is what could read them.
    """
    missing = result.pages_without_text
    if not missing:
        return ""

    shown = missing if len(missing) <= 12 else missing[:12]
    listing = _format_page_ranges(shown)
    if len(missing) > len(shown):
        listing += f", … ({len(missing)} pages total)"
    # Count against what was delivered, not the whole document: on a windowed read the
    # denominators differ, and quoting the total would imply the unread pages are a small
    # share of material the model never received either way.
    delivered = result.parsed_pages or result.page_count

    # Only promise the page images that this delivery actually carries. Past the image
    # ceiling some of these pages have no image either, and their content is simply absent.
    carried = {img.page_number for img in result.images if img.page_number > 0}
    with_image = [page for page in missing if page in carried]
    without_image = [page for page in missing if page not in carried]
    if without_image and len(without_image) < len(missing):
        availability = (
            f"Content of pages {_format_page_ranges(with_image)} is only available as page images; "
            f"pages {_format_page_ranges(without_image)} were not delivered at all."
        )
    elif without_image:
        availability = "Those pages were not delivered, so their content is unavailable."
    else:
        availability = "Their content is only available as page images."

    if len(missing) >= delivered:
        # Nothing readable in the delivered window, so "the text below omits them" would
        # describe text that is not there. Say what is actually true instead.
        return (
            f"[PDF coverage] none of the {delivered} delivered pages have a text layer "
            f"(scanned images or blank pages). {availability}\n\n"
        )
    return (
        f"[PDF coverage] {len(missing)} of the {delivered} delivered pages have no text layer "
        f"(scanned images or blank pages): pages {listing}. "
        f"The text below omits those pages; {availability}\n\n"
    )


async def _describe_pdf_pages(
    executor: CodeExecutor,
    result: PDFExtractResult,
    path: str,
    vision_fallback_model_cfg: object | None,
    vision_fallback_model_cfgs: object | None,
) -> str:
    """Describe delivered page images via the auxiliary vision chain.

    Mirrors the sibling image/video readers: the page images were already rendered for
    this delivery, so converting them here keeps a text-only model from losing every
    scanned page. Returns ``""`` when the chain is unconfigured or every page fails, so
    the caller falls back to plain text instead of crashing the read.
    """
    from myrm_agent_harness.toolkits.llms.vision.fallback_engine import (
        create_vision_fallback_engine,
    )

    engine = create_vision_fallback_engine(vision_fallback_model_cfg, vision_fallback_model_cfgs)
    if engine is None:
        return ""

    descriptions: list[str] = []
    for index, img in enumerate(result.images, start=1):
        try:
            page_text = await engine.describe_image_b64(img.data, img.mime_type)
        except Exception as exc:
            logger.warning("Vision fallback failed for PDF %s page %d: %s", path, index, exc)
            continue
        if page_text.strip():
            # Prefer the real source page so the model can cite the document correctly.
            label = img.page_number if img.page_number > 0 else index
            descriptions.append(f"[Page {label}]\n{page_text}")

    if not descriptions:
        return ""
    return f"[PDF page analysis for {path}]\n" + "\n\n".join(descriptions)
