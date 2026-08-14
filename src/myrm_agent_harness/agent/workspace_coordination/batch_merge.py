"""Serial merge of deferred ISOLATED_COPY workspaces after parallel batch delegation.

[INPUT]
- workspace_coordination.merge_metadata::strip_merge_transient_inner_keys (POS: merge metadata key SSOT)
- workspace_coordination.merge_snapshots::MergeSnapshotContext, record_isolated_merge_snapshots (POS: Revert snapshot registration)
- workspace_coordination.merge_warning::record_workspace_merge_failure (POS: Per-turn tracker bridging batch_merge failures to post_run_events warning SSE)
- sub_agents.workspace_isolation::_merge_tree_additive (POS: Additive workspace merge)

[OUTPUT]
- merge_batch_workspace_sync_backs: serial deferred merge with optional revert snapshots; records turn warning on merge errors
- discard_deferred_isolated_workspaces: rmtree child workspaces without merge (alternatives mode)

[POS]
Serial lifecycle for deferred ISOLATED_COPY workspaces after parallel batch delegation.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

from myrm_agent_harness.agent.workspace_coordination.merge_metadata import (
    strip_merge_transient_inner_keys,
)
from myrm_agent_harness.agent.workspace_coordination.merge_snapshots import (
    MergeSnapshotContext,
    record_isolated_merge_snapshots,
    schedule_merge_snapshot_persist,
)
from myrm_agent_harness.agent.workspace_coordination.merge_warning import (
    record_workspace_merge_failure,
)

logger = logging.getLogger(__name__)


def _extract_merge_target(
    result_item: dict[str, object],
) -> tuple[Path, Path] | None:
    inner = result_item.get("result")
    if not isinstance(inner, dict):
        return None
    child_ws = inner.get("_isolated_child_workspace")
    parent_ws = inner.get("_isolated_parent_workspace")
    if isinstance(child_ws, str) and isinstance(parent_ws, str):
        return Path(child_ws), Path(parent_ws)
    return None


def _extract_sync_back(result_item: dict[str, object]) -> Callable[[], object] | None:
    inner = result_item.get("result")
    if not isinstance(inner, dict):
        return None
    sync_back = inner.get("_workspace_sync_back")
    return sync_back if callable(sync_back) else None


async def _invoke_sync_back(sync_back: Callable[[], object]) -> None:
    outcome = sync_back()
    if asyncio.iscoroutine(outcome) or isinstance(outcome, Awaitable):
        await cast(Awaitable[object], outcome)


def _merge_from_isolated_child(child_workspace: Path, parent_workspace: Path) -> None:
    from myrm_agent_harness.agent.sub_agents.workspace_isolation import (
        _merge_tree_additive,
    )

    _merge_tree_additive(child_workspace, parent_workspace)


def _cleanup_child_workspace(child_workspace: Path) -> None:
    if child_workspace.is_dir():
        shutil.rmtree(child_workspace, ignore_errors=True)


def _strip_merge_metadata(item: dict[str, object]) -> None:
    inner = item.get("result")
    if isinstance(inner, dict):
        item["result"] = strip_merge_transient_inner_keys(inner)


def discard_deferred_isolated_workspaces(
    results: list[object],
) -> int:
    """Remove deferred ISOLATED_COPY child workspaces without merging.

    Used by alternatives mode: comparison output is text-only; isolated dirs are discarded.
    Strips transient merge metadata from every result dict after cleanup.
    Returns the number of child workspaces removed.
    """
    from myrm_agent_harness.agent.sub_agents.types import SubAgentResult

    removed = 0
    for item in results:
        if not isinstance(item, SubAgentResult):
            continue
        inner = item.result
        if not isinstance(inner, dict):
            continue
        child_raw = inner.get("_isolated_child_workspace")
        if isinstance(child_raw, str):
            child_path = Path(child_raw)
            if child_path.is_dir():
                _cleanup_child_workspace(child_path)
                removed += 1
        item.result = strip_merge_transient_inner_keys(inner)
    return removed


async def merge_batch_workspace_sync_backs(
    results: list[dict[str, object]],
    *,
    snapshot_context: MergeSnapshotContext | None = None,
) -> dict[str, object]:
    """Apply deferred workspace sync_backs in order (parent dir locked per merge)."""
    merge_snapshot_ctx = snapshot_context
    merged_count = 0
    merge_errors: list[str] = []

    for index, item in enumerate(results):
        if not isinstance(item, dict) or not item.get("success"):
            continue
        merge_target = _extract_merge_target(item)
        sync_back = _extract_sync_back(item)
        if merge_target is None and sync_back is None:
            continue
        task_id = item.get("task_id")
        task_label = f"task_id={task_id}" if isinstance(task_id, str) else f"task_index={index}"
        try:
            did_merge = False
            child_ws: Path | None = merge_target[0] if merge_target is not None else None
            if merge_target is not None:
                child_ws, parent_ws = merge_target
                if child_ws.is_dir():
                    if merge_snapshot_ctx is not None:
                        record_isolated_merge_snapshots(child_ws, parent_ws, merge_snapshot_ctx)
                    else:
                        _merge_from_isolated_child(child_ws, parent_ws)
                    did_merge = True
                elif sync_back is not None:
                    await _invoke_sync_back(sync_back)
                    did_merge = True
                else:
                    raise FileNotFoundError(f"{task_label}: isolated child workspace missing and no sync_back")
            elif sync_back is not None:
                await _invoke_sync_back(sync_back)
                did_merge = True

            if not did_merge:
                raise RuntimeError(f"{task_label}: no workspace merge action performed")

            if child_ws is not None:
                _cleanup_child_workspace(child_ws)

            merged_count += 1
            _strip_merge_metadata(item)
            item["workspace_merge_status"] = "merged"
        except Exception as exc:
            message = f"{task_label}: {exc}"
            logger.error("Batch workspace merge failed: %s", message)
            merge_errors.append(message)
            item["workspace_merge_status"] = "error"
            item["workspace_merge_error"] = str(exc)

    if merge_snapshot_ctx is not None and merged_count > 0:
        schedule_merge_snapshot_persist(merge_snapshot_ctx)

    if merge_errors:
        for error_message in merge_errors:
            record_workspace_merge_failure(str(error_message))

    return {
        "workspace_merge_merged_count": merged_count,
        "workspace_merge_errors": merge_errors,
        "workspace_merge_ok": not merge_errors,
    }
