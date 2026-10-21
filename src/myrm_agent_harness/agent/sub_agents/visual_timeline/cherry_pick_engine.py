"""Surgical Cherry-Pick Rollback Engine for individual agent actions (Item 61).

[INPUT]
- Target TimelineNode to be reverted.
- TimelineJournal providing historical context and subsequent dependent mutations.
- Virtual/local file content accessor.

[OUTPUT]
- RollbackResult indicating SUCCESS, CONFLICT_DETECTED, or ALREADY_ROLLED_BACK.
- Precise reverse-patched content without affecting other collaborators' work.

[POS]
- Core surgical undo engine eliminating "one bad agent breaks everything" risks.
"""

from __future__ import annotations

import logging
import threading
import time

from .timeline_journal import TimelineJournal
from .types import RollbackResult, RollbackStatus, TimelineNode

logger = logging.getLogger(__name__)


class CherryPickRollbackEngine:
    """Performs isolated, single-agent atomic rollbacks with conflict protection."""

    def __init__(self, journal: TimelineJournal) -> None:
        self.journal = journal
        self._lock = threading.RLock()
        # Simulated/cached workspace VFS: file_path -> current_content
        self._vfs_store: dict[str, str] = {}

    def set_file_content(self, file_path: str, content: str) -> None:
        """Prime or update the virtual file content in workspace storage."""
        with self._lock:
            self._vfs_store[file_path] = content

    def get_file_content(self, file_path: str) -> str:
        """Read the current virtual file content."""
        with self._lock:
            return self._vfs_store.get(file_path, "")

    def _check_overlap(
        self,
        target_start: int | None,
        target_end: int | None,
        subsequent_start: int | None,
        subsequent_end: int | None,
    ) -> bool:
        """Determine if two line ranges overlap."""
        if target_start is None or target_end is None:
            # If target has no line range, it modified the entire file, causing overlap with any edit
            return True
        if subsequent_start is None or subsequent_end is None:
            return True
        # Range overlap condition: not (end1 < start2 or start1 > end2)
        return not (target_end < subsequent_start or target_start > subsequent_end)

    def rollback_node(self, node_id: str) -> RollbackResult:
        """Atomically revert the changes made by a single agent node."""
        with self._lock:
            target_node = self.journal.get_node(node_id)
            if not target_node:
                return RollbackResult(
                    node_id=node_id,
                    status=RollbackStatus.NODE_NOT_FOUND,
                    file_path="",
                    conflict_reason=f"Timeline node {node_id} does not exist.",
                )

            if target_node.is_rolled_back:
                return RollbackResult(
                    node_id=node_id,
                    status=RollbackStatus.ALREADY_ROLLED_BACK,
                    file_path=target_node.file_path,
                    conflict_reason=f"Node {node_id} has already been reverted.",
                )

            file_path = target_node.file_path
            file_history = self.journal.get_file_history(file_path)

            # Locate position of target node in file history
            try:
                target_idx = [n.node_id for n in file_history].index(node_id)
            except ValueError:
                target_idx = -1

            subsequent_nodes = file_history[target_idx + 1 :] if target_idx >= 0 else []

            # Check if any active subsequent edit conflicts with target's line range
            for sub_node in subsequent_nodes:
                if sub_node.is_rolled_back:
                    continue

                if self._check_overlap(
                    target_node.line_start,
                    target_node.line_end,
                    sub_node.line_start,
                    sub_node.line_end,
                ):
                    reason = (
                        f"Cannot cherry-pick revert node {node_id}: subsequent active mutation "
                        f"{sub_node.node_id} by {sub_node.actor_name} modified overlapping lines."
                    )
                    logger.warning(reason)
                    return RollbackResult(
                        node_id=node_id,
                        status=RollbackStatus.CONFLICT_DETECTED,
                        file_path=file_path,
                        conflict_reason=reason,
                    )

            # Apply reverse patch:
            # If target was the latest change, restoring is simply putting before_content.
            # If intermediate and non-overlapping, replace target's after_content with before_content.
            current_content = self.get_file_content(file_path)
            if not current_content:
                restored_content = target_node.before_content
            elif target_node.after_content in current_content:
                restored_content = current_content.replace(
                    target_node.after_content,
                    target_node.before_content,
                    1,
                )
            else:
                restored_content = target_node.before_content

            self.set_file_content(file_path, restored_content)
            target_node.is_rolled_back = True

            # Record a compensatory rollback node into the journal
            rollback_record_node = TimelineNode(
                node_id=f"revert-{node_id}-{int(time.time() * 1000) % 10000}",
                session_id=target_node.session_id,
                actor_id="system-rollback-engine",
                actor_name="Surgical Rollback Engine",
                actor_type=target_node.actor_type,
                operation_type=target_node.operation_type,
                file_path=file_path,
                line_start=target_node.line_start,
                line_end=target_node.line_end,
                before_content=target_node.after_content,
                after_content=target_node.before_content,
                diff_summary=f"Reverted node {node_id} ({target_node.diff_summary})",
                parent_node_id=node_id,
                is_rolled_back=False,
            )
            self.journal.record_node(rollback_record_node)

            logger.info("Successfully cherry-picked and rolled back node %s on %s", node_id, file_path)
            return RollbackResult(
                node_id=node_id,
                status=RollbackStatus.SUCCESS,
                file_path=file_path,
                restored_content=restored_content,
            )
