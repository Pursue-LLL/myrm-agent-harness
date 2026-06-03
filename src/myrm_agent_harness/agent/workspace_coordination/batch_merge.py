"""Serial merge of deferred ISOLATED_COPY workspaces after parallel batch delegation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

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


async def merge_batch_workspace_sync_backs(
    results: list[dict[str, object]],
) -> dict[str, object]:
    """Apply deferred workspace sync_backs in order (parent dir locked per merge)."""
    merged_count = 0
    merge_errors: list[str] = []

    for index, item in enumerate(results):
        if not isinstance(item, dict) or not item.get("success"):
            continue
        merge_target = _extract_merge_target(item)
        sync_back = _extract_sync_back(item)
        if merge_target is None and sync_back is None:
            continue
        try:
            if merge_target is not None:
                child_ws, parent_ws = merge_target
                if child_ws.is_dir():
                    _merge_from_isolated_child(child_ws, parent_ws)
            elif sync_back is not None:
                await _invoke_sync_back(sync_back)
            merged_count += 1
            if isinstance(item.get("result"), dict):
                item["result"] = {
                    k: v
                    for k, v in item["result"].items()
                    if k
                    not in (
                        "_workspace_sync_back",
                        "_isolated_child_workspace",
                        "_isolated_parent_workspace",
                    )
                }
                item["workspace_merge_status"] = "merged"
        except Exception as exc:
            message = f"task_index={index}: {exc}"
            logger.error("Batch workspace merge failed: %s", message)
            merge_errors.append(message)
            item["workspace_merge_status"] = "error"
            item["workspace_merge_error"] = str(exc)

    return {
        "workspace_merge_merged_count": merged_count,
        "workspace_merge_errors": merge_errors,
        "workspace_merge_ok": not merge_errors,
    }
