# file_parsers/pdf/

## Overview
PDF parsing domain: pdfplumber text/table parser, smart extraction orchestrator (Text/Hybrid/Image + OCR fallback), SmartPDFParser adapter, bookmark/numbering/font heading pipeline, cross-page table stitching, and heuristic table extraction for borderless forms.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Aggregate facade re-exporting PDF parsing primitives | ✅ |
| pdf.py | Core | PDFPlumberParser orchestrator: page parsing (sequential/parallel), heading composition, cross-page stitching and text/table merging with physical max_pages slicing. Writes a `[Page N]` marker for every page (blank ones too, table placement relies on list position) and owns the page-coverage helpers: `count_content_chars` (length of page text without those marker lines), `pages_with_text` (which marked pages carry any text), and `pages_without_text` (marked pages whose body is empty). A page that failed OCR leaves no marker behind, so a caller holding the delivered page set subtracts `pages_with_text` from it instead of trusting the markers | ✅ |
| pdf_bookmarks.py | Core | Bookmark extraction + page-object-id resolution and the generic-exporter-title quality gate | ✅ |
| pdf_content_extractor.py | Core | Smart PDF extraction orchestrator (Text/Hybrid/Image strategy + OCR fallback) with physical page cutoff. Text vs. scanned is judged by `count_content_chars` against `min_text_chars` (page markers never count); text without real content is returned as `""`; a scan reports the OCR/render window (`ocr_pages`) as `parsed_pages`; text/table casts carry a page window (`max_pages`), while both image paths and the page window they may read are capped by `min(max_pages, ocr_pages)` so one prompt can never receive an unbounded pile of page images. Delivery shortfalls are disclosed through three distinct channels: a capped embedded-figure scan sets `image_trace["truncated"]`, a window-cut full-page scan reports fewer `parsed_pages`, and a page the text layer could not read (scanned/blank inside the delivered window) is listed in `pages_without_text` with its 1-based number. Every rendered page image carries `PDFImageContent.page_number` so a consumer can name the real source page | ✅ |
| pdf_cross_page.py | Core | Precision-first cross-page table stitching (repeated header / column signature + cut-row evidence) | ✅ |
| pdf_font_heading.py | Core | Font-based heading detection for bookmark-less PDFs | ✅ |
| pdf_heading_pipeline.py | Core | Heading fusion (numbering + font), running-title repeat filter wiring, and in-place heading placement | ✅ |
| pdf_heuristic_table.py | Core | Heuristic table extractor for borderless forms | ✅ |
| pdf_numbering.py | Core | Clause-numbering detection (第X章/节/条, 一、, （一）, 1.1.1, ①) with precision guards and document-level level mapping | ✅ |
| pdf_smart.py | Core | SmartPDFParser adapter registered as default PDF parser | ✅ |
| pdf_tables.py | Core | Table extraction (line + heuristic), column anchors, and Markdown/L0 rendering after stitching | ✅ |

## Module Dependencies

- `pdfplumber`
- `pydantic`
