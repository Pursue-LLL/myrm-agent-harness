# wiki/diagnostics/

## Overview

Deterministic wiki quality measurement — zero LLM, zero agent tools. Consumed by
server `/wiki/stats` and CI retrieval regression gates.

## Files

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package marker and re-exports for the diagnostics module. | — |
| `structural_lint.py` | Core | SSOT for broken markdown links (code-fence aware), broken `[[wikilink]]` targets (path + title alias), frontmatter type gate counts, and raw-backed provenance gaps | ✅ |
| `recall_benchmark.py` | Core | Offline **Tier-1** FTS indexer benchmark (hit@k, latency). **Tier-2** query-path claim-health cases live in `tests/toolkits/wiki/test_query_closure_v2.py` (CI via harness `test.yml`) | ✅ |

## Boundaries

- **In scope**: read-only vault scans, indexer.search probes, documented cross-reference to query-path pytest gate
- **Out of scope**: LLM drift/consistency (WikiLinter maintain path), user-facing health scores, agent tools
