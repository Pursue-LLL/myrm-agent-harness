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
| pdf_heuristic_table.py | Core | Heuristic table extractor for borderless forms: spatial clustering, dynamic line-height gap merging, CJK-aware same-row and cross-row cell concatenation. | ✅ |
| pptx.py | Core | PowerPoint document parser (slide text, tables, speaker notes) | ✅ |
| text.py | Core | Text file parser | ✅ |
| ipynb.py | Core | Jupyter Notebook parser. Extracts Markdown/code/raw cells, strips metadata/outputs. | ✅ |

## Dependencies

- **Core**: `pdfplumber`（`pyproject.toml` 主依赖；`pdf.py`, `pdf_content_extractor.py`）
- **Optional `[file-parsers]`**: `pypdfium2`, `python-docx`, `openpyxl`, `python-pptx`
- **Stdlib**: `json`（`ipynb.py`，无额外依赖）
