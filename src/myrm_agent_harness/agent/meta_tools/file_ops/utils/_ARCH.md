# utils/

## Overview
Utility functions module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Utility functions module. | — |
| document_reader.py | Core | Document file reader for file_read_tool. Converts .docx/.xlsx/.xls to Markdown via file_parsers. | ✅ |
| file_utils.py | Core | Provides parse_path_with_range. | ✅ |
| image_reader.py | Core | Provides is_image_path, read_image_as_content_blocks. | ✅ |
| line_endings.py | Core | Line ending detection and normalization. Preserves CRLF/LF across agent edits. | ✅ |
| video_reader.py | Core | Provides is_video_path, read_video_as_content_blocks. | ✅ |
| path_utils.py | Core | Provides resolve_file_id_path. | ✅ |
| pdf_reader.py | Core | PDF file reader with Large Document Smart RAG Diverter. Auto-ingests large PDFs (>20 pages) into wiki knowledge base for RAG retrieval. | ✅ |

## Key Dependencies

- `toolkits`
