# tests/eval/

## Overview

Unit tests for `myrm_agent_harness.eval` — assertion engines (sandbox/file/command/json, state, semantic), task-native suite judge + reward/JUnit payload parsing, runner, loader, builder, reporters, protocols, metrics, and `memory_retrieval/` submodule.

## File Index

| File | Covers |
|------|--------|
| `conftest.py` | shared fixtures (executor bound to temp workspace) |
| `test_assertions.py` | sandbox/file/command/json assertion engine |
| `test_matrix.py` | cross-profile matrix evaluation (MatrixRunner/MatrixResult) |
| `test_builder.py` | trajectory extraction & skill eval case generation |
| `test_runner.py` | EvalRunner single/multi-turn and concurrency |
| `test_loader.py` | JSON case loading |
| `test_reporters.py` | JSONL and Markdown reporters |
| `test_protocol.py` | EvalCase / AgentExecutor protocol types |
| `test_metrics.py` | IR metrics (recall@k, NDCG, MRR) |
| `test_memory_retrieval.py` | memory retrieval eval runner |
| `test_reward_payload.py` | reward/JUnit payload parsing unit tests |
| `test_suite_judge.py` | task-native test suite judging integration tests |
| `test_state_assertions.py` | state assertion engine (evaluate_state_assertions) |
| `test_semantic_assertions.py` | semantic (LLM-as-a-judge) assertion engine |

## Key Dependencies

- `myrm_agent_harness.eval`
