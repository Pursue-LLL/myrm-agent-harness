"""Document file reader for file_read_tool

Reads structured documents (.docx, .xlsx, .xls, .pptx, .ppt, .ipynb) via Harness
file_parsers, returning AI-friendly Markdown text.

[INPUT]
- toolkits.file_parsers::DocxParser (POS: Word document parser)
- toolkits.file_parsers::ExcelParser (POS: Excel file parser)
- toolkits.file_parsers::PptxParser (POS: PowerPoint document parser)
- toolkits.file_parsers::IpynbParser (POS: Jupyter Notebook parser)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)

[OUTPUT]
- is_document_path: Detect if path is a structured document file
- read_document_as_text: Read document and return parsed Markdown text

[POS]
Document file reader for file_read_tool. Converts .docx/.xlsx/.xls/.pptx/.ppt/.ipynb
to Markdown via existing file_parsers.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import tempfile
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)

DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({".docx", ".xlsx", ".xls", ".pptx", ".ppt", ".ipynb"})

_FALLBACK_MAX_CHARS = 200_000


def is_document_path(path: str) -> bool:
    """Detect if path is a structured document file (.docx/.xlsx/.xls/.pptx/.ppt/.ipynb)"""
    suffix = PurePosixPath(path).suffix.lower()
    return suffix in DOCUMENT_EXTENSIONS


async def _write_to_temp(raw_bytes: bytes, suffix: str) -> str:
    """Write bytes to a temp file and return the temp path."""

    def _write() -> str:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw_bytes)
            tmp.flush()
            return tmp.name

    return await asyncio.to_thread(_write)


async def read_document_as_text(path: str, executor: CodeExecutor) -> str:
    """Read a structured document and return parsed Markdown text.

    Uses DocxParser for .docx, ExcelParser for .xlsx/.xls, PptxParser for .pptx/.ppt,
    IpynbParser for .ipynb. Falls back to a descriptive error message on failure.
    """
    suffix = PurePosixPath(path).suffix.lower()

    try:
        raw_bytes = await executor.read_file_bytes(path)
    except FileNotFoundError:
        raise
    except Exception as e:
        logger.warning("Failed to read document bytes: %s, error: %s", path, e)
        return f"[Document: {path}] (Failed to read: {e})"

    tmp_path: str | None = None
    try:
        tmp_path = await _write_to_temp(raw_bytes, suffix)

        if suffix == ".ipynb":
            from myrm_agent_harness.toolkits.file_parsers.ipynb import IpynbParser

            parser = IpynbParser()
        elif suffix == ".docx":
            from myrm_agent_harness.toolkits.file_parsers.docx import DocxParser

            parser = DocxParser()
        elif suffix in (".xlsx", ".xls"):
            from myrm_agent_harness.toolkits.file_parsers.excel import ExcelParser

            parser = ExcelParser()
        elif suffix in (".pptx", ".ppt"):
            from myrm_agent_harness.toolkits.file_parsers.pptx import PptxParser

            parser = PptxParser()
        else:
            return f"[Document: {path}] (Unsupported document format: {suffix})"

        text = await parser.parse(tmp_path)

    except ImportError as e:
        logger.warning("Document parser dependency not available for %s: %s", path, e)
        return f"[Document: {path}] (Parser dependency not installed: {e})"
    except Exception as e:
        logger.warning("Document parsing failed for %s: %s", path, e)
        return f"[Document: {path}] (Parsing failed: {e})"
    finally:
        if tmp_path:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    if not text.strip():
        return f"[Document: {path}] (No extractable content)"

    if len(text) > _FALLBACK_MAX_CHARS:
        text = text[:_FALLBACK_MAX_CHARS] + f"\n\n... [truncated at {_FALLBACK_MAX_CHARS} chars]"

    return f"[Document: {path}]\n{text}"
