# _background/

## Overview

Background bash process registry and durable job ledger for ``bash_code_execute_tool(run_in_background=True)`` and ``bash_process_tool``.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Public re-exports: registry singleton + snapshot types. | ✅ |
| types.py | Core | Shared dataclasses (`BackgroundProcessInfo`, `BackgroundQuotaError`, listener aliases). | ✅ |
| registry.py | Core | Process-wide singleton registry with per-session buckets, SIGTERM→SIGKILL kill, reap, ``kill_session_jobs``. | ✅ |
| consume.py | Core | Per-entry stdout/stderr reader loop, spill hooks, finish listener dispatch. | ✅ |
| stdin.py | Core | ``write_background_stdin`` — raw/submit/EOF writes to live child stdin. | ✅ |
| store_sync.py | Core | Write-through helpers: spawn upsert, vault log ref, terminal state persist. | ✅ |
| poll.py | Core | Incremental poll snapshot builder for ``bash_process_tool`` / auto-yield. | ✅ |
| progress.py | Core | Parses ``MYRM_PROGRESS`` / ``MYRM_CHECKPOINT`` markers and heuristic build output. | ✅ |
| job_store_core.py | Core | Pure reconcile/status helpers for BSDL durable ledger. | ✅ |
| job_store.py | Core | SQLite BackgroundJobStore on Volume (metadata, finish dedupe, orphan reconcile). | ✅ |
| output_spill.py | Core | Incremental vault spill for long background stdout/stderr. | ✅ |

## Key Dependencies

- `toolkits.code_execution.executors`
- `agent.meta_tools.bash._executor.session_spawn_lifecycle`
