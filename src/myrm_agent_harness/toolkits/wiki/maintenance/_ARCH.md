# maintenance/

## Overview
Wiki health checks and auto-maintenance. Broken link detection, completeness checks,
LLM-driven consistency checks, knowledge drift defense (drift + stale),
LLM-driven wikilink enrichment, and proactive knowledge-gap analysis
(isolated/bridge node detection via graph insights).

Deterministic broken markdown/wikilink links and frontmatter-type checks live in `../diagnostics/structural_lint.py` (SSOT); `linter.py` delegates to that module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Init | — |
| linter.py | Core | Health checker: broken links, completeness (report-only), frontmatter auto-fix + link enrichment via publish gate; stale via `stale_summary` | ✅ |
| stale_summary.py | Core | Raw-source stale detection vs `last_compile_time`; path set + concept stale-source matching + raw ingest tri-state resolver for linter, product API, and tree badges | ✅ |

## Key Dependencies

- `core` (config, structure, types)
- `retrieval` (indexer for FTS5/edge updates)
- `web_search` (optional, for deep research)
