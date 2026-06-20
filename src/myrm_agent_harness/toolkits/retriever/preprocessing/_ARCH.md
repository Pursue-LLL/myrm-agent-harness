# preprocessing/

## Overview

Document preprocessing for the retrieval pipeline: chunk filtering and normalization before embedding and index build.

Detailed design: [RETRIEVER_SYSTEM.md](../RETRIEVER_SYSTEM.md)

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for chunk filtering helpers | — |
| `chunk_filter.py` | Core | Document chunk filter and crawl-result chunk builder | ✅ |

## Key Dependencies

- `utils`
