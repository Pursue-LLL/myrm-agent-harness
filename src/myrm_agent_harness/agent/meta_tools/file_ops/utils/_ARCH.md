# utils/

## Overview
Utility functions module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Utility functions module. | — |
| document_reader.py | Core | Document file reader for file_read_tool. Converts .docx/.doc/.xlsx/.xls/.pptx/.ppt/.ipynb to Markdown via file_parsers with multimodal plot blocks and magic bytes sniffing. | ✅ |
| file_utils.py | Core | Provides parse_path_with_range with positive line numbers and ordered range validation. | ✅ |
| image_reader.py | Core | Provides is_image_path, read_image_as_content_blocks. Quality Ladder compression (95->20) + (original/attached/scale) coordinate scale factor disclosure. | ✅ |
| line_endings.py | Core | Line ending detection and normalization (CRLF/LF preserved across edits) plus UTF-8 BOM stripping on display. | ✅ |
| vault_scope.py | Core | Obsidian vault root detection via `.obsidian/` marker | ✅ |
| office_scope.py | Core | Office `.docx`/`.xlsx` extension scope for write guards | ✅ |
| office_opc.py | Core | OPC metrics + xlsx formula snapshots + corrupt Office file audit read errors for bash post-audit | ✅ |
| office_recalc.py | Core | Optional LibreOffice recalc + Excel error cell scan after xlsx edits | ✅ |
| video_reader.py | Core | Sandbox video reads for file_read_tool; video-slot-first fallback chain + VideoAnalysisEngine. | ✅ |
| path_utils.py | Core | Provides resolve_file_id_path. | ✅ |
| vault_read.py | Core | vault:// URI read, workspace resolve, batch read for file_read_tool | ✅ |
| pdf_reader.py | Core | PDF file reader with structure outline extraction and Large Document Smart RAG Diverter: within the auto-index page limit the whole document is re-read text-only and ingested, empty documents are not ingested, and past the limit the hint reports the delivered pages only. Delivery mirrors the sibling readers: a vision model gets page image blocks, a text-only model with an auxiliary vision chain gets the same pages as text descriptions (real source page numbers from `PDFImageContent.page_number`), and a text layer that could not read some pages is disclosed through a `[PDF coverage]` prefix. A windowed read always carries a `[Partial Read]` hint naming the delivered page count, whether or not a knowledge base can absorb the rest | ✅ |

## Tests

- `tests/agent/meta_tools/file_ops/utils/test_office_opc.py`
- `tests/agent/meta_tools/file_ops/utils/test_office_recalc.py`

## Key Dependencies

- `toolkits`
