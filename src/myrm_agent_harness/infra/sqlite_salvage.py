"""Non-destructive SQLite B-Tree page-skipping rowid salvage engine.

Recovers surviving records from corrupted SQLite databases where standard
dumping (`iterdump()`) or physical file backups fail due to page-level write
tears (`database disk image is malformed`).

[INPUT]
- source_path: Path to corrupted SQLite database.
- output_path: Path where the clean recovered database will be created.

[OUTPUT]
- SalvageResult: Structured execution summary with row counts, skipped corrupted
  ranges, reconstructed orphan sessions, FTS indexes rebuilt, and SHA-256 hashes.

[POS]
Harness infrastructure layer. Generic, technology-agnostic SQLite physical salvage
engine. Used by server-level lifecycle and disaster recovery operations.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_DEFAULT_CHUNK_SIZE = 500
_FTS_SHADOW_SUFFIXES = (
    "_data",
    "_idx",
    "_content",
    "_docsize",
    "_config",
    "_segments",
    "_segdir",
    "_stat",
)


@dataclass(frozen=True, slots=True)
class CorruptedRange:
    """Range of rowids that failed physical page verification."""

    low_rowid: int
    high_rowid: int
    error: str


@dataclass(slots=True)
class TableSalvageStats:
    """Salvage statistics for a single table."""

    table_name: str
    source_rows_estimate: int = 0
    recovered_rows: int = 0
    skipped_ranges: list[CorruptedRange] = field(default_factory=list)
    status: Literal["ok", "partial", "empty", "failed"] = "ok"
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SalvageResult:
    """Comprehensive disaster recovery summary."""

    source_path: str
    recovered_path: str
    success: bool
    total_recovered_rows: int
    table_stats: dict[str, TableSalvageStats]
    orphans_reconstructed: int
    fts_rebuilt: list[str]
    elapsed_ms: float
    source_sha256: str
    recovered_sha256: str
    error: str | None = None


class SQLiteRowidSalvageEngine:
    """Engine for non-destructive B-Tree page-skipping data recovery."""

    def __init__(
        self,
        *,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
        text_replace: bool = True,
    ) -> None:
        self._chunk_size = chunk_size
        self._text_replace = text_replace

    def inspect_database(self, db_path: Path | str) -> dict[str, str | int | bool]:
        """Inspects database integrity without writing to disk."""
        path = Path(db_path)
        if not path.exists():
            return {"exists": False, "readable": False, "quick_check": "missing"}

        sha = self._compute_sha256(path)
        result: dict[str, str | int | bool] = {
            "exists": True,
            "size_bytes": path.stat().st_size,
            "sha256": sha,
            "readable": False,
            "quick_check": "failed",
        }

        try:
            conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
            try:
                check = conn.execute("PRAGMA quick_check;").fetchone()
                result["quick_check"] = str(check[0]) if check else "unknown"
                result["readable"] = True
            finally:
                conn.close()
        except Exception as exc:
            result["quick_check"] = f"error: {exc}"

        return result

    def salvage_database(
        self,
        source_path: Path | str,
        output_path: Path | str,
        *,
        isolate_sandbox: bool = True,
    ) -> SalvageResult:
        """Recovers surviving records from source into a clean target database."""
        start_time = time.monotonic()
        src = Path(source_path).resolve()
        dst = Path(output_path).resolve()

        if not src.exists():
            return SalvageResult(
                source_path=str(src),
                recovered_path=str(dst),
                success=False,
                total_recovered_rows=0,
                table_stats={},
                orphans_reconstructed=0,
                fts_rebuilt=[],
                elapsed_ms=0.0,
                source_sha256="",
                recovered_sha256="",
                error=f"Source file does not exist: {src}",
            )

        src_sha256 = self._compute_sha256(src)

        if dst.exists():
            try:
                dst.unlink()
                self._cleanup_wal_files(dst)
            except OSError as exc:
                logger.warning("Failed to remove existing destination %s: %s", dst, exc)

        dst.parent.mkdir(parents=True, exist_ok=True)

        # Execute recovery inside sandbox or direct copy
        sandbox_dir: str | None = None
        try:
            if isolate_sandbox:
                sandbox_dir = tempfile.mkdtemp(prefix="sqlite_salvage_")
                working_src = Path(sandbox_dir) / src.name
                shutil.copy2(src, working_src)
                # Copy companion WAL/SHM files
                for suffix in ("-wal", "-shm"):
                    companion = src.with_name(f"{src.name}{suffix}")
                    if companion.exists():
                        shutil.copy2(
                            companion,
                            working_src.with_name(f"{working_src.name}{suffix}"),
                        )
            else:
                working_src = src

            return self._execute_salvage(
                working_src=working_src,
                output_path=dst,
                original_src_path=src,
                src_sha256=src_sha256,
                start_time=start_time,
            )
        finally:
            if sandbox_dir and os.path.exists(sandbox_dir):
                shutil.rmtree(sandbox_dir, ignore_errors=True)

    def _execute_salvage(
        self,
        working_src: Path,
        output_path: Path,
        original_src_path: Path,
        src_sha256: str,
        start_time: float,
    ) -> SalvageResult:
        table_stats: dict[str, TableSalvageStats] = {}
        fts_tables: list[str] = []
        total_recovered = 0
        orphans_reconstructed = 0

        # Read-only source connection with UTF-8 replacement factory
        source_uri = f"file:{working_src.resolve()}?mode=ro"
        try:
            source_conn = sqlite3.connect(source_uri, uri=True)
            if self._text_replace:
                source_conn.text_factory = lambda b: b.decode("utf-8", "replace")
        except sqlite3.Error as exc:
            return SalvageResult(
                source_path=str(original_src_path),
                recovered_path=str(output_path),
                success=False,
                total_recovered_rows=0,
                table_stats={},
                orphans_reconstructed=0,
                fts_rebuilt=[],
                elapsed_ms=(time.monotonic() - start_time) * 1000,
                source_sha256=src_sha256,
                recovered_sha256="",
                error=f"Cannot open source database in read-only mode: {exc}",
            )

        try:
            # Passive checkpoint on working copy to fold unharmed WAL frames
            with contextlib.suppress(sqlite3.Error):
                source_conn.execute("PRAGMA wal_checkpoint(PASSIVE);")

            # Extract user table definitions
            tables, virtual_tables = self._extract_schemas(source_conn)
            fts_tables.extend(virtual_tables.keys())

            # Open destination connection
            dest_conn = sqlite3.connect(str(output_path))
            try:
                dest_conn.execute("PRAGMA foreign_keys = OFF;")
                dest_conn.execute("PRAGMA journal_mode = WAL;")

                # Recreate schemas
                for tbl, ddl in tables.items():
                    if ddl:
                        try:
                            dest_conn.execute(ddl)
                        except sqlite3.Error as exc:
                            logger.warning(
                                "Failed to recreate schema for %s: %s", tbl, exc
                            )

                for vtbl, vddl in virtual_tables.items():
                    if vddl:
                        try:
                            dest_conn.execute(vddl)
                        except sqlite3.Error as exc:
                            logger.warning(
                                "Failed to recreate virtual table %s: %s", vtbl, exc
                            )

                # Salvage records table by table
                for table_name, ddl in tables.items():
                    stats = self._salvage_table(source_conn, dest_conn, table_name, ddl)
                    table_stats[table_name] = stats
                    total_recovered += stats.recovered_rows

                dest_conn.commit()

                # Reconstruct broken foreign key orphans (e.g. chats -> messages)
                orphans_reconstructed = self._reconstruct_orphans(dest_conn)
                dest_conn.commit()

                # Rebuild FTS virtual tables natively
                for vtbl in fts_tables:
                    try:
                        dest_conn.execute(
                            f'INSERT INTO "{vtbl}"("{vtbl}") VALUES(\'rebuild\');'
                        )
                    except sqlite3.Error as fts_exc:
                        logger.warning("FTS rebuild failed for %s: %s", vtbl, fts_exc)

                dest_conn.commit()
                dest_conn.execute("PRAGMA foreign_keys = ON;")
            finally:
                dest_conn.close()

            dst_sha256 = self._compute_sha256(output_path)
            return SalvageResult(
                source_path=str(original_src_path),
                recovered_path=str(output_path),
                success=True,
                total_recovered_rows=total_recovered,
                table_stats=table_stats,
                orphans_reconstructed=orphans_reconstructed,
                fts_rebuilt=fts_tables,
                elapsed_ms=(time.monotonic() - start_time) * 1000,
                source_sha256=src_sha256,
                recovered_sha256=dst_sha256,
            )
        except Exception as exc:
            logger.error("Salvage execution aborted: %s", exc)
            return SalvageResult(
                source_path=str(original_src_path),
                recovered_path=str(output_path),
                success=False,
                total_recovered_rows=total_recovered,
                table_stats=table_stats,
                orphans_reconstructed=orphans_reconstructed,
                fts_rebuilt=fts_tables,
                elapsed_ms=(time.monotonic() - start_time) * 1000,
                source_sha256=src_sha256,
                recovered_sha256="",
                error=str(exc),
            )
        finally:
            source_conn.close()

    def _extract_schemas(
        self, conn: sqlite3.Connection
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Extracts standard tables and virtual FTS tables, skipping internal shadow tables."""
        tables: dict[str, str] = {}
        virtual_tables: dict[str, str] = {}
        try:
            cursor = conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            )
            for row in cursor.fetchall():
                name: str = row[0]
                sql: str | None = row[1]
                if any(name.endswith(suffix) for suffix in _FTS_SHADOW_SUFFIXES):
                    continue
                if sql and "VIRTUAL" in sql.upper():
                    virtual_tables[name] = sql
                elif sql:
                    tables[name] = sql
        except sqlite3.Error as exc:
            logger.warning("Error reading sqlite_master: %s", exc)
        return tables, virtual_tables

    def _salvage_table(
        self,
        source: sqlite3.Connection,
        dest: sqlite3.Connection,
        table: str,
        ddl: str = "",
    ) -> TableSalvageStats:
        """Performs chunked bisection rowid salvage on a single table."""
        stats = TableSalvageStats(table_name=table)
        cols = self._get_column_names(dest, table)
        if not cols:
            stats.status = "failed"
            stats.error = "No columns found in destination schema"
            return stats

        col_identifiers = ", ".join(f'"{c}"' for c in cols)
        placeholders = ", ".join("?" for _ in cols)
        insert_sql = f'INSERT OR REPLACE INTO "{table}" ({col_identifiers}) VALUES ({placeholders});'

        try:
            # Detect rowid support deterministically from DDL or query
            has_rowid = "WITHOUT ROWID" not in ddl.upper()
            if has_rowid:
                try:
                    source.execute(f'SELECT rowid FROM "{table}" LIMIT 1;')
                except sqlite3.OperationalError:
                    has_rowid = False
                except sqlite3.DatabaseError:
                    pass

            if not has_rowid:
                # Fallback for WITHOUT ROWID tables
                return self._salvage_without_rowid(
                    source, dest, table, insert_sql, cols, stats
                )

            # Determine rowid boundaries
            min_id, max_id = self._probe_rowid_bounds(source, table)
            if min_id is None or max_id is None:
                stats.status = "empty"
                return stats

            stats.source_rows_estimate = max_id - min_id + 1
            cur_id = min_id

            while cur_id <= max_id:
                chunk_end = min(cur_id + self._chunk_size - 1, max_id)
                try:
                    query = (
                        f'SELECT {col_identifiers} FROM "{table}" '
                        f"WHERE rowid BETWEEN ? AND ? ORDER BY rowid ASC;"
                    )
                    rows = source.execute(query, (cur_id, chunk_end)).fetchall()
                    if rows:
                        dest.executemany(insert_sql, rows)
                        stats.recovered_rows += len(rows)
                except sqlite3.DatabaseError:
                    # Corrupted B-Tree page encountered: bisect this chunk
                    self._bisect_range(
                        source=source,
                        dest=dest,
                        table=table,
                        insert_sql=insert_sql,
                        col_identifiers=col_identifiers,
                        low=cur_id,
                        high=chunk_end,
                        stats=stats,
                    )
                cur_id = chunk_end + 1

            if (
                stats.recovered_rows < stats.source_rows_estimate
                and not stats.skipped_ranges
            ):
                stats.skipped_ranges.append(
                    CorruptedRange(
                        low_rowid=min_id,
                        high_rowid=max_id,
                        error=f"{stats.source_rows_estimate - stats.recovered_rows} rows missing or damaged in page gap",
                    )
                )

            if stats.skipped_ranges or (
                stats.source_rows_estimate > 0
                and stats.recovered_rows < stats.source_rows_estimate
            ):
                stats.status = "partial"
        except Exception as exc:
            logger.warning("Table salvage encountered error for %s: %s", table, exc)
            stats.status = "failed"
            stats.error = str(exc)

        return stats

    def _bisect_range(
        self,
        source: sqlite3.Connection,
        dest: sqlite3.Connection,
        table: str,
        insert_sql: str,
        col_identifiers: str,
        low: int,
        high: int,
        stats: TableSalvageStats,
    ) -> None:
        """Recursively bisects a corrupted rowid interval to rescue undamaged rows."""
        if low > high:
            return

        if low == high:
            try:
                query = f'SELECT {col_identifiers} FROM "{table}" WHERE rowid = ?;'
                row = source.execute(query, (low,)).fetchone()
                if row is not None:
                    dest.execute(insert_sql, row)
                    stats.recovered_rows += 1
            except sqlite3.DatabaseError as exc:
                stats.skipped_ranges.append(
                    CorruptedRange(low_rowid=low, high_rowid=high, error=str(exc))
                )
            return

        mid = (low + high) // 2
        # Probe left sub-interval
        try:
            query = (
                f'SELECT {col_identifiers} FROM "{table}" '
                f"WHERE rowid BETWEEN ? AND ? ORDER BY rowid ASC;"
            )
            left_rows = source.execute(query, (low, mid)).fetchall()
            if left_rows:
                dest.executemany(insert_sql, left_rows)
                stats.recovered_rows += len(left_rows)
        except sqlite3.DatabaseError:
            self._bisect_range(
                source, dest, table, insert_sql, col_identifiers, low, mid, stats
            )

        # Probe right sub-interval
        try:
            query = (
                f'SELECT {col_identifiers} FROM "{table}" '
                f"WHERE rowid BETWEEN ? AND ? ORDER BY rowid ASC;"
            )
            right_rows = source.execute(query, (mid + 1, high)).fetchall()
            if right_rows:
                dest.executemany(insert_sql, right_rows)
                stats.recovered_rows += len(right_rows)
        except sqlite3.DatabaseError:
            self._bisect_range(
                source, dest, table, insert_sql, col_identifiers, mid + 1, high, stats
            )

    def _salvage_without_rowid(
        self,
        source: sqlite3.Connection,
        dest: sqlite3.Connection,
        table: str,
        insert_sql: str,
        cols: list[str],
        stats: TableSalvageStats,
    ) -> TableSalvageStats:
        """Best-effort scan for WITHOUT ROWID tables."""
        col_identifiers = ", ".join(f'"{c}"' for c in cols)
        try:
            cursor = source.execute(f'SELECT {col_identifiers} FROM "{table}";')
            while True:
                try:
                    row = cursor.fetchone()
                    if row is None:
                        break
                    dest.execute(insert_sql, row)
                    stats.recovered_rows += 1
                except sqlite3.DatabaseError as exc:
                    stats.skipped_ranges.append(
                        CorruptedRange(0, 0, f"Row error: {exc}")
                    )
                    break
        except sqlite3.DatabaseError as exc:
            stats.status = "failed"
            stats.error = str(exc)
        return stats

    def _probe_rowid_bounds(
        self, conn: sqlite3.Connection, table: str
    ) -> tuple[int | None, int | None]:
        """Probes minimum and maximum accessible rowids."""
        min_id: int | None = None
        max_id: int | None = None
        try:
            row_min = conn.execute(
                f'SELECT rowid FROM "{table}" ORDER BY rowid ASC LIMIT 1;'
            ).fetchone()
            if row_min is not None:
                min_id = int(row_min[0])
        except sqlite3.DatabaseError:
            pass
        try:
            row_max = conn.execute(
                f'SELECT rowid FROM "{table}" ORDER BY rowid DESC LIMIT 1;'
            ).fetchone()
            if row_max is not None:
                max_id = int(row_max[0])
        except sqlite3.DatabaseError:
            pass

        if min_id is None and max_id is not None:
            min_id = 1
        elif min_id is not None and max_id is None:
            max_id = min_id + 10000

        return min_id, max_id

    def _reconstruct_orphans(self, conn: sqlite3.Connection) -> int:
        """Synthesizes parent stub records for orphaned child messages."""
        reconstructed = 0
        try:
            # Check for chat session relationships: chats(id) <- messages(chat_id)
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            }
            if "chats" in tables and "messages" in tables:
                orphan_query = (
                    'SELECT DISTINCT m.chat_id, MIN(m.created_at) FROM "messages" m '
                    'LEFT JOIN "chats" c ON m.chat_id = c.id '
                    "WHERE c.id IS NULL AND m.chat_id IS NOT NULL "
                    "GROUP BY m.chat_id;"
                )
                orphans = conn.execute(orphan_query).fetchall()
                for chat_id, earliest_time in orphans:
                    chat_cols = self._get_column_names(conn, "chats")
                    ts = earliest_time or time.strftime("%Y-%m-%d %H:%M:%S")
                    stub_data: dict[str, object] = {
                        "id": str(chat_id),
                        "title": f"[Recovered Session] {chat_id[:8]}",
                        "created_at": ts,
                        "updated_at": ts,
                        "action_mode": "fast",
                        "source": "recovered",
                        "total_calls": 0,
                        "total_tokens": 0,
                        "total_usd": 0.0,
                    }
                    valid_cols = [c for c in chat_cols if c in stub_data]
                    placeholders = ", ".join("?" for _ in valid_cols)
                    col_str = ", ".join(f'"{c}"' for c in valid_cols)
                    conn.execute(
                        f'INSERT OR IGNORE INTO "chats" ({col_str}) VALUES ({placeholders});',
                        [stub_data[c] for c in valid_cols],
                    )
                    reconstructed += 1
        except sqlite3.Error as exc:
            logger.warning("Orphan reconstruction skipped: %s", exc)
        return reconstructed

    def _get_column_names(self, conn: sqlite3.Connection, table: str) -> list[str]:
        """Returns column names for a given table."""
        try:
            cursor = conn.execute(f'PRAGMA table_info("{table}");')
            return [str(row[1]) for row in cursor.fetchall()]
        except sqlite3.Error:
            return []

    def _compute_sha256(self, path: Path) -> str:
        """Computes SHA-256 digest of a file in chunks."""
        hasher = hashlib.sha256()
        try:
            with open(path, "rb") as fp:
                while chunk := fp.read(65536):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except OSError:
            return ""

    def _cleanup_wal_files(self, db_path: Path) -> None:
        """Removes companion WAL and SHM files."""
        for suffix in ("-wal", "-shm"):
            companion = db_path.with_name(f"{db_path.name}{suffix}")
            if companion.exists():
                with contextlib.suppress(OSError):
                    companion.unlink()
