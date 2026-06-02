# splitter/

## Overview
textsplittoolmodule

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | textsplittoolmodule | — |
| chunk_processor.py | Core | Chunk processing utilities. | ✅ |
| code_utils.py | Core | Provides detect_code_language, split_large_code_block, protect_code_blocks. | ✅ |
| markdown_link_handler.py | Core | Markdown link handler module. | ✅ |
| overlap_processor.py | Core | Overlap processing module. | ✅ |
| recursive_character_protect_special_splitter.py | Core | Unified recursive character splitter | ✅ |
| smart_markdown_header_text_splitter.py | Core | Markdown-aware splitter. Splits documents along header boundaries while enforcing a | ✅ |
| special_block_detector.py | Core | Provides SpecialBlockDetector, hello. | ✅ |
| special_block_splitter.py | Core | Special-block splitter. Handles oversized code / table / list blocks that exceed the normal | ✅ |
| splitter.py | Core | High-level text splitter. Selects the appropriate splitting strategy based on content type | ✅ |

## Key Dependencies

- `utils`
