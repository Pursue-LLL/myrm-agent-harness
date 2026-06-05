"""Diff collector observer — emits real-time per-file diffs to the SSE stream.

Computes unified diffs on file create/modify events using difflib (stdlib)
and pushes them via ToolProgressSink. Zero memory overhead (stateless observer).

[INPUT]
- (none)

[OUTPUT]
- DiffCollectorObserver: Emits cumulative per-file unified diffs for the current agent turn
  (baseline from SnapshotStore initial snapshot when present; otherwise uses event payload).
  When the initial snapshot is CREATE with missing pre-content but the current emit is a MODIFY,
  base content falls back to modify old_content so the diff is not shown as from /dev/null.

[POS]
Diff collector observer for Agent SSE: computes unified diffs with difflib and pushes file_diff
events via ToolProgressSink; aligns baseline with snapshot queue to avoid false “new file” hunks.
"""

from __future__ import annotations

import difflib
import logging

from myrm_agent_harness.agent.streaming.types import AgentEventType

from .base import FileOperationObserver

logger = logging.getLogger(__name__)

_MAX_DIFF_LINES = 2000
_FILE_DIFF_EVENT = AgentEventType.FILE_DIFF.value


def _compute_unified_diff(old_content: str, new_content: str, path: str, is_new: bool) -> tuple[str, int, int, int]:
    """Compute unified diff and line-change stats.

    Returns:
        (diff_text, lines_added, lines_removed, diff_line_count)
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    fromfile = "/dev/null" if is_new else f"a/{path}"
    tofile = f"b/{path}"

    diff_lines = list(difflib.unified_diff(old_lines, new_lines, fromfile=fromfile, tofile=tofile, n=3))

    added = sum(1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))

    return "".join(diff_lines), added, removed, len(diff_lines)


class DiffCollectorObserver(FileOperationObserver):
    """Emits real-time per-file unified diffs to the Agent SSE stream.

    Leverages ToolProgressSink (ContextVar) to push ``file_diff`` events.
    Silently skips when no sink is available (e.g. outside BaseAgent.run).
    """

    async def on_file_created(self, path: str, content: str) -> None:
        logger.info("on_file_created called for %s", path)
        if not content:
            logger.warning("Empty content for %s, skipping diff", path)
            return
        await self._emit_diff(old_content="", new_content=content, path=path, is_new=True)

    async def on_file_modified(self, path: str, old_content: str, new_content: str) -> None:
        logger.info("on_file_modified called for %s", path)
        if old_content == new_content:
            logger.warning("Content unchanged for %s, skipping diff", path)
            return
        await self._emit_diff(old_content=old_content, new_content=new_content, path=path, is_new=False)

    async def on_file_viewed(self, path: str) -> None:
        pass

    async def _emit_diff(self, *, old_content: str, new_content: str, path: str, is_new: bool) -> None:
        try:
            from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
                SnapshotOp,
                SnapshotStore,
                _get_session_id,
                get_current_message_id,
            )
            from myrm_agent_harness.utils.runtime.progress_sink import (
                get_tool_progress_sink,
            )

            sink = get_tool_progress_sink()
            if sink is None:
                logger.warning("No ToolProgressSink available, skipping diff emit for %s", path)
                return

            # 获取回合初的初始快照，以计算累积 Diff
            session_id = _get_session_id()
            message_id = get_current_message_id()
            store = SnapshotStore.get()
            initial_snap = store.get_initial_file_snapshot(session_id, message_id, path)

            if initial_snap:
                snap_is_blank_create = (
                    initial_snap.operation == SnapshotOp.CREATE and initial_snap.original_content is None
                )
                if snap_is_blank_create and not is_new:
                    # CREATE 误报在 MODIFY 之前入队时，避免把整个修改算成「从空文件新增」
                    base_content = old_content
                    base_is_new = False
                else:
                    base_content = initial_snap.original_content or ""
                    base_is_new = initial_snap.original_content is None
            else:
                base_content = old_content
                base_is_new = is_new

            diff_text, added, removed, line_count = _compute_unified_diff(base_content, new_content, path, base_is_new)
            if not diff_text:
                return

            truncated = line_count > _MAX_DIFF_LINES
            if truncated:
                diff_lines = diff_text.splitlines(keepends=True)
                diff_text = "".join(diff_lines[:_MAX_DIFF_LINES])

            event: dict[str, object] = {
                "type": _FILE_DIFF_EVENT,
                "data": {
                    "path": path,
                    "diff": diff_text,
                    "is_new": base_is_new,
                    "lines_added": added,
                    "lines_removed": removed,
                    "truncated": truncated,
                },
            }
            logger.info("Emitting file diff event: %s", event)
            await sink.emit(event)
        except Exception as e:
            logger.error("Failed to emit file diff: %s", e, exc_info=True)
