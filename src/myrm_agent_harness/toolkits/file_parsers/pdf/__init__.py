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
  - pdf_heading: font-based heading detection for bookmark-less PDFs
  - pdf_heuristic_table: heuristic table extractor for borderless forms

[POS]
Framework generic file-parsing capability. PDF parsing is one coherent domain
with five modules sharing extraction primitives, so they stay co-located under
one facade.
"""

from myrm_agent_harness.toolkits.file_parsers.pdf.pdf import PDFPlumberParser
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_content_extractor import (
    PDFExtractConfig,
    PDFExtractResult,
    PDFImageContent,
    extract_pdf_content,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_heading import (
    DetectedHeading,
    FontHeadingConfig,
    detect_headings_by_font,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_heuristic_table import (
    extract_heuristic_tables_from_words,
)
from myrm_agent_harness.toolkits.file_parsers.pdf.pdf_smart import SmartPDFParser

__all__ = [
    "DetectedHeading",
    "FontHeadingConfig",
    "PDFExtractConfig",
    "PDFExtractResult",
    "PDFImageContent",
    "PDFPlumberParser",
    "SmartPDFParser",
    "detect_headings_by_font",
    "extract_heuristic_tables_from_words",
    "extract_pdf_content",
]
