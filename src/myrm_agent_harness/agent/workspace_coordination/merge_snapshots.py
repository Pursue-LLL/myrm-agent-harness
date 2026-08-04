"""Revert snapshot registration for ISOLATED_COPY workspace merges.

[INPUT]
- agent.meta_tools.file_ops.observers.snapshot_observer::SnapshotStore (POS: Revert snapshot index)
- agent.sub_agents.workspace_isolation::_merge_tree_additive (POS: Additive workspace merge)

[OUTPUT]
- MergeSnapshotContext: session/message/workspace binding for merge-time snapshots
- build_merge_snapshot_context: SSOT resolver for session/message/workspace ids
- record_isolated_merge_snapshots: merge child workspace and register revert entries
- apply_isolated_sync_back_with_snapshots: sync_back with per-file revert snapshot registration
- schedule_merge_snapshot_persist: async disk persistence for registered snapshots

[POS]
Registers revert snapshots when ISOLATED_COPY child workspaces merge into the parent.
Callers use build_merge_snapshot_context for session/message binding.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
    MAX_FILE_BYTES,
    FileSnapshot,
    SnapshotOp,
    SnapshotSkipReason,
    SnapshotStore,
)
from myrm_agent_harness.agent.sub_agents.workspace_isolation import (
    _merge_tree_additive,
    _sync_tree,
)

logger = logging.getLogger(__name__)

_persist_tasks: set[asyncio.Task[None]] = set()


@dataclass(frozen=True, slots=True)
class MergeSnapshotContext:
    session_id: str
    message_id: str
    workspace_root: str


def _session_id_from_parent_context(parent_agent: object | None) -> str | None:
    parent_ctx = getattr(parent_agent, "_last_context", None) if parent_agent is not None else None
    if not isinstance(parent_ctx, dict):
        return None
    raw_chat_id = str(parent_ctx.get("chat_id") or "").strip()
    if raw_chat_id:
        return raw_chat_id
    session_id = str(parent_ctx.get("session_id") or "").strip()
    return session_id or None


def _resolve_merge_session_id(
    *,
    session_id: str | None,
    parent_agent: object | None,
) -> str | None:
    if session_id:
        return session_id

    parent_session = _session_id_from_parent_context(parent_agent)
    if parent_session:
        return parent_session

    from myrm_agent_harness.agent.context_management.infra.session_lock import (
        get_current_chat_id,
    )
    from myrm_agent_harness.core.context_vars import chat_id_var

    chat_from_lock = get_current_chat_id()
    if chat_from_lock:
        return chat_from_lock

    delivery_chat = chat_id_var.get().strip()
    return delivery_chat or None


def _resolve_merge_message_id(message_id: str | None) -> str | None:
    if message_id:
        return message_id
    from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
        get_bound_message_id,
    )
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_active_message_id,
    )

    bound = get_bound_message_id()
    if bound:
        return bound
    active = get_active_message_id()
    return active or None


def _resolve_merge_workspace_root(
    *,
    workspace_root: str | None,
    parent_agent: object | None,
) -> str:
    if workspace_root:
        return workspace_root

    parent_ctx = getattr(parent_agent, "_last_context", None) if parent_agent is not None else None
    if isinstance(parent_ctx, dict):
        parent_workspace = str(parent_ctx.get("workspace_path") or "").strip()
        if parent_workspace:
            return parent_workspace

    from myrm_agent_harness.agent.middlewares._session_context import get_workspace_root

    active_workspace = get_workspace_root().strip()
    if active_workspace:
        return active_workspace

    from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import (
        WorkspacePathResolver,
    )

    return str(WorkspacePathResolver.resolve_workspace_root())


def build_merge_snapshot_context(
    *,
    session_id: str | None = None,
    message_id: str | None = None,
    workspace_root: str | None = None,
    parent_agent: object | None = None,
) -> MergeSnapshotContext | None:
    """Build revert snapshot context for ISOLATED_COPY workspace merge.

    Returns None when session_id or message_id cannot be resolved; merge still
    proceeds but revert snapshots are skipped for that batch.
    """
    resolved_session = _resolve_merge_session_id(session_id=session_id, parent_agent=parent_agent)
    resolved_message = _resolve_merge_message_id(message_id)
    if not resolved_session or not resolved_message:
        return None

    resolved_workspace = _resolve_merge_workspace_root(
        workspace_root=workspace_root,
        parent_agent=parent_agent,
    )

    return MergeSnapshotContext(
        session_id=resolved_session,
        message_id=resolved_message,
        workspace_root=resolved_workspace,
    )


def _relative_workspace_path(file_path: Path, workspace_root: Path) -> str:
    try:
        return str(file_path.resolve().relative_to(workspace_root.resolve()))
    except ValueError:
        return str(file_path)


def _read_original_for_snapshot(file_path: Path) -> tuple[str | None, SnapshotSkipReason | None]:
    try:
        size = file_path.stat().st_size
    except OSError:
        return None, SnapshotSkipReason.FILE_TOO_LARGE
    if size > MAX_FILE_BYTES:
        return None, SnapshotSkipReason.FILE_TOO_LARGE
    try:
        raw = file_path.read_bytes()
    except OSError:
        return None, SnapshotSkipReason.FILE_TOO_LARGE
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, SnapshotSkipReason.FILE_TOO_LARGE


def _record_snapshot(
    store: SnapshotStore,
    ctx: MergeSnapshotContext,
    rel_path: str,
    operation: SnapshotOp,
    original_content: str | None,
    skip_reason: SnapshotSkipReason | None,
) -> None:
    if skip_reason is not None:
        store.record_skipped(ctx.session_id, ctx.message_id, rel_path, operation, skip_reason)
        return
    snap = FileSnapshot(path=rel_path, operation=operation, original_content=original_content)
    if not store.record(ctx.session_id, ctx.message_id, snap):
        store.record_skipped(ctx.session_id, ctx.message_id, rel_path, operation, SnapshotSkipReason.STORE_FULL)


def _register_snapshot_for_dst_file(
    store: SnapshotStore,
    ctx: MergeSnapshotContext,
    workspace_root: Path,
    dst_file: Path,
) -> None:
    rel = _relative_workspace_path(dst_file, workspace_root)
    if not dst_file.exists():
        _record_snapshot(store, ctx, rel, SnapshotOp.CREATE, None, None)
    else:
        original, skip = _read_original_for_snapshot(dst_file)
        _record_snapshot(store, ctx, rel, SnapshotOp.MODIFY, original, skip)


def record_isolated_merge_snapshots(
    child_workspace: Path,
    parent_workspace: Path,
    ctx: MergeSnapshotContext,
) -> None:
    """Merge child into parent and register revert snapshots for each copied file."""
    workspace_root = Path(ctx.workspace_root).resolve()
    store = SnapshotStore.get()

    def before_copy(_src_file: Path, dst_file: Path) -> None:
        _register_snapshot_for_dst_file(store, ctx, workspace_root, dst_file)

    _merge_tree_additive(child_workspace, parent_workspace, before_copy=before_copy)


async def apply_isolated_sync_back_with_snapshots(
    *,
    child_workspace: Path,
    parent_workspace: Path,
    sync_back: Callable[[], object],
    parent_agent: object | None = None,
) -> None:
    """Run immediate ISOLATED_COPY sync_back and register revert snapshots."""
    merge_ctx = build_merge_snapshot_context(parent_agent=parent_agent)
    if (
        merge_ctx is not None
        and child_workspace.is_dir()
        and parent_workspace.is_dir()
    ):
        workspace_root = Path(merge_ctx.workspace_root).resolve()
        store = SnapshotStore.get()

        def before_copy(_src_file: Path, dst_file: Path) -> None:
            _register_snapshot_for_dst_file(store, merge_ctx, workspace_root, dst_file)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: _sync_tree(child_workspace, parent_workspace, before_copy=before_copy),
        )
        schedule_merge_snapshot_persist(merge_ctx)
        return

    outcome = sync_back()
    if asyncio.iscoroutine(outcome):
        await outcome


def schedule_merge_snapshot_persist(ctx: MergeSnapshotContext) -> None:
    store = SnapshotStore.get()
    if not store.get_message_snapshots(ctx.session_id, ctx.message_id):
        return
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(store.persist_to_disk(ctx.workspace_root, ctx.session_id, ctx.message_id))
        _persist_tasks.add(task)
        task.add_done_callback(_persist_tasks.discard)
    except RuntimeError:
        logger.debug("No running event loop; merge snapshots kept in memory only")
