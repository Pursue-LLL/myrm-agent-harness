# splitter/

## Overview

Document chunking for RAG: code-aware splits, markdown headers, special blocks, and overlap handling.

Detailed design: [RETRIEVER_SYSTEM.md](../RETRIEVER_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public splitter exports | — |
| `chunk_processor.py` | Core | Chunk processing utilities | ✅ |
| `code_utils.py` | Core | Code language detection and large-block splitting | ✅ |
| `markdown_link_handler.py` | Core | Markdown link handling during split | ✅ |
| `overlap_processor.py` | Core | Chunk overlap processing | ✅ |
| `recursive_character_protect_special_splitter.py` | Core | Recursive character splitter with special-block protection | ✅ |
| `smart_markdown_header_text_splitter.py` | Core | Markdown header-aware text splitter | ✅ |
| `special_block_detector.py` | Core | Detects code/table/list blocks needing special handling | ✅ |
| `special_block_splitter.py` | Core | Splits oversized special blocks | ✅ |
| `splitter.py` | Core | High-level splitter strategy selector | ✅ |

## Key Dependencies

- `utils`
