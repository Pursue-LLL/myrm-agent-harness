# workspace_coordination/

## Overview
Parallel subagent workspace safety helpers — write isolation policy and serial merge of deferred ISOLATED_COPY workspaces.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Re-exports policy and batch merge helpers | — |
| policy.py | Core | `apply_parallel_write_isolation`, `count_parallel_writers` — WorkspacePolicy enforcement | — |
| merge/（子包） | Core | 延迟 ISOLATED_COPY workspace 合并子域：批合并 + 清理、合并元数据键 SSOT、回滚快照注册、失败告警追踪。4 个 `merge_*` 模块聚合于此，`merge/__init__.py` 为聚合门面统一 re-export | ✅ |

Note: INHERIT delegate writes register via FileOperationObserver. ISOLATED_COPY merge (batch defer, race, tournament, DW, immediate sync_back) uses `merge/merge_snapshots.py`. Transient merge inner keys are stripped via `merge/merge_metadata.py` before SQLite persistence and after merge/discard. Alternatives mode discards deferred child workspaces via `discard_deferred_isolated_workspaces`.

## Module Dependencies

- `agent.sub_agents.types::SubagentConfig`, `WorkspacePolicy`
