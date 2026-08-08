"""File parsers toolkit.

Provides parsers for various file formats:
- PDF (pdfplumber, core dep): Text + table extraction with Markdown output
- Word (python-docx, `[file-parsers]`): DOCX files with headings, lists, and tables (merged-cell dedup) in document order
- Excel (openpyxl, `[file-parsers]`): XLSX files with merged cells support
- PowerPoint (python-pptx, `[file-parsers]`): PPTX files with slide text, tables, and notes
- PDF page render fallback (pypdfium2 via pdfplumber transitive dependency)
- Text: Plain text and Markdown files
- Jupyter Notebook (stdlib json): IPYNB cell extraction (Markdown/code/raw)
- Legacy formats (.doc/.xls/.ppt): OLE2 detection with soffice auto-conversion


[INPUT]
- base::FileParser, PDFParseResult, PDFTable (POS: parser abstract base and PDF result models)
- docx::DocxParser (POS: Word document parser)
- excel::ExcelParser (POS: Excel file parser)
- pptx::PptxParser (POS: PowerPoint document parser)
- pdf::PDFPlumberParser (POS: PDF parser using pdfplumber)
- pdf_content_extractor::PDFExtractConfig, PDFExtractResult, PDFImageContent, extract_pdf_content (POS: PDF content extraction)
- text::TextParser (POS: plain text and Markdown parser)
- ipynb::IpynbParser (POS: Jupyter Notebook parser)
- legacy::LegacyFormatParser (POS: OLE2 legacy format parser with soffice conversion)

[OUTPUT]
- FileParser, PDFPlumberParser, DocxParser, ExcelParser, PptxParser, TextParser, IpynbParser: parser classes
- LegacyFormatParser: OLE2 legacy format parser with soffice auto-conversion
- PDFParseResult, PDFTable: PDF-specific result models
- PDFExtractConfig, PDFExtractResult, PDFImageContent, extract_pdf_content: PDF extraction utilities
- parse_file(): auto-detect file type and parse

[POS]
File parsers toolkit entry point. Aggregates all file format parsers and provides
a unified parse_file() function for auto-detection.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.file_parsers.base import (
    FileParser,
    PDFParseResult,
    PDFTable,
)
from myrm_agent_harness.toolkits.file_parsers.container_xml_parser import (
    EpubParser,
    OdfParser,
)
from myrm_agent_harness.toolkits.file_parsers.content_format_sniff import (
    sniff_content_format,
)
from myrm_agent_harness.toolkits.file_parsers.csv_parser import CsvParser
from myrm_agent_harness.toolkits.file_parsers.docx import DocxParser
from myrm_agent_harness.toolkits.file_parsers.excel import ExcelParser
from myrm_agent_harness.toolkits.file_parsers.rtf_parser import RtfParser
from myrm_agent_harness.toolkits.file_parsers.ipynb import IpynbParser
from myrm_agent_harness.toolkits.file_parsers.ocr import OCRLine, OCRParser, OCRResult
from myrm_agent_harness.toolkits.file_parsers.pdf import PDFPlumberParser
from myrm_agent_harness.toolkits.file_parsers.pdf_content_extractor import (
    PDFExtractConfig,
    PDFExtractResult,
    PDFImageContent,
    extract_pdf_content,
)
from myrm_agent_harness.toolkits.file_parsers.pptx import PptxParser
from myrm_agent_harness.toolkits.file_parsers.text import TextParser

__all__ = [
    "DocxParser",
    "ExcelParser",
    "FileParser",
    "IpynbParser",
    "LegacyFormatParser",
    "OCRLine",
    "OCRParser",
    "OCRResult",
    "PDFExtractConfig",
    "PDFExtractResult",
    "PDFImageContent",
    "PDFParseResult",
    "PDFPlumberParser",
    "PDFTable",
    "PptxParser",
    "TextParser",
    "extract_pdf_content",
    "get_file_type",
    "get_parser",
    "get_pdf_parser",
    "is_supported",
]


# ====================== Legacy Format Support ======================

_logger = logging.getLogger(__name__)

# OLE2 Compound Binary File magic bytes (shared by .doc, .xls, .ppt)
_OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

_LEGACY_TO_MODERN: dict[str, str] = {
    ".doc": ".docx",
    ".xls": ".xlsx",
    ".ppt": ".pptx",
}


class LegacyFormatParser(FileParser):
    """Parser for legacy Office formats (.doc/.xls/.ppt) via soffice conversion.

    python-docx/openpyxl/python-pptx only support the modern Open XML formats.
    Legacy OLE2 files (pre-2007) must be converted first.  This parser detects
    the OLE2 magic number and converts via ``soffice --headless`` before
    delegating to the corresponding modern parser.
    """

    def __init__(self, target_ext: str, delegate: FileParser) -> None:
        self._target_ext = target_ext
        self._delegate = delegate

    async def parse(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if self._is_ole2(path):
            converted = await self._convert_with_soffice(path)
            if converted is None:
                raise RuntimeError(
                    f"Cannot parse legacy {path.suffix} file: soffice is not available. "
                    f"Please convert to {self._target_ext} first, or install LibreOffice."
                )
            try:
                return await self._delegate.parse(str(converted))
            finally:
                shutil.rmtree(converted.parent, ignore_errors=True)

        return await self._delegate.parse(file_path)

    def _is_ole2(self, path: Path) -> bool:
        """Check whether the file starts with OLE2 magic bytes."""
        try:
            with path.open("rb") as f:
                header = f.read(8)
            return header == _OLE2_MAGIC
        except OSError:
            return False

    async def _convert_with_soffice(self, path: Path) -> Path | None:
        """Convert OLE2 file to modern format using soffice headless."""
        soffice = shutil.which("soffice")
        if soffice is None:
            return None

        tmpdir = Path(tempfile.mkdtemp(prefix="legacy_convert_"))
        fmt_map = {".docx": "docx", ".xlsx": "xlsx", ".pptx": "pptx"}
        out_fmt = fmt_map.get(self._target_ext, "docx")

        try:
            proc = await asyncio.create_subprocess_exec(
                soffice,
                "--headless",
                "--convert-to",
                out_fmt,
                "--outdir",
                str(tmpdir),
                str(path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode != 0:
                _logger.warning(
                    "soffice exited with code %d for %s: %s",
                    proc.returncode,
                    path.name,
                    stderr.decode(errors="replace")[:500],
                )
                shutil.rmtree(tmpdir, ignore_errors=True)
                return None
        except (asyncio.TimeoutError, OSError) as exc:
            _logger.warning("soffice conversion failed for %s: %s", path.name, exc)
            shutil.rmtree(tmpdir, ignore_errors=True)
            return None

        converted_files = list(tmpdir.glob(f"*{self._target_ext}"))
        if not converted_files:
            _logger.warning("soffice produced no output for %s", path.name)
            shutil.rmtree(tmpdir, ignore_errors=True)
            return None

        return converted_files[0]

    @property
    def supported_extensions(self) -> list[str]:
        src_ext = next(
            (k for k, v in _LEGACY_TO_MODERN.items() if v == self._target_ext), ""
        )
        return [src_ext] if src_ext else []


# ====================== Parser Registry ======================

_DEFAULT_PDF_PARSER = PDFPlumberParser(
    extract_tables=True,
    parallel=False,
)

_FAST_PDF_PARSER = PDFPlumberParser(
    extract_tables=False,
    parallel=True,
    max_workers=4,
)

_OCR_PARSER = OCRParser()

_PARSERS: dict[str, FileParser] = {
    ".txt": TextParser(),
    ".md": TextParser(),
    ".markdown": TextParser(),
    ".rst": TextParser(),
    ".text": TextParser(),
    ".pdf": _DEFAULT_PDF_PARSER,
    ".docx": DocxParser(),
    ".doc": LegacyFormatParser(".docx", DocxParser()),
    ".xlsx": ExcelParser(),
    ".xls": LegacyFormatParser(".xlsx", ExcelParser()),
    ".pptx": PptxParser(),
    ".ppt": LegacyFormatParser(".pptx", PptxParser()),
    ".ipynb": IpynbParser(),
    # Image files via OCR (PaddleOCR, optional dependency)
    ".png": _OCR_PARSER,
    ".jpg": _OCR_PARSER,
    ".jpeg": _OCR_PARSER,
    ".tiff": _OCR_PARSER,
    ".tif": _OCR_PARSER,
    ".bmp": _OCR_PARSER,
    ".webp": _OCR_PARSER,
    ".csv": CsvParser(),
    ".rtf": RtfParser(),
    ".epub": EpubParser(),
    ".odt": OdfParser(".odt"),
    ".ods": OdfParser(".ods"),
    ".odp": OdfParser(".odp"),
}


# ====================== Factory Functions ======================


def _resolve_parser_extension(file_path: str) -> str:
    path = Path(file_path)
    declared = path.suffix.lower()
    sniffed = sniff_content_format(path)
    if sniffed is None:
        return declared
    if declared not in _PARSERS:
        return sniffed
    if sniffed != declared:
        return sniffed
    return declared


def get_parser(file_path: str) -> FileParser:
    """Get parser for file based on extension with content sniff fallback."""
    ext = _resolve_parser_extension(file_path)
    parser = _PARSERS.get(ext)

    if parser is None:
        supported = ", ".join(_PARSERS.keys())
        raise ValueError(f"Unsupported file type: {ext}. Supported: {supported}")

    return parser


def get_pdf_parser(
    mode: str = "default",
    extract_tables: bool = True,
    parallel: bool = False,
) -> PDFPlumberParser:
    """Get PDF parser with custom configuration

    Args:
        mode: Preset mode ("default", "fast", "table")
        extract_tables: Whether to extract tables
        parallel: Whether to use parallel processing

    Returns:
        Configured PDF parser
    """
    if mode == "fast":
        return _FAST_PDF_PARSER
    if mode == "table":
        return PDFPlumberParser(extract_tables=True, parallel=False)
    return PDFPlumberParser(extract_tables=extract_tables, parallel=parallel)


def get_file_type(file_path: str) -> str:
    """Get file type (extension without dot)"""
    return Path(file_path).suffix.lower().lstrip(".")


def is_supported(file_path: str) -> bool:
    """Check if file type is supported (extension or content sniff)."""
    path = Path(file_path)
    declared = path.suffix.lower()
    if declared in _PARSERS:
        return True
    return sniff_content_format(path) in _PARSERS
