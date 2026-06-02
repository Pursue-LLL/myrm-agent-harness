# eval/

## Overview
Eval Framework — Agent behavior quality evaluation. Supports multi-dimensional assertions (tool, state, sandbox, semantic/LLM-as-a-Judge), concurrent execution, and pluggable reporting.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Eval Framework — Agent behavior quality evaluation. | — |
| assertions.py | Core | Multi-type assertion engine: tool, state (contains/not_contains/regex/json_valid/json_schema/custom_python/jaccard), sandbox, semantic (LLM-as-a-Judge with custom prompt/model + threshold soft-scoring). | ✅ |
| builder.py | Core | Captures agent trajectories and transforms them into reusable EvalCases. | ✅ |
| loader.py | Core | Convenience utilities for loading eval cases from JSON files. | ✅ |
| protocols.py | Core | Defines the eval framework's type system (EvalCase, MultiTurnEvalCase, SemanticAssertion with judge_prompt/judge_model/threshold, AgentResponse with token_usage/cost) and the AgentExecutor protocol. | ✅ |
| reporters.py | Core | Out-of-the-box JSONL (with time_secs, usage, avg aggregates) and Markdown reporting. | ✅ |
| runner.py | Core | Orchestrates eval execution. Supports concurrent case execution via asyncio.Semaphore, progress callbacks, single/multi-turn scenarios. | ✅ |

| metrics.py | Core | Pure IR metric functions: recall@k, precision@k, ndcg@k, mrr, hit_rate, latency_percentile. Reusable across eval submodules. | ✅ |
| memory_retrieval/ | Submodule | Memory retrieval evaluation framework with pluggable adapter protocol, built-in datasets, and orchestration runner. | — |
| memory_retrieval/__init__.py | Package | Public API: MemoryRetrievalEvalRunner, MemoryRetrievalAdapter, load_eval_cases, MemoryRetrievalEvalSummary. | — |
| memory_retrieval/protocols.py | Core | DTOs (MemoryRetrievalEvalCase, CaseResult, CategorySummary, EvalSummary) and MemoryRetrievalAdapter protocol. | ✅ |
| memory_retrieval/runner.py | Core | Orchestrates eval case execution via adapter, computes IR metrics per case and aggregate summary. | ✅ |
| memory_retrieval/datasets/ | Data | Built-in evaluation datasets (coding_agent_life.json: 8 categories, bilingual). | — |

## Key Dependencies

- `toolkits`
- `litellm` (for SemanticAssertion LLM-as-a-Judge)
