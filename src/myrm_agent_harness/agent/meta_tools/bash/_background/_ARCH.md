# _background/

## Overview

Background bash process registry and durable job ledger for ``bash_code_execute_tool(run_in_background=True)`` and ``bash_process_tool``.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | 域聚合出口：导出 registry 单例 + 快照类型（6 个公共符号）。 | ✅ |
| types.py | Core | Shared dataclasses (`BackgroundProcessInfo`, `BackgroundQuotaError`, listener aliases). | ✅ |
| registry.py | Core | Process-wide singleton registry with per-session buckets, credential redaction, SIGTERM→SIGKILL kill, reap, ``kill_session_jobs``. | ✅ |
| consume.py | Core | Per-entry stdout/stderr reader loop, spill hooks, 10Hz adaptive progress throttle (with 100% terminal penetration & trailing flush), and finish listener dispatch. | ✅ |
| stdin.py | Core | ``write_background_stdin`` — raw/submit/EOF writes to live child stdin. | ✅ |
| store_sync.py | Core | Write-through helpers: spawn upsert, vault log ref, terminal state persist. | ✅ |
| poll.py | Core | Incremental poll snapshot builder for ``bash_process_tool`` / auto-yield. | ✅ |
| progress.py | Core | Parses ``MYRM_PROGRESS`` / ``MYRM_CHECKPOINT`` markers, ANSI CSI cleanse, alias/numeric coercion, non-finite clamp, and heuristic build output. | ✅ |
| job_store_core.py | Core | Pure reconcile/status helpers for BSDL durable ledger. | ✅ |
| job_store.py | Core | SQLite BackgroundJobStore on Volume (metadata, finish dedupe, orphan reconcile). | ✅ |
| output_spill.py | Core | Incremental vault spill for long background stdout/stderr. | ✅ |
| session_spawn_lifecycle.py | Core | Session spawn lifecycle markers (activate/clear, auto-clean when session has no running jobs). | ✅ |

## Key Dependencies

- `toolkits.code_execution.executors`
