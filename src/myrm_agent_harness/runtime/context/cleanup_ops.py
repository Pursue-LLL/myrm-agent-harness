"""Context cleanup entrypoints.

[INPUT]
- runtime.context.cleanup::cleanup_context_files_async (POS: Context file cleanup with session-aware strategy.)
- runtime.context.instance_metrics::record_cleanup (POS: Context operation metrics for monitoring and observability.)
- runtime.execution_paths::* (POS: stable context archive paths)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)

[OUTPUT]
- cleanup_session_context_files: remove all context files for one session.
- cleanup_orphan_context_files_async: session-aware async orphan cleanup.
- cleanup_orphan_context_files: local synchronous orphan cleanup.

[POS]
Runtime context cleanup operations. Owns session directory cleanup and orphan cleanup entrypoints.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from myrm_agent_harness.runtime.context.cleanup import (
    cleanup_context_files_async,
    cleanup_context_files_local,
)
from myrm_agent_harness.runtime.context.instance_metrics import record_cleanup
from myrm_agent_harness.runtime.execution_paths import (
    CONTEXT_ROOT,
    _sanitize_path_segment,
    get_context_session_dir,
    get_workspace_relative_path,
)

if TYPE_CHECKING:
    from myrm_agent_harness.runtime.checkpoint_protocol import CheckpointerProtocol
    from myrm_agent_harness.runtime.context.file_access_tracker import FileAccessTracker
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)

ORPHAN_CLEANUP_THRESHOLD_DAYS = 7


async def cleanup_session_context_files(chat_id: str, executor: CodeExecutor) -> None:
    """Clean up context offload files for a specific session."""
    if not chat_id:
        logger.warning("cleanup_session_context_files: chat_id is empty, skip")
        return

    if not os.path.isdir(CONTEXT_ROOT):
        return

    session_abs_path = get_context_session_dir(chat_id)

    if not os.path.isdir(session_abs_path):
        return

    session_rel_path = get_workspace_relative_path(session_abs_path)
    cleanup_script = f"""python - <<'PY'
from pathlib import Path
import shutil

root = Path({CONTEXT_ROOT!r}).resolve()
target = Path({session_abs_path!r}).resolve()
if target == root or root not in target.parents:
    raise SystemExit("refusing to remove path outside context root")
if target.exists():
    shutil.rmtree(target)
PY"""

    try:
        from myrm_agent_harness.toolkits.code_execution.executors.base import ExecutionContext

        context = ExecutionContext(
            code=cleanup_script,
            session_id=chat_id,
            work_dir=executor.workspace_path,
            workspace_root=executor.workspace_path,
        )
        await executor.execute_bash(context)
        try:
            from myrm_agent_harness.runtime.context.file_access_tracker import (
                get_file_access_tracker,
            )

            tracker = await get_file_access_tracker()
            await tracker.delete_session_records(chat_id)
        except Exception as exc:
            logger.debug(
                "Failed to delete context access records for %s: %s",
                session_rel_path,
                exc,
            )
        logger.info(
            "CONTEXT_CLEANUP session=%s path=%s",
            _sanitize_path_segment(chat_id),
            session_rel_path,
        )
        record_cleanup("session", 1)

    except Exception as exc:
        logger.warning("Failed to cleanup session context %s: %s", session_rel_path, exc)


async def cleanup_orphan_context_files_async(
    max_age_days: int = ORPHAN_CLEANUP_THRESHOLD_DAYS,
    session_active_days: int = 30,
    file_access_days: int = 14,
    checkpointer: CheckpointerProtocol | None = None,
    access_tracker: FileAccessTracker | None = None,
) -> int:
    """Clean up expired orphan context files with the session-aware strategy."""
    try:
        cleaned_count = await cleanup_context_files_async(
            max_age_days=max_age_days,
            session_active_days=session_active_days,
            file_access_days=file_access_days,
            checkpointer=checkpointer,
            access_tracker=access_tracker,
        )
        if cleaned_count > 0:
            logger.info(
                "Orphan cleanup completed: cleaned %d files (strategy: session-aware, "
                "session_active=%dd, file_access=%dd, fallback=%dd)",
                cleaned_count,
                session_active_days,
                file_access_days,
                max_age_days,
            )
            record_cleanup("orphan", cleaned_count)
        return cleaned_count
    except Exception as exc:
        logger.warning("Orphan cleanup failed: %s", exc)
        return 0


def cleanup_orphan_context_files(max_age_days: int = ORPHAN_CLEANUP_THRESHOLD_DAYS) -> int:
    """Clean up expired orphan context files using local filesystem mtime."""
    try:
        cleaned_count = cleanup_context_files_local(max_age_days)
        if cleaned_count > 0:
            logger.info("Orphan cleanup completed: cleaned %d files older than %d days", cleaned_count, max_age_days)
            record_cleanup("orphan", cleaned_count)
        return cleaned_count
    except Exception as exc:
        logger.warning("Orphan cleanup failed: %s", exc)
        return 0
