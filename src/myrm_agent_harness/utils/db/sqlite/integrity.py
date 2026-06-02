"""SQLite integrity & crash-recovery primitives (file-level, connection-agnostic).

These guards detect torn writes / truncation / corruption early and clean up
orphaned WAL companions left by an unclean shutdown — the foundation of the
"power-loss survival guard" across local / Tauri / sandbox deployments.

[INPUT]
- pathlib.Path (POS: target SQLite database file)
- sqlite3.Connection / aiosqlite.Connection (POS: open connection for checkpoint/quick_check)

[OUTPUT]
- SQLiteIntegrityError: raised when a corruption/truncation invariant is violated
- validate_sqlite_header / check_page_count_invariant / cleanup_orphan_wal: file-level guards
- quick_check_sync: bounded corruption canary
- checkpoint_truncate_sync / checkpoint_truncate_async: WAL flush helpers

[POS]
Leaf integrity module for the unified SQLite hardening factory. No dependency on
profile/connection setup, so it is safe to import from any store.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

_SQLITE_MAGIC = b"SQLite format 3\x00"
_HEADER_SIZE = 100
_PAGE_SIZE_OFFSET = 16
_PAGE_COUNT_OFFSET = 28


class SQLiteIntegrityError(Exception):
    """Raised when a SQLite file violates a corruption/truncation invariant."""


def validate_sqlite_header(path: Path) -> None:
    """Reject non-SQLite / wrong-format files before opening a connection.

    An empty or absent file is allowed (a fresh DB will be created). A non-empty
    file that lacks the SQLite magic string is a misplaced/garbage file and must
    not be silently opened as a database.
    """
    try:
        if not path.exists() or path.stat().st_size == 0:
            return
        with path.open("rb") as handle:
            head = handle.read(len(_SQLITE_MAGIC))
    except OSError:
        return  # cannot inspect; defer to the connection attempt
    if not head.startswith(_SQLITE_MAGIC):
        raise SQLiteIntegrityError(
            f"file is not a SQLite database (invalid header): {path}"
        )


def check_page_count_invariant(path: Path) -> None:
    """Detect torn-write truncation: the file must not be shorter than its header claims.

    The SQLite header records page size (bytes 16-17) and page count (bytes 28-31).
    A physical file shorter than ``page_count * page_size`` means pages were lost to
    a truncated/torn write. This is a one-directional check: a stale (too-low) header
    count never triggers a false positive — only genuine truncation does.
    """
    try:
        if not path.exists():
            return
        size = path.stat().st_size
        if size < _HEADER_SIZE:
            return  # too small to host a valid header; nothing to assert
        with path.open("rb") as handle:
            header = handle.read(_HEADER_SIZE)
    except OSError:
        return
    if not header.startswith(_SQLITE_MAGIC):
        return  # header validity is asserted separately

    page_size = int.from_bytes(header[_PAGE_SIZE_OFFSET : _PAGE_SIZE_OFFSET + 2], "big")
    if page_size == 1:
        page_size = 65536  # SQLite encodes a 64 KiB page size as the value 1
    page_count = int.from_bytes(
        header[_PAGE_COUNT_OFFSET : _PAGE_COUNT_OFFSET + 4], "big"
    )
    if page_size == 0 or page_count == 0:
        return  # legacy header that does not maintain an in-file page count

    expected = page_size * page_count
    if size < expected:
        missing = (expected - size + page_size - 1) // page_size
        raise SQLiteIntegrityError(
            f"SQLite file truncated: {path} header claims {page_count} pages "
            f"({expected} bytes) but file is {size} bytes (~{missing} pages missing)"
        )


def cleanup_orphan_wal(path: Path) -> None:
    """Remove orphaned WAL/SHM companions left when the main DB is empty.

    A zero-byte main database alongside a ``-wal``/``-shm`` companion is the
    signature of an unclean shutdown that never checkpointed. Deleting the
    companions lets SQLite start cleanly instead of failing to open.
    """
    try:
        if not path.exists() or path.stat().st_size != 0:
            return
    except OSError:
        return
    for suffix in ("-wal", "-shm"):
        companion = Path(f"{path}{suffix}")
        try:
            if companion.exists():
                companion.unlink()
                logger.warning("Removed orphaned SQLite companion: %s", companion)
        except OSError as exc:
            logger.warning("Failed to remove orphaned companion %s: %s", companion, exc)


def prepare_database_file(path: Path, *, validate: bool = True) -> None:
    """Pre-open crash-recovery + corruption guard for a durability-critical store.

    Cleans up orphaned WAL companions, then (when ``validate``) asserts the file is
    a real SQLite database and has not been torn-write truncated. Raises
    :class:`SQLiteIntegrityError` so the caller can route to a recovery/reset flow.
    """
    cleanup_orphan_wal(path)
    if validate:
        validate_sqlite_header(path)
        check_page_count_invariant(path)


def on_disk_journal_mode_is_wal(path: Path) -> bool:
    """Return True if the on-disk header indicates the DB is already in WAL mode.

    SQLite header bytes 18 (write version) and 19 (read version) equal 2 for WAL.
    Used to refuse a WAL->DELETE downgrade on a transient error when the database
    is provably already a WAL database.
    """
    try:
        if not path.exists() or path.stat().st_size < 20:
            return False
        with path.open("rb") as handle:
            header = handle.read(20)
    except OSError:
        return False
    if not header.startswith(_SQLITE_MAGIC):
        return False
    return header[18] == 2 and header[19] == 2


def _is_quick_check_ok(rows: list[tuple[object, ...]]) -> bool:
    return len(rows) == 1 and str(rows[0][0]).lower() == "ok"


def quick_check_sync(conn: sqlite3.Connection, *, max_errors: int = 1) -> None:
    """Run a bounded ``quick_check`` canary; raise on corruption.

    ``quick_check(N)`` is far cheaper than ``integrity_check`` on large databases
    because it skips index/content cross-checks and stops after ``N`` problems.
    """
    rows = conn.execute(f"PRAGMA quick_check({max_errors})").fetchall()
    if not _is_quick_check_ok(rows):
        raise SQLiteIntegrityError(f"quick_check failed: {rows}")


def checkpoint_truncate_sync(conn: sqlite3.Connection) -> None:
    """Flush the WAL into the main database and truncate it (best effort)."""
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as exc:
        logger.debug("WAL checkpoint (sync) skipped: %s", exc)


async def checkpoint_truncate_async(conn: aiosqlite.Connection) -> None:
    """Async flush the WAL into the main database and truncate it (best effort)."""
    try:
        await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error as exc:
        logger.debug("WAL checkpoint (async) skipped: %s", exc)
