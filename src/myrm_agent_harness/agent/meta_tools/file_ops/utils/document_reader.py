"""Document file reader for file_read_tool

Reads structured documents (.docx, .doc, .xlsx, .xls, .pptx, .ppt, .ipynb) via Harness
file_parsers, returning AI-friendly Markdown text and extracted multimodal blocks.
Legacy OLE2 formats (.doc/.xls/.ppt) are auto-converted via LegacyFormatParser (soffice headless).

[INPUT]
- toolkits.file_parsers::DocxParser (POS: Word document parser)
- toolkits.file_parsers::ExcelParser (POS: Excel file parser)
- toolkits.file_parsers::PptxParser (POS: PowerPoint document parser)
- toolkits.file_parsers::IpynbParser (POS: Jupyter Notebook parser)
- toolkits.file_parsers::LegacyFormatParser (POS: OLE2 legacy format parser with soffice conversion)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)

[OUTPUT]
- is_document_path: Detect if path is a structured document file
- read_document_as_text: Read document and return parsed Markdown text
- read_document_multimodal: Read document and return text + extracted image content blocks

[POS]
Document file reader for file_read_tool. Converts .docx/.doc/.xlsx/.xls/.pptx/.ppt/.ipynb
to Markdown via existing file_parsers with multimodal block emission for Notebook plots.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import tempfile
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from langchain_core.messages.content import ContentBlock, create_image_block, create_text_block

from myrm_agent_harness.utils.mime_types import detect_image_mime

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)

DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".ipynb"})

_FALLBACK_MAX_CHARS = 200_000
_EXCEL_STRUCTURE_THRESHOLD_BYTES = 50 * 1024


def is_document_path(path: str) -> bool:
    """Detect if path is a structured document file (.docx/.doc/.xlsx/.xls/.pptx/.ppt/.ipynb)"""
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


async def read_document_multimodal(
    path: str,
    executor: CodeExecutor,
    *,
    supports_vision: bool = True,
    parse_mode: str | None = None,
) -> list[ContentBlock]:
    """Read a structured document and return content blocks (text + extracted images).

    For .ipynb files with plots, emits visual image blocks alongside structured text.
    For Office files (.docx/.xlsx/.pptx), emits parsed structured text blocks.
    """
    suffix = PurePosixPath(path).suffix.lower()

    try:
        raw_bytes = await executor.read_file_bytes(path)
    except FileNotFoundError:
        raise
    except Exception as e:
        logger.warning("Failed to read document bytes: %s, error: %s", path, e)
        return [create_text_block(f"[Document: {path}] (Failed to read)")]

    # Magic bytes check: if file is actually an image without extension or misnamed
    sniffed_mime = detect_image_mime(raw_bytes, fallback="")
    if sniffed_mime and suffix not in DOCUMENT_EXTENSIONS:
        from .image_reader import read_image_as_content_blocks

        res = await read_image_as_content_blocks(path, executor, supports_vision)
        if isinstance(res, list):
            return res
        return [create_text_block(res)]

    tmp_path: str | None = None
    try:
        tmp_path = await _write_to_temp(raw_bytes, suffix)

        if suffix == ".ipynb":
            from myrm_agent_harness.toolkits.file_parsers.ipynb import IpynbParser

            parser = IpynbParser()
            parsed_res = await parser.parse_with_images(tmp_path)
            blocks: list[ContentBlock] = []

            text = parsed_res.text
            if not text.strip():
                text = f"[Document: {path}] (No extractable content)"
            elif len(text) > _FALLBACK_MAX_CHARS:
                text = text[:_FALLBACK_MAX_CHARS] + f"\n\n... [truncated at {_FALLBACK_MAX_CHARS} chars]"

            blocks.append(create_text_block(f"[Document: {path}]\n{text}"))

            if supports_vision and parsed_res.images:
                for img in parsed_res.images:
                    blocks.append(
                        create_text_block(
                            f"[Notebook Plot: cell {img.cell_index}, output {img.output_index}] ({img.mime_type})"
                        )
                    )
                    blocks.append(create_image_block(base64=img.base64_data, mime_type=img.mime_type))

            return blocks

        elif suffix in (".docx", ".doc"):
            from myrm_agent_harness.toolkits.file_parsers.docx import DocxParser

            docx_delegate = DocxParser(output_format="structure") if parse_mode == "structure" else DocxParser()
            if suffix == ".doc":
                from myrm_agent_harness.toolkits.file_parsers import LegacyFormatParser

                parser = LegacyFormatParser(".docx", docx_delegate)
            else:
                parser = docx_delegate
        elif suffix in (".xlsx", ".xls"):
            from myrm_agent_harness.toolkits.file_parsers.excel import ExcelParser

            effective_mode = parse_mode
            if effective_mode is None and len(raw_bytes) > _EXCEL_STRUCTURE_THRESHOLD_BYTES:
                effective_mode = "structure"

            if effective_mode in ("structure", "audit"):
                excel_delegate = ExcelParser(output_format=effective_mode)
            else:
                excel_delegate = ExcelParser()

            if suffix == ".xls":
                from myrm_agent_harness.toolkits.file_parsers import LegacyFormatParser

                parser = LegacyFormatParser(".xlsx", excel_delegate)
            else:
                parser = excel_delegate
        elif suffix in (".pptx", ".ppt"):
            from myrm_agent_harness.toolkits.file_parsers.pptx import PptxParser

            pptx_delegate = PptxParser(output_format="structure") if parse_mode == "structure" else PptxParser()
            if suffix == ".ppt":
                from myrm_agent_harness.toolkits.file_parsers import LegacyFormatParser

                parser = LegacyFormatParser(".pptx", pptx_delegate)
            else:
                parser = pptx_delegate
        else:
            return [create_text_block(f"[Document: {path}] (Unsupported document format: {suffix})")]

        text = await parser.parse(tmp_path)

    except ImportError as e:
        logger.warning("Document parser dependency not available for %s: %s", path, e)
        return [create_text_block(f"[Document: {path}] (Parser dependency not installed)")]
    except Exception as e:
        logger.warning("Document parsing failed for %s: %s", path, e)
        return [create_text_block(f"[Document: {path}] (Parsing failed)")]
    finally:
        if tmp_path:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    if not text.strip():
        return [create_text_block(f"[Document: {path}] (No extractable content)")]

    if len(text) > _FALLBACK_MAX_CHARS:
        text = text[:_FALLBACK_MAX_CHARS] + f"\n\n... [truncated at {_FALLBACK_MAX_CHARS} chars]"

    return [create_text_block(f"[Document: {path}]\n{text}")]


async def read_document_as_text(
    path: str,
    executor: CodeExecutor,
    *,
    parse_mode: str | None = None,
) -> str:
    """Read a structured document and return parsed text."""
    blocks = await read_document_multimodal(path, executor, supports_vision=False, parse_mode=parse_mode)
    text_blocks: list[str] = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text":
            text_blocks.append(str(b.get("text", "")))
        elif hasattr(b, "text"):
            text_blocks.append(str(getattr(b, "text", "")))
    return "\n\n".join(text_blocks) if text_blocks else f"[Document: {path}] (No extractable content)"
