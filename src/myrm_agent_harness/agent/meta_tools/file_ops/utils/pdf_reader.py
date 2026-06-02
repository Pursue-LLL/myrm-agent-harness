"""PDF file reader for file_read_tool

Uses pdf_content_extractor for unified smart extraction:
- Text-first via pdfplumber (with table extraction)
- Image fallback via pypdfium2 when text is sparse
- Returns LangChain content blocks for multimodal models, plain text otherwise

[INPUT]
- toolkits.file_parsers.pdf_content_extractor::PDFExtractConfig (POS: Smart PDF extraction orchestrator. Auto-selects Text/Hybrid(embedded image)/Image(full-page render fallback) strategy. Supports Table Encapsulation to prevent RAG chunking from splitting tables, using L0 summaries to ensure retrieval accuracy.)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)

[OUTPUT]
- is_pdf_path: Detect if path is a PDF file
- read_pdf_as_content_blocks: Read PDF and return smart-extracted content.

[POS]
PDF file reader for file_read_tool
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from langchain_core.messages.content import ContentBlock, create_image_block, create_text_block

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)

PDF_EXTENSIONS: frozenset[str] = frozenset({".pdf"})

_FALLBACK_MAX_CHARS = 100_000


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


async def read_pdf_as_content_blocks(
    path: str, executor: CodeExecutor, supports_vision: bool
) -> str | list[ContentBlock]:
    """Read PDF and return smart-extracted content."""
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
            result = await extract_pdf_content(tmp_path, PDFExtractConfig())
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

    if len(text) > _FALLBACK_MAX_CHARS:
        text = text[:_FALLBACK_MAX_CHARS] + f"\n\n... [truncated at {_FALLBACK_MAX_CHARS} chars]"

    if supports_vision and result.images:
        blocks: list[ContentBlock] = []
        if text.strip():
            blocks.append(create_text_block(f"[PDF: {path}]\n{text}"))
        for img in result.images:
            blocks.append(create_image_block(base64=img.data, mime_type=img.mime_type))
        return blocks

    if text.strip():
        return f"[PDF: {path}]\n{text}"

    return f"[PDF file: {path}] (No extractable text — may be image-only)"
