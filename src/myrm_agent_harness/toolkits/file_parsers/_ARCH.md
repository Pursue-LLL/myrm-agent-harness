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
| content_format_sniff.py | Core | Content sniffing: detect file format from bytes (magic bytes) independent of extension | ✅ |
| container_xml_parser.py | Core | Generic OPC/container XML parser for legacy office formats | ✅ |
| csv_parser.py | Core | CSV file parser with delimiter detection and Markdown output | ✅ |
| docx.py | Core | Word document parser. Supports markdown (headings, lists, tables with merged-cell dedup, document order, embedded image refs) and structure mode (JSON metadata with paragraph IDs, styles, table cell map with row/col coordinates for incremental edits and form filling). | ✅ |
| docx_embedded_assets.py | Core | DOCX OOXML relationship-id → image bytes extractor and markdown ref localizer into wiki assets | ✅ |
| excel.py | Core | Excel file parser. Supports markdown/text (content), structure (JSON metadata for token-efficient overview), audit (formula error detection). Dynamic data_only based on mode. | ✅ |
| gfm_normalize.py | Core | Normalize parser output into consistent GitHub Flavored Markdown | ✅ |
| image_filter.py | Core | Smart image ablation filter. Intercepts UI noise, decorative lines, tiny logos, | ✅ |
| ocr.py | Core | OCR parser for images using PaddleOCR (2.x/3.x engine compatible, PaddleX unified API in 3.x). Supports CJK languages natively. | ✅ |
| pdf/（子包） | Core | PDF 解析子域：pdfplumber 文本/表格解析、智能提取编排（Text/Hybrid/Image + OCR 兜底）、SmartPDFParser 适配器、字体级标题检测、无边框表格启发式提取。5 个 `pdf*` 模块聚合于此，`pdf/__init__.py` 为聚合门面统一 re-export | ✅ |
| pptx.py | Core | PowerPoint document parser. Supports markdown (slide text, tables, speaker notes) and structure mode (JSON metadata with shape IDs, types, positions, layouts for incremental edits). | ✅ |
| rtf_parser.py | Core | RTF parser with font/color group handling and Markdown output | ✅ |
| text.py | Core | Text file parser | ✅ |
| ipynb.py | Core | Jupyter Notebook parser. Extracts Markdown/code/raw cells, outputs plots (multimodal blocks), preserves cell tags, and applies 10K/100-line safe truncation. | ✅ |

## Dependencies

- **Core**: `pdfplumber`（含 pypdfium2 传递依赖；`pdf/pdf.py`, `pdf/pdf_content_extractor.py`, `file_read_tool`）
- **Optional `[file-parsers]`**: `python-docx`, `openpyxl`, `python-pptx`
- **Optional `[pdf-ocr]`**: `paddleocr` + `paddlepaddle`（`ocr.py` 扫描 PDF OCR 兜底，经 `pdf/pdf_smart.py`/`extract_pdf_content` 接入；缺失时自动降级，返回文本层/页面图）
- **Stdlib**: `json`（`ipynb.py`，无额外依赖）
