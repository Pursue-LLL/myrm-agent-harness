"""Context cleanup entrypoints.

[INPUT]
- runtime.context.cleanup::CONTEXT_RETENTION_DAYS, cleanup_context_files_async, cleanup_context_files_local (POS: Context file cleanup with a single retention window.)
- runtime.context.instance_metrics::record_cleanup (POS: Context operation metrics for monitoring and observability.)
- runtime.paths.execution_paths::* (POS: stable context archive paths)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)

[OUTPUT]
- cleanup_session_context_files: remove all context files for one session.
- cleanup_orphan_context_files_async: async orphan cleanup that honours recorded reads.
- cleanup_orphan_context_files: local synchronous orphan cleanup by modification time.

[POS]
Runtime context cleanup operations. Owns session directory cleanup and orphan cleanup entrypoints.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from myrm_agent_harness.runtime.context.cleanup import (
    CONTEXT_RETENTION_DAYS,
    cleanup_context_files_async,
    cleanup_context_files_local,
)
from myrm_agent_harness.runtime.context.instance_metrics import record_cleanup
from myrm_agent_harness.runtime.paths.execution_paths import (
    get_context_root,
    get_context_session_dir,
    get_workspace_relative_path,
    sanitize_path_segment,
)

if TYPE_CHECKING:
    from myrm_agent_harness.runtime.context.file_access_tracker import FileAccessTracker
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)


async def cleanup_session_context_files(chat_id: str, executor: CodeExecutor) -> None:
    """Clean up context offload files for a specific session."""
    if not chat_id:
        logger.warning("cleanup_session_context_files: chat_id is empty, skip")
        return

    context_root = get_context_root()
    if not os.path.isdir(context_root):
        return

    session_abs_path = get_context_session_dir(chat_id)

    if not os.path.isdir(session_abs_path):
        return

    session_rel_path = get_workspace_relative_path(session_abs_path)
    cleanup_script = f"""python - <<'PY'
from pathlib import Path
import shutil

root = Path({context_root!r}).resolve()
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
            sanitize_path_segment(chat_id),
            session_rel_path,
        )
        record_cleanup("session", 1)

    except Exception as exc:
        logger.warning("Failed to cleanup session context %s: %s", session_rel_path, exc)


async def cleanup_orphan_context_files_async(
    retention_days: int = CONTEXT_RETENTION_DAYS,
    access_tracker: FileAccessTracker | None = None,
) -> int:
    """Clean up context files nothing has read or written for ``retention_days``."""
    try:
        cleaned_count = await cleanup_context_files_async(retention_days=retention_days, access_tracker=access_tracker)
        if cleaned_count > 0:
            logger.info("Orphan cleanup completed: cleaned %d files (retention=%dd)", cleaned_count, retention_days)
            record_cleanup("orphan", cleaned_count)
        return cleaned_count
    except Exception as exc:
        logger.warning("Orphan cleanup failed: %s", exc)
        return 0


def cleanup_orphan_context_files(retention_days: int = CONTEXT_RETENTION_DAYS) -> int:
    """Clean up context files not modified for ``retention_days``, using the local filesystem only."""
    try:
        cleaned_count = cleanup_context_files_local(retention_days)
        if cleaned_count > 0:
            logger.info("Orphan cleanup completed: cleaned %d files older than %d days", cleaned_count, retention_days)
            record_cleanup("orphan", cleaned_count)
        return cleaned_count
    except Exception as exc:
        logger.warning("Orphan cleanup failed: %s", exc)
        return 0
