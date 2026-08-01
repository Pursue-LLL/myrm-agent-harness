# memory_retrieval/

## Overview
Dataset-driven memory retrieval quality evaluation. Framework-only; business layer supplies `MemoryRetrievalAdapter`.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports runner and protocol types | — |
| protocols.py | Core | MemoryRetrievalEvalCase, MemoryRetrievalAdapter protocol, summary DTOs | ✅ |
| runner.py | Core | MemoryRetrievalEvalRunner — ingest, query, score, aggregate IR metrics | ✅ |
| datasets/coding_agent_life.json | Data | Eval dataset: 8 categories + adversarial probes, bilingual EN/ZH | — |

## Module Dependencies

- `eval.metrics` (recall_at_k, precision_at_k, ndcg_at_k, mrr, hit_rate, false_positive_rate, latency_percentile)
- No `myrm-agent-server` imports

## Metrics (7 dimensions)

| Metric | Purpose |
|--------|---------|
| recall@5/10 | Fraction of gold items found in top-K |
| precision@5 | Fraction of top-K that are gold items |
| nDCG@10 | Ranking quality (position-aware) |
| MRR | Reciprocal rank of first gold hit |
| hit@5 | Binary: any gold item in top-5 |
| false_positive@10 | Adversarial: detects results returned for queries that should match nothing |
| latency p50/p95 | Performance percentiles |
