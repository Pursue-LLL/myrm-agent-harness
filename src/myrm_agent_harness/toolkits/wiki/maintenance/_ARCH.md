# maintenance/

## Overview
Wiki health checks and auto-maintenance. Broken link detection, completeness checks,
LLM-driven wikilink enrichment, and proactive knowledge-gap analysis
(isolated/bridge node detection via graph insights). Cross-concept contradiction
synthesis runs at compile time (`pipeline/contradiction_synthesis/`).

Deterministic broken markdown/wikilink links and frontmatter-type checks live in `../diagnostics/structural_lint.py` (SSOT); `linter.py` delegates to that module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Init | — |
| linter.py | Core | Health checker: …; `lint_and_maintain(mode=STRUCTURAL|FULL)` — STRUCTURAL skips LLM drift/backlinks; post-maintain **vault git snapshot** when `enable_version_control` | ✅ |
| modes.py | Types | `MaintainMode` enum for cron vs manual maintain SSOT | ✅ |
| stale_summary.py | Core | Hash-based raw stale detection vs `last_compile_raw_hashes` snapshot; conservative all-raw-stale when compile time exists without hash snapshot; path set + concept stale-source matching + raw ingest tri-state resolver | ✅ |

## Key Dependencies

- `core` (config, structure, types)
- `retrieval` (indexer for FTS5/edge updates)
- `web_search` (optional, for deep research)
