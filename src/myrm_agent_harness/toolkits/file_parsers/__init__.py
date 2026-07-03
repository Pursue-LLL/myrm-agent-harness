"""File parsers toolkit.

Provides parsers for various file formats:
- PDF (pdfplumber, core dep): Text + table extraction with Markdown output
- Word (python-docx, `[file-parsers]`): DOCX files with headings, lists, and tables (merged-cell dedup) in document order
- Excel (openpyxl, `[file-parsers]`): XLSX files with merged cells support
- PowerPoint (python-pptx, `[file-parsers]`): PPTX files with slide text, tables, and notes
- PDF page render fallback (pypdfium2 via pdfplumber transitive dependency)
- Text: Plain text and Markdown files
- Jupyter Notebook (stdlib json): IPYNB cell extraction (Markdown/code/raw)


[INPUT]
- base::FileParser, PDFParseResult, PDFTable (POS: parser abstract base and PDF result models)
- docx::DocxParser (POS: Word document parser)
- excel::ExcelParser (POS: Excel file parser)
- pptx::PptxParser (POS: PowerPoint document parser)
- pdf::PDFPlumberParser (POS: PDF parser using pdfplumber)
- pdf_content_extractor::PDFExtractConfig, PDFExtractResult, PDFImageContent, extract_pdf_content (POS: PDF content extraction)
- text::TextParser (POS: plain text and Markdown parser)
- ipynb::IpynbParser (POS: Jupyter Notebook parser)

[OUTPUT]
- FileParser, PDFPlumberParser, DocxParser, ExcelParser, PptxParser, TextParser, IpynbParser: parser classes
- PDFParseResult, PDFTable: PDF-specific result models
- PDFExtractConfig, PDFExtractResult, PDFImageContent, extract_pdf_content: PDF extraction utilities
- parse_file(): auto-detect file type and parse

[POS]
File parsers toolkit entry point. Aggregates all file format parsers and provides
a unified parse_file() function for auto-detection.
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.file_parsers.base import (
    FileParser,
    PDFParseResult,
    PDFTable,
)
from myrm_agent_harness.toolkits.file_parsers.docx import DocxParser
from myrm_agent_harness.toolkits.file_parsers.excel import ExcelParser
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
    ".doc": DocxParser(),
    ".xlsx": ExcelParser(),
    ".xls": ExcelParser(),
    ".pptx": PptxParser(),
    ".ppt": PptxParser(),
    ".ipynb": IpynbParser(),
    # Image files via OCR (PaddleOCR, optional dependency)
    ".png": _OCR_PARSER,
    ".jpg": _OCR_PARSER,
    ".jpeg": _OCR_PARSER,
    ".tiff": _OCR_PARSER,
    ".tif": _OCR_PARSER,
    ".bmp": _OCR_PARSER,
    ".webp": _OCR_PARSER,
}


# ====================== Factory Functions ======================


def get_parser(file_path: str) -> FileParser:
    """Get parser for file based on file extension

    Args:
        file_path: File path

    Returns:
        Corresponding file parser

    Raises:
        ValueError: Unsupported file type
    """
    ext = Path(file_path).suffix.lower()
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
    """Check if file type is supported"""
    ext = Path(file_path).suffix.lower()
    return ext in _PARSERS
