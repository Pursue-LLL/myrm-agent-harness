# Parallel Task Execution (Harness)

Shared parallel subagent spawn path for `batch_delegate_tasks_tool` and Swarm Fission.

| Module | Role |
|--------|------|
| `config.py` | Default/cap for swarm fission concurrency |
| `schemas.py` | `ParallelTaskResults` resume contract |
| `summary.py` | Public `batch_summary` / `inject_capacity_signal` |
| `resume_compact.py` | Vault/truncate oversized resume payloads |
| `runner.py` | `run_parallel_task_requests` — concurrent `_delegate.coroutine` with semaphore |
| `fission.py` | `execute_swarm_fission` — parse interrupt payload `tasks[]`, resume dict |

Swarm Fission must **not** use `execute_dag_plan`; it reuses the same spawn metadata path as batch delegate.
