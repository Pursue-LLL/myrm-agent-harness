# memory_retrieval/

## Overview
Dataset-driven memory retrieval quality evaluation. Framework-only; business layer supplies `MemoryRetrievalAdapter`.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports runner and protocol types | — |
| protocols.py | Core | MemoryRetrievalEvalCase, MemoryRetrievalAdapter protocol, summary DTOs | ✅ |
| runner.py | Core | MemoryRetrievalEvalRunner — ingest, query, score, aggregate IR metrics | ✅ |
| datasets/coding_agent_life.json | Data | Sample eval dataset | — |

## Module Dependencies

- `eval.metrics` (hit_rate, nDCG, MRR)
- No `myrm-agent-server` imports
