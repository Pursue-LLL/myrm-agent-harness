# file_parsers/

## Overview
File parsers toolkit. Aggregates parsers for PDF, Word, Excel, PowerPoint, text,
Jupyter Notebook, images (OCR), and legacy OLE2 formats (.doc/.xls/.ppt via soffice
auto-conversion).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | File parsers toolkit entry point. Aggregates parsers, LegacyFormatParser (OLE2 magic detection + soffice conversion for .doc/.xls/.ppt), and factory functions. | ✅ |
| base.py | Core | File parser base classes and data structures | ✅ |
| docx.py | Core | Word document parser. Supports markdown (headings, lists, tables with merged-cell dedup, document order) and structure mode (JSON metadata with paragraph IDs, styles, table cell map with row/col coordinates for incremental edits and form filling). | ✅ |
| excel.py | Core | Excel file parser. Supports markdown/text (content), structure (JSON metadata for token-efficient overview), audit (formula error detection). Dynamic data_only based on mode. | ✅ |
| image_filter.py | Core | Smart image ablation filter. Intercepts UI noise, decorative lines, tiny logos, | ✅ |
| ocr.py | Core | OCR parser for images using PaddleOCR. Supports CJK languages natively. | ✅ |
| pdf.py | Core | PDF parser based on pdfplumber. Implements text layout preservation, Markdown table | ✅ |
| pdf_heading.py | Core | Font-based heading detection for PDFs without bookmarks. Uses statistical font size analysis. | ✅ |
| pdf_content_extractor.py | Core | Smart PDF extraction orchestrator. Auto-selects Text/Hybrid(embedded image)/Image(full-page | ✅ |
| pdf_heuristic_table.py | Core | Heuristic table extractor for borderless forms: spatial clustering, dynamic line-height gap merging, CJK-aware same-row and cross-row cell concatenation. | ✅ |
| pptx.py | Core | PowerPoint document parser. Supports markdown (slide text, tables, speaker notes) and structure mode (JSON metadata with shape IDs, types, positions, layouts for incremental edits). | ✅ |
| text.py | Core | Text file parser | ✅ |
| ipynb.py | Core | Jupyter Notebook parser. Extracts Markdown/code/raw cells, strips metadata/outputs. | ✅ |

## Dependencies

- **Core**: `pdfplumber`（含 pypdfium2 传递依赖；`pdf.py`, `pdf_content_extractor.py`, `file_read_tool`）
- **Optional `[file-parsers]`**: `python-docx`, `openpyxl`, `python-pptx`
- **Stdlib**: `json`（`ipynb.py`，无额外依赖）
