# workspace_coordination/merge/

## Overview
Deferred ISOLATED_COPY workspace merge domain: serial merge + cleanup of deferred isolated workspaces, transient merge metadata key stripping, rollback snapshot registration, and per-turn merge warning tracking.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Aggregate facade re-exporting batch_merge, merge_metadata, merge_snapshots, and merge_warning | ✅ |
| batch_merge.py | Core | Serial merge + cleanup of deferred ISOLATED_COPY workspaces; discard_deferred_isolated_workspaces for alternatives mode | ✅ |
| merge_metadata.py | Core | MERGE_TRANSIENT_INNER_KEYS + strip_merge_transient_inner_keys SSOT for spawn store and batch merge metadata cleanup | ✅ |
| merge_snapshots.py | Core | Revert snapshot registration + build_merge_snapshot_context; apply_isolated_sync_back_with_snapshots for immediate ISOLATED_COPY sync_back | ✅ |
| merge_warning.py | Core | Per-turn ContextVar tracker; merge failures -> WORKSPACE_MERGE_FAILED SSE + completion_status: warning | ✅ |

## Module Dependencies

- `agent.sub_agents.types::SubagentConfig`, `WorkspacePolicy`
