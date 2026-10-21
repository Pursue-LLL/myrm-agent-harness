"""Consistent single-file snapshots of live SQLite databases.

[INPUT]
- infra.sqlite_backup::hot_copy_database (POS: online page-wise backup)

[OUTPUT]
- snapshot_sqlite: Write a consistent standalone image of a live database.
- is_sqlite_file: Header-based SQLite detector (extension-independent).

[POS]
Capture step of ``infra/state_archive``. ``compact=True`` uses ``VACUUM INTO`` so
free pages (which can still hold deleted rows) never reach the snapshot; the
default keeps the page layout byte-faithful via the online backup API.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from myrm_agent_harness.infra.sqlite_backup import hot_copy_database

_SQLITE_MAGIC = b"SQLite format 3\x00"
_VACUUM_INTO_MIN_VERSION = (3, 27, 0)


def is_sqlite_file(path: Path) -> bool:
    """Return True when the file starts with the SQLite 3 magic header."""
    try:
        with path.open("rb") as handle:
            return handle.read(len(_SQLITE_MAGIC)) == _SQLITE_MAGIC
    except OSError:
        return False


def snapshot_sqlite(src: Path, dst: Path, *, compact: bool = False) -> None:
    """Snapshot ``src`` into the not-yet-existing file ``dst``.

    The destination never has WAL/SHM siblings. Raises ``FileExistsError`` when
    ``dst`` already exists so callers cannot silently overwrite data.
    """
    if dst.exists():
        raise FileExistsError(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if compact and sqlite3.sqlite_version_info >= _VACUUM_INTO_MIN_VERSION:
        conn = sqlite3.connect(str(src), timeout=10.0)
        try:
            conn.execute("VACUUM INTO ?", (str(dst),))
        finally:
            conn.close()
        return
    hot_copy_database(src, dst)
