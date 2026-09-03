# file_parsers/pdf/

## Overview
PDF parsing domain: pdfplumber text/table parser, smart extraction orchestrator (Text/Hybrid/Image + OCR fallback), SmartPDFParser adapter, font-based heading detection, and heuristic table extraction for borderless forms.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Aggregate facade re-exporting PDF parsing primitives | ✅ |
| pdf.py | Core | PDFPlumberParser text layout preservation + Markdown tables with physical max_pages slicing | ✅ |
| pdf_content_extractor.py | Core | Smart PDF extraction orchestrator (Text/Hybrid/Image strategy + OCR fallback) with physical page cutoff | ✅ |
| pdf_heading.py | Core | Font-based heading detection for bookmark-less PDFs | ✅ |
| pdf_heuristic_table.py | Core | Heuristic table extractor for borderless forms | ✅ |
| pdf_smart.py | Core | SmartPDFParser adapter registered as default PDF parser | ✅ |

## Module Dependencies

- `pdfplumber`
- `pydantic`
