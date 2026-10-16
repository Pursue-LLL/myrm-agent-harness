"""Requeue the wiki sources a dead process left half-compiled.

[INPUT]
- sqlite3 (POS: connection type of the queue database)
- pathlib::Path (POS: queue database location)

[OUTPUT]
- requeue_orphaned_processing: on a database's first open in this process, return its ``processing`` rows to ``pending``

[POS]
Only the worker of the process that owns a vault marks sources ``processing``. A row still marked so when this
process first opens the database was left by a process that died: nothing works on it, yet it keeps the page on
"compiling" and blocks maintenance (the 300 s stale reset frees only older rows). The archiver's background worker
compiles requeued rows like any pending row. Later opens of the same database in this process (a new archiver after
a model switch) leave them alone, they belong to the live worker. One process per vault, as in kanban boot recovery.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

logger = logging.getLogger(__name__)

# Databases this process has opened. ``setdefault`` is atomic, so exactly one of several threads opening the
# same database at once sees its own token and runs the sweep.
_OPENED_DATABASES: dict[str, object] = {}


def requeue_orphaned_processing(
    db_path: Path, get_conn: Callable[[], AbstractContextManager[sqlite3.Connection]]
) -> int:
    """Return ``processing`` rows to ``pending`` on the first open of ``db_path`` in this process.

    Returns:
        How many rows were requeued; 0 on every later open.
    """
    key = str(db_path.resolve())
    token = object()
    if _OPENED_DATABASES.setdefault(key, token) is not token:
        return 0
    try:
        with get_conn() as conn:
            requeued = conn.execute(
                "UPDATE ingestion_queue SET status = 'pending', updated_at = CURRENT_TIMESTAMP "
                "WHERE status = 'processing'"
            ).rowcount
    except Exception:
        # A sweep that failed leaves the database unswept: the next open has to try again.
        _OPENED_DATABASES.pop(key, None)
        raise
    if requeued:
        logger.warning("Requeued %d wiki source(s) a previous process left half-compiled in %s", requeued, db_path)
    return int(requeued)
