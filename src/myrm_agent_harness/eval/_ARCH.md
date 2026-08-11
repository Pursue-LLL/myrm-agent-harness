# eval/

## Overview
Eval Framework — Agent behavior quality evaluation. Supports multi-dimensional assertions (tool, state, sandbox, test_suite, semantic/LLM-as-a-Judge), concurrent execution, and pluggable reporting.

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
| __init__.py | Package | Eval Framework — Agent behavior quality evaluation. Exports the framework benchmark registry (`BenchmarkSpec`, `register_benchmark`, `list_benchmarks`, `get_benchmark`), `SemanticAssertion`, and the rest of the public API. | — |
| assertions.py | Core | Multi-type assertion engine: tool, state (contains/not_contains/regex/json_valid/json_schema/custom_python/jaccard), sandbox (file/cmd/json + `test_suite` delegation), semantic (LLM-as-a-Judge with custom prompt/model + threshold soft-scoring, judge 响应经 `extract_litellm_answer_text` 提取以兼容 reasoning 模型 content 空回退). Re-exports `test_suite` helpers from `suite_judge` to keep the public API stable. | ✅ |
| suite_judge.py | Core | Task-native test suite judge (Rule): `evaluate_test_suite_assertion` runs the suite command resolved from `SandboxAssertion.result_file` (JUnit XML or reward payload, timeout overridable via `SandboxAssertion.timeout`, default 600s). The target command may reference the live agent workspace via the `{workspace}` placeholder; `SandboxAssertion.readonly_paths` mounts external grading assets read-only for the grader command. `parse_junit_result` (skipped excluded from pass count), `parse_reward_result` (bare numeric text or JSON; field order `reward`→`overall`→`test_pass_rate`→`score` matching the official WBBench reward payload reader, with `pass_rate`/`reward_score` kept for backward compatibility; `_counts_from_reward` adds the official counts fallback for payloads carrying only `tests_passed`/`tests_total` or a `tests[]` array). Reward files resolve the declared `result_file` with `score.json`/`reward.json`/`reward.txt` sibling fallback matching the official candidate paths plus the Code `script_verifier` numeric spelling. Failure details append a bounded tail of the suite command's output (`_with_output_tail`) so a timeout/crash/non-zero exit/unreadable result file exposes where the grader stopped. | ✅ |
| builder.py | Core | Captures agent trajectories and transforms them into reusable EvalCases. Provides `build_skill_eval_cases` for lightweight regression test generation bound to SkillRecord. | ✅ |
| loader.py | Core | Convenience utilities for loading eval cases from JSON files. | ✅ |
| matrix.py | Core | Cross-profile matrix evaluation. `MatrixRunner` runs the same cases against multiple `AgentExecutor` instances sequentially; `MatrixResult` aggregates results with stable/regression classification; `MatrixCellResult` gives per-case-per-profile detail. | ✅ |
| protocols.py | Core | Defines the eval framework's type system (EvalCase, MultiTurnEvalCase with on_turn_fail strategy, OnTurnFail, EvalManifest for environment reproducibility snapshots with profile_id/benchmark_mode, SemanticAssertion with judge_prompt/judge_model/threshold, SandboxAssertion with result_file/timeout/readonly_paths, EvalTurnResult with per-turn scores, EvalResult aggregating `avg_pass_rate` = mean of per-turn test pass rates) and the AgentExecutor protocol. | ✅ |
| reporters.py | Core | Out-of-the-box JSONL (with time_secs, usage, scores, per-assertion result_file/readonly_paths, and `avg_pass_rate` summary) and Markdown reporting (incl. Avg Test Pass Rate line). | ✅ |
| runner.py | Core | Orchestrates eval execution. Supports concurrent case execution via asyncio.Semaphore, progress callbacks, single/multi-turn scenarios with configurable `on_turn_fail` strategy (continue/skip_remaining/abort). Collects sandbox/test_suite scores into each EvalTurnResult. | ✅ |
| metrics.py | Core | Pure IR metric functions: recall@k, precision@k, ndcg@k, mrr, hit_rate, latency_percentile. Reusable across eval submodules. | ✅ |

| Submodule | Description |
|-----------|-------------|
| memory_retrieval/ | Memory retrieval quality eval. See [memory_retrieval/_ARCH.md](memory_retrieval/_ARCH.md). |

## Key Dependencies

- `toolkits`
- `litellm` (for SemanticAssertion LLM-as-a-Judge)
