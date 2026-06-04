# file_parsers/

## Overview
File parsers toolkit entry point. Aggregates all file format parsers and provides

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | File parsers toolkit entry point. Aggregates all file format parsers and provides | ✅ |
| base.py | Core | File parser base classes and data structures | ✅ |
| docx.py | Core | Word document parser | ✅ |
| excel.py | Core | Excel file parser | ✅ |
| image_filter.py | Core | Smart image ablation filter. Intercepts UI noise, decorative lines, tiny logos, | ✅ |
| ocr.py | Core | OCR parser for images using PaddleOCR. Supports CJK languages natively. | ✅ |
| pdf.py | Core | PDF parser based on pdfplumber. Implements text layout preservation, Markdown table | ✅ |
| pdf_heading.py | Core | Font-based heading detection for PDFs without bookmarks. Uses statistical font size analysis. | ✅ |
| pdf_content_extractor.py | Core | Smart PDF extraction orchestrator. Auto-selects Text/Hybrid(embedded image)/Image(full-page | ✅ |
| pdf_heuristic_table.py | Core | Heuristic table extractor based on spatial coordinate clustering for borderless forms. | ✅ |
| pptx.py | Core | PowerPoint document parser (slide text, tables, speaker notes) | ✅ |
| text.py | Core | Text file parser | ✅ |
