# code_graph/

## Overview

AST-based code knowledge graph — Tree-sitter multi-language parsing → SQLite graph storage → structural queries (impact radius, call chains, execution flows, architecture hotspots). Framework-agnostic; no `agent/` imports.

Inspired by Aider's RepoMap (tree-sitter + PageRank), Goose's analyze extension (tree-sitter + CallGraph), and code-review-graph's full-featured knowledge graph. Surpasses all three by combining their strengths with modular architecture, streaming memory safety, and integration into the existing Memory/Retriever/Wiki ecosystem.

## Architecture gate

- **Generic capability**: ✅ Any Agent framework can use code graph analysis
- **Zero agent/ imports**: ✅ Pure capability package
- **Self-contained**: ✅ Only depends on tree-sitter + SQLite + optional networkx/igraph
- **Category**: Workspace (alongside `browser/`, `filesystem_suggest/`, `wiki/`)
- **Tool layer**: EXTENDED — not loaded by default, user opts in via agent config

## Dependencies

### Required

- `utils/` — `db/fts5.py` for FTS5 sanitization
- `core/` — framework config (MYRM_DATA_DIR)

### Optional (installable via `[code-graph]` extra)

- `tree-sitter-language-pack` — multi-language grammar support
- `networkx` — betweenness centrality (Bridge node detection)
- `igraph` — Leiden community detection (with file-grouping fallback)

### Forbidden

- `agent/` — NEVER
- `backends/` — not a toolkit concern
- `runtime/` — not a toolkit concern

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public API: `CodeGraphStore`, `CodeGraphBuilder`, `CodeGraphAnalyzer` | ✅ |
| `store.py` | Core | SQLite graph storage — nodes, edges (UNIQUE dedup), FTS5, composite indexes, schema migrations | ✅ |
| `builder.py` | Core | Graph builder — full/incremental builds, parallel parsing (ThreadPoolExecutor), streaming memory safety | ✅ |
| `analysis.py` | Core | Impact radius (BFS), Hub/Bridge detection, Leiden community detection | ✅ |
| `flows.py` | Core | Execution flow detection — entry point identification, forward tracing | ✅ |
| `search.py` | Core | FTS5 + vector semantic hybrid search with kind/context boosting | ✅ |
| `lifecycle.py` | Core | Graph data lifecycle — workspace-hashed DB naming, TTL cleanup | ✅ |
| `code_graph_agent_tools.py` | Adapter | LangChain `StructuredTool` factory for Agent consumers (EXTENDED layer) | ✅ |

| Submodule | Description |
|-----------|-------------|
| `parser/` | Tree-sitter multi-language AST parsing — Protocol + per-language extractors + custom extension |

### parser/ Submodule Index

| File | Role | Description |
|------|------|-------------|
| `__init__.py` | Package | Parser factory — `get_parser()`, `register_custom_parsers()`, optional dependency detection |
| `_base.py` | Protocol | `LanguageParser` Protocol — parse contract for all language extractors |
| `_python.py` | Extractor | Python: functions, classes, imports, calls, decorators |
| `_javascript.py` | Extractor | JavaScript/TypeScript: functions, classes, imports, calls |
| `_java.py` | Extractor | Java: classes, methods, imports, annotations |
| `_go.py` | Extractor | Go: functions, structs, interfaces, imports |
| `_rust.py` | Extractor | Rust: functions, structs, traits, impl blocks, use declarations |
| `_c_cpp.py` | Extractor | C/C++: functions, structs, classes, includes, calls |
| `_custom.py` | Extension | `languages.toml` declarative language extension for enterprise private languages |

## Agent Tool Design

Two tools, ~550 tokens total, EXTENDED layer (not loaded by default):

| Tool | Purpose | Estimated tokens |
|------|---------|-----------------|
| `code_graph_query` | Unified query entry (impact_radius / callers / dependencies / structure_search / execution_flows / hotspots) | ~400 |
| `code_graph_build` | Build or incrementally update the code graph | ~150 |

## Data Storage

- SQLite database at `{MYRM_DATA_DIR}/code_graph/{workspace_hash}.db`
- Each workspace gets its own isolated graph database
- Automatic TTL-based cleanup for stale workspace graphs
