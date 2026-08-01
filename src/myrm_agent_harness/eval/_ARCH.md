# eval/

## Overview
Eval Framework — Agent behavior quality evaluation. Supports multi-dimensional assertions (tool, state, sandbox, semantic/LLM-as-a-Judge), concurrent execution, and pluggable reporting.

## Placement (why top-level `eval/`, not `toolkits/` or `tests/`)

| Candidate | Verdict |
|-----------|---------|
| `toolkits/eval/` | ❌ Not an agent-callable domain capability; violates [toolkits/_ARCH.md](../toolkits/_ARCH.md) |
| `agent/eval/` | ❌ Runner uses `AgentExecutor` Protocol — must not import Agent runtime |
| `tests/` only | ❌ Shipped product surface: `myrm-agent-server/app/core/eval/` runs suites in production |
| **Top-level `eval/`** | ✅ Framework subsystem; business implements Protocol in server |

Business wiring (AgentFactory, background jobs, GUI flywheel) lives in **`myrm-agent-server/app/core/eval/`**, not here.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Eval Framework — Agent behavior quality evaluation. | — |
| assertions.py | Core | Multi-type assertion engine: tool, state (contains/not_contains/regex/json_valid/json_schema/custom_python/jaccard), sandbox, semantic (LLM-as-a-Judge with custom prompt/model + threshold soft-scoring). | ✅ |
| builder.py | Core | Captures agent trajectories and transforms them into reusable EvalCases. Provides `build_skill_eval_cases` for lightweight regression test generation bound to SkillRecord. | ✅ |
| loader.py | Core | Convenience utilities for loading eval cases from JSON files. | ✅ |
| matrix.py | Core | Cross-profile matrix evaluation. `MatrixRunner` runs the same cases against multiple `AgentExecutor` instances sequentially; `MatrixResult` aggregates results with stable/regression classification; `MatrixCellResult` gives per-case-per-profile detail. | ✅ |
| protocols.py | Core | Defines the eval framework's type system (EvalCase, MultiTurnEvalCase with on_turn_fail strategy, OnTurnFail, EvalManifest for environment reproducibility snapshots with profile_id/benchmark_mode, SemanticAssertion with judge_prompt/judge_model/threshold, AgentResponse with token_usage/cost) and the AgentExecutor protocol. | ✅ |
| reporters.py | Core | Out-of-the-box JSONL (with time_secs, usage, avg aggregates) and Markdown reporting. | ✅ |
| runner.py | Core | Orchestrates eval execution. Supports concurrent case execution via asyncio.Semaphore, progress callbacks, single/multi-turn scenarios with configurable `on_turn_fail` strategy (continue/skip_remaining/abort). | ✅ |
| metrics.py | Core | Pure IR metric functions: recall@k, precision@k, ndcg@k, mrr, hit_rate, latency_percentile. Reusable across eval submodules. | ✅ |

| Submodule | Description |
|-----------|-------------|
| memory_retrieval/ | Memory retrieval quality eval. See [memory_retrieval/_ARCH.md](memory_retrieval/_ARCH.md). |

## Key Dependencies

- `toolkits`
- `litellm` (for SemanticAssertion LLM-as-a-Judge)
