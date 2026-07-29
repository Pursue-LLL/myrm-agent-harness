# web_corpus/

## Overview

Persistent cross-session web page index. Every `web_search` and `web_fetch`
result is automatically stored in a local SQLite FTS5 index (tier 1: metadata)
with full-text content on the file system (tier 2: on-demand loading). Users
query via `memory_search_tool(corpus='web')` — no new LLM tool is introduced.

## Architecture

| Layer | What | Why |
|-------|------|-----|
| **Tier 1 — Index** | SQLite FTS5: URL, title, snippet, date, agent_id | Lightweight, fast text search |
| **Tier 2 — Content** | File system: `{data_dir}/web_corpus_content/{hash[:2]}/{hash}.txt` | Full text loaded on demand only |
| **Aging** | LRU eviction by `last_accessed` + disk quota | Prevents unbounded growth |

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| types.py | Types | WebCorpusEntry, CorpusStats data models | ✅ |
| store.py | Core | WebCorpusStore — FTS5 two-tier index with UPSERT, search, content retrieval, stale/LRU listing | ✅ |
| aging.py | Core | CorpusAgingPolicy + run_aging — time-based and disk-based eviction | ✅ |
| __init__.py | Package | Re-exports | — |
| _ARCH.md | Doc | This file | — |

## Integration points

- **Ingestion**: Server layer injects ContextVar callback after `web_fetch` / `web_search` execution.
  Toolkits must NOT import `agent/`. Uses the same ContextVar injection pattern as `spill.py`.
- **Query**: Extends `MemorySearchCorpus` with `'web'`; `MemorySearchBackends.query_web_corpus`
  callback bound by server at session start.
- **Settings**: Server Settings UI toggle for enable/disable, disk usage display, clear button.

## Key design decisions

1. **No new LLM tool** — reuses `memory_search_tool(corpus='web')` to avoid prompt token increase.
2. **Zero LLM cost** — pure FTS5 indexing, no embedding/LLM processing at ingest time.
3. **URL dedup** — reuses `url_normalizer.py` with UPSERT semantics on normalized URL.
4. **WAL mode** — concurrent-safe SQLite access (framework principle #3.4).
5. **Compliant with toolkits/ boundary** — no `agent/` imports, no `server/` imports.
