# tests/eval/

## Overview

Unit tests for `myrm_agent_harness.eval` — assertions, runner, loader, reporters, protocols, metrics, and `memory_retrieval/` submodule.

## File Index

| File | Covers |
|------|--------|
| `test_assertions.py` | tool/state/sandbox/semantic assertion engine |
| `test_runner.py` | EvalRunner single/multi-turn and concurrency |
| `test_loader.py` | JSON case loading |
| `test_reporters.py` | JSONL and Markdown reporters |
| `test_protocol.py` | EvalCase / AgentExecutor protocol types |
| `test_metrics.py` | IR metrics (recall@k, NDCG, MRR) |
| `test_memory_retrieval.py` | memory retrieval eval runner |

## Key Dependencies

- `myrm_agent_harness.eval`
