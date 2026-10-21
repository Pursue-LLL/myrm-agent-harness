"""File activity observer — records write activities to the FileActivityTracker.

Runs after each successful file write/create, recording the agent ID and
affected line range so subsequent writes by other agents can detect conflicts.

[INPUT]
- .base::FileOperationObserver (POS: Observer base class)
- core.file_activity_tracker::get_file_activity_tracker (POS: File activity tracker singleton)
- agent.middlewares._session_context::get_subagent_task_id, get_is_subagent (POS: ContextVar for subagent identity)

[OUTPUT]
- FileActivityObserver: Observer that records file write activities

[POS]
File activity observer. Records file write activities (agent ID, path, line
range) to the FileActivityTracker after each successful write operation.
Only active when running inside a subagent context.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.agent.meta_tools.file_ops.core.file_activity_tracker import get_file_activity_tracker
from myrm_agent_harness.agent.middlewares._session_context import get_is_subagent, get_subagent_task_id

from .base import FileOperationObserver

logger = logging.getLogger(__name__)

_DEFAULT_AGENT_ID = "__main__"


class FileActivityObserver(FileOperationObserver):
    """Records file write activities to the FileActivityTracker.

    Only records when running inside a subagent context. For single-agent
    operation, this observer is a no-op (zero overhead).
    """

    async def on_file_created(self, path: str, content: str) -> None:
        if not get_is_subagent():
            return
        agent_id = get_subagent_task_id() or _DEFAULT_AGENT_ID
        total_lines = content.count("\n") + 1
        tracker = get_file_activity_tracker()
        tracker.record_write(agent_id, path, 1, total_lines)

    async def on_file_modified(self, path: str, old_content: str, new_content: str) -> None:
        if not get_is_subagent():
            return
        agent_id = get_subagent_task_id() or _DEFAULT_AGENT_ID
        tracker = get_file_activity_tracker()

        line_start, line_end = _diff_line_range(old_content, new_content)
        tracker.record_write(agent_id, path, line_start, line_end)

    async def on_file_viewed(self, path: str) -> None:
        pass


def _diff_line_range(old: str, new: str) -> tuple[int, int]:
    """Compute the line range that changed between old and new content.

    Returns (start_line, end_line) 1-indexed. Uses a simple prefix/suffix
    match to find the changed region efficiently.
    """
    old_lines = old.split("\n")
    new_lines = new.split("\n")

    # Find common prefix length
    prefix = 0
    min_len = min(len(old_lines), len(new_lines))
    while prefix < min_len and old_lines[prefix] == new_lines[prefix]:
        prefix += 1

    # Find common suffix length
    suffix = 0
    while suffix < (min_len - prefix) and old_lines[-(suffix + 1)] == new_lines[-(suffix + 1)]:
        suffix += 1

    start = prefix + 1  # 1-indexed
    end_old = len(old_lines) - suffix
    end_new = len(new_lines) - suffix
    end = max(end_old, end_new, start)

    return start, end
