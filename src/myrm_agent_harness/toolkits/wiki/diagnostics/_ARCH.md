# wiki/diagnostics/

## Overview

Deterministic wiki quality measurement — zero LLM, zero agent tools. Consumed by
server `/wiki/stats` and CI retrieval regression gates.

## Files

| File | Role |
|------|------|
| `structural_lint.py` | SSOT for broken links + frontmatter type gate counts |
| `recall_benchmark.py` | Offline FTS retrieval benchmark (hit@k, latency) |

## Boundaries

- **In scope**: read-only vault scans, indexer.search probes
- **Out of scope**: LLM drift/consistency (WikiLinter maintain path), user-facing health scores, agent tools
