# maintenance/

## Overview
Wiki health checks and auto-maintenance. Broken link detection, completeness checks,
LLM-driven consistency checks, knowledge drift defense (drift + stale),
LLM-driven wikilink enrichment, and proactive knowledge-gap analysis
(isolated/bridge node detection via graph insights).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Init | — |
| linter.py | Core | Health checker: broken links, completeness (report-only), frontmatter auto-fix + link enrichment via publish gate | ✅ |

## Key Dependencies

- `core` (config, structure, types)
- `retrieval` (indexer for FTS5/edge updates)
- `web_search` (optional, for deep research)
