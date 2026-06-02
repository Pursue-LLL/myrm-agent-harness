# local_file_search/

## Overview
Semantic search over user's local files. Provides SHA256 incremental indexing,
multi-format file parsing, vector embedding, and hybrid retrieval with optional
reranking. Requires explicit user authorization — no background scanning.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Toolkit entry point, re-exports public API | — |
| models.py | Core | Data models: IndexedDirectory, FileRecord, IndexStats, SearchHit, SearchResponse | ✅ |
| config.py | Config | Configuration: directories, exclusions, supported extensions, constants | ✅ |
| indexer.py | Core | Indexing engine: scan → parse → chunk → embed → store (SHA256 incremental) | ✅ |
| search.py | Core | Search engine: query → embed → vector search → optional rerank → results | ✅ |
| local_file_search_agent_tools.py | Core | LangChain tool wrappers: search_local_files_tool, get_local_file_index_status_tool | ✅ |

## Architecture

```
User (Frontend GUI) → Configure directories (explicit authorization)
                     ↓
Server (Business Layer) → Trigger indexing via LocalFileIndexer
                         ↓
LocalFileIndexer:
  1. Scan directories (exclude patterns, size limits)
  2. SHA256 hash check (skip unchanged files)
  3. Parse content (file_parsers toolkit)
  4. Chunk text (retriever.splitter)
  5. Embed chunks (retriever.embedding)
  6. Store in vector DB (vector toolkit, collection: "local_file_search")
                         ↓
Agent uses search_local_files_tool tool → LocalFileSearchEngine
  1. Embed query
  2. Vector similarity search
  3. Optional reranking (reranker)
  4. Return scored results with file paths and snippets
```

## Key Dependencies

- `file_parsers` (PDF, DOCX, XLSX, PPTX, text parsing)
- `retriever` (embedding, text chunking, reranker)
- `vector` (Qdrant vector store)

## Design Principles

- **Explicit authorization**: Deny-by-default. User must configure directories in frontend.
- **Incremental indexing**: SHA256 content hash — only re-index changed files.
- **Lazy indexing**: No background watcher. Index on startup + manual trigger + on directory change.
- **Circuit breaker**: 5 consecutive embedding failures abort indexing (avoids wasting time when API is down).
- **Reuse**: Leverages existing retriever, file_parsers, and vector toolkits.
- **Framework purity**: Zero business logic. Configuration, persistence (FileRecord recovery), and API endpoints are in the server layer.
