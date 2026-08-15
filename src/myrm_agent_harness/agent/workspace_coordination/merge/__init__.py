"""Deferred ISOLATED_COPY workspace merge domain.

[INPUT]
- Spawn store results (deferred ISOLATED_COPY workspaces, sync_back callables).
- Revert snapshot context resolved from parent agent / message / workspace root.
- Per-turn merge failure reports from parallel runners.

[OUTPUT]
- Aggregate facade re-exporting every public name of the ``merge`` subpackage:
  - batch_merge: serial merge + cleanup of deferred ISOLATED_COPY workspaces;
    `discard_deferred_isolated_workspaces` for alternatives discard
  - merge_metadata: `MERGE_TRANSIENT_INNER_KEYS` + `strip_merge_transient_inner_keys`
    SSOT for spawn store and batch merge metadata cleanup
  - merge_snapshots: revert snapshot registration + `build_merge_snapshot_context`;
    `apply_isolated_sync_back_with_snapshots` for immediate ISOLATED_COPY sync_back
  - merge_warning: per-turn ContextVar tracker; merge failures →
    `WORKSPACE_MERGE_FAILED` SSE + `completion_status: warning`

[POS]
Framework generic capability for parallel-subagent workspace safety. Merge of
deferred ISOLATED_COPY workspaces is one coherent domain across batch merge,
snapshot registration and warning tracking, so the four modules stay
co-located under one facade.
"""

from myrm_agent_harness.agent.workspace_coordination.merge.batch_merge import (
    discard_deferred_isolated_workspaces,
    merge_batch_workspace_sync_backs,
)
from myrm_agent_harness.agent.workspace_coordination.merge.merge_metadata import (
    MERGE_TRANSIENT_INNER_KEYS,
    strip_merge_transient_inner_keys,
)
from myrm_agent_harness.agent.workspace_coordination.merge.merge_snapshots import (
    MergeSnapshotContext,
    apply_isolated_sync_back_with_snapshots,
    build_merge_snapshot_context,
    record_isolated_merge_snapshots,
    schedule_merge_snapshot_persist,
)
from myrm_agent_harness.agent.workspace_coordination.merge.merge_warning import (
    format_workspace_merge_failures,
    has_workspace_merge_warning,
    record_workspace_merge_failure,
    reset_workspace_merge_warning,
)

__all__ = [
    "MERGE_TRANSIENT_INNER_KEYS",
    "MergeSnapshotContext",
    "apply_isolated_sync_back_with_snapshots",
    "build_merge_snapshot_context",
    "discard_deferred_isolated_workspaces",
    "format_workspace_merge_failures",
    "has_workspace_merge_warning",
    "merge_batch_workspace_sync_backs",
    "record_isolated_merge_snapshots",
    "record_workspace_merge_failure",
    "reset_workspace_merge_warning",
    "schedule_merge_snapshot_persist",
    "strip_merge_transient_inner_keys",
]
