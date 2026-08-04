# workspace_coordination/

## Overview
Parallel subagent workspace safety helpers — write isolation policy and serial merge of deferred ISOLATED_COPY workspaces.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports policy and batch merge helpers | — |
| policy.py | Core | `apply_parallel_write_isolation`, `count_parallel_writers` — WorkspacePolicy enforcement | — |
| merge_metadata.py | Core | `MERGE_TRANSIENT_INNER_KEYS` + `strip_merge_transient_inner_keys` SSOT for spawn store and batch merge metadata cleanup | — |
| batch_merge.py | Core | Serial merge + cleanup of deferred ISOLATED_COPY workspaces; `discard_deferred_isolated_workspaces` for alternatives discard | — |
| merge_snapshots.py | Core | Revert snapshot registration + `build_merge_snapshot_context` SSOT; `apply_isolated_sync_back_with_snapshots` for immediate ISOLATED_COPY sync_back | — |
| merge_warning.py | Core | Per-turn ContextVar tracker; merge failures → `WORKSPACE_MERGE_FAILED` SSE + `completion_status: warning` | ✅ |

Note: INHERIT delegate writes register via FileOperationObserver. ISOLATED_COPY merge (batch defer, race, tournament, DW, immediate sync_back) uses `merge_snapshots.py`. Transient merge inner keys are stripped via `merge_metadata.py` before SQLite persistence and after merge/discard. Alternatives mode discards deferred child workspaces via `discard_deferred_isolated_workspaces`.

## Module Dependencies

- `agent.sub_agents.types::SubagentConfig`, `WorkspacePolicy`
