# parallel/

## Overview

Shared parallel subagent spawn path for `batch_delegate_tasks_tool` and Swarm Fission. Must **not** use `execute_dag_plan`; reuses the same spawn metadata path as batch delegate.

Detailed design: see [sub_agents/SUB_AGENT_SYSTEM.md](../sub_agents/SUB_AGENT_SYSTEM.md) (parallel execution section).

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports parallel runner and fission entrypoints. | — |
| `config.py` | Config | Default/cap for swarm fission concurrency. | — |
| `schemas.py` | Types | `ParallelTaskResults` resume contract. | — |
| `summary.py` | Core | Public `batch_summary` / `inject_capacity_signal`. | — |
| `resume_compact.py` | Utility | Vault/truncate oversized resume payloads. | — |
| `runner.py` | Core | `run_parallel_task_requests` — concurrent `_delegate.coroutine` with semaphore. | — |
| `fission.py` | Core | `execute_swarm_fission` — parse interrupt payload `tasks[]`, resume dict. | — |

## Module Dependencies

- `agent/sub_agents/` — spawn/delegate implementation
- `agent/meta_tools/spawn_subagent/` — batch_delegate_tasks_tool entry
