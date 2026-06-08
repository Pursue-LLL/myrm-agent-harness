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

| Submodule | Description |
|-----------|-------------|
| memory_retrieval/ | Memory retrieval quality eval. See [memory_retrieval/_ARCH.md](memory_retrieval/_ARCH.md). |

## Key Dependencies

- `toolkits`
- `litellm` (for SemanticAssertion LLM-as-a-Judge)
