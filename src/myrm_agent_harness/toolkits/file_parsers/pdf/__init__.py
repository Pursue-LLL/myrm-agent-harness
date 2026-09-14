"""PDF parsing domain: pdfplumber text/table parser, smart extraction, headings, heuristic tables.

[INPUT]
- PDF files (any encoding / layout), including scanned PDFs (sparse text layer).
- Table extraction config + OCR language for the scanned-PDF fallback.

[OUTPUT]
- Aggregate facade re-exporting every public name of the ``pdf`` subpackage:
  - pdf: PDFPlumberParser (text layout preservation + Markdown tables)
  - pdf_content_extractor: Smart PDF extraction orchestrator
    (Text / Hybrid / Image strategy + OCR fallback)
  - pdf_smart: SmartPDFParser adapter (registered as the default ``get_parser(".pdf")``)
  - pdf_bookmarks: bookmark extraction and generic-title quality gate
  - pdf_font_heading: font-based heading detection for bookmark-less PDFs
  - pdf_numbering: clause-numbering detection with precision guards
  - pdf_heading_pipeline: heading fusion and in-place placement
  - pdf_cross_page: cross-page table stitching
  - pdf_heuristic_table: heuristic table extractor for borderless forms

[POS]
Framework generic file-parsing capability. PDF parsing is one coherent domain
with per-source modules sharing extraction primitives, so they stay co-located
under one facade.
"""

from myrm_agent_harness.toolkits.file_parsers.pdf.pdf import PDFPlumberParser
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_bookmarks import (
    bookmarks_are_degenerate,
    extract_bookmarks,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_content_extractor import (
    PDFExtractConfig,
    PDFExtractResult,
    PDFImageContent,
    extract_pdf_content,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_cross_page import (
    stitch_cross_page_tables,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_font_heading import (
    DetectedHeading,
    FontHeadingConfig,
    detect_headings_by_font,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_heading_pipeline import (
    build_numbering_cues,
    fuse_headings,
    insert_headings_into_page_text,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_heuristic_table import (
    extract_heuristic_tables_from_words,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_numbering import (
    NumberingHeading,
    NumberingHeadingConfig,
    detect_numbering_headings,
    filter_repeated_titles,
    normalize_heading_title,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_smart import SmartPDFParser

__all__ = [
    "DetectedHeading",
    "FontHeadingConfig",
    "NumberingHeading",
    "NumberingHeadingConfig",
    "PDFExtractConfig",
    "PDFExtractResult",
    "PDFImageContent",
    "PDFPlumberParser",
    "SmartPDFParser",
    "bookmarks_are_degenerate",
    "build_numbering_cues",
    "detect_headings_by_font",
    "detect_numbering_headings",
    "extract_bookmarks",
    "extract_heuristic_tables_from_words",
    "extract_pdf_content",
    "filter_repeated_titles",
    "fuse_headings",
    "insert_headings_into_page_text",
    "normalize_heading_title",
    "stitch_cross_page_tables",
]
