"""File edit conflict guard helpers.

[INPUT]
- agent.middlewares._session_context::get_is_subagent, get_subagent_task_id (POS: ContextVar for subagent identity)
- core.file_activity_tracker::get_file_activity_tracker (POS: 文件活动跟踪器,行级冲突检测)

[OUTPUT]
- compute_edit_line_range: affected line range calculator.
- check_conflict_pre_write: pre-write conflict guard.

[POS]
File edit conflict guard. Calculates edit ranges and blocks overlapping concurrent subagent edits.
"""

import logging

from myrm_agent_harness.agent.middlewares._session_context import (
    get_is_subagent,
    get_subagent_task_id,
)

from .file_activity_tracker import get_file_activity_tracker

logger = logging.getLogger(__name__)


def compute_edit_line_range(content: str, old_str: str) -> tuple[int, int]:
    """Compute the 1-indexed line range affected by a str_replace operation."""
    idx = content.find(old_str)
    if idx < 0:
        total = content.count("\n") + 1
        return 1, total

    start_line = content[:idx].count("\n") + 1
    end_line = start_line + old_str.count("\n")
    return start_line, end_line


def check_conflict_pre_write(path: str, line_start: int, line_end: int) -> str | None:
    """Check for concurrent subagent file conflicts before writing."""
    if not get_is_subagent():
        return None

    agent_id = get_subagent_task_id() or "__main__"
    tracker = get_file_activity_tracker()
    conflict = tracker.check_conflict(agent_id, path, line_start, line_end)

    if conflict is None:
        return None

    message = conflict.to_message(path)

    if conflict.is_blocking:
        logger.warning("[subagent:%s] Blocking file conflict: %s", agent_id, message)
        raise ValueError(message)

    logger.info("[subagent:%s] Non-blocking file conflict: %s", agent_id, message)
    return message


__all__ = ["check_conflict_pre_write", "compute_edit_line_range"]
