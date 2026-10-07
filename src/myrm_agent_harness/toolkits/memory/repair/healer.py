"""[POS]: src/myrm_agent_harness/toolkits/memory/repair/healer.py
[INPUT]: SQLite connection and detected integrity diagnostics.
[OUTPUT]: Self-healing restoration engine producing RepairReport.
"""

import sqlite3
import time

from .models import IntegrityCheckReport, RepairActionStatus, RepairReport


class DatabaseAutoHealer:
    """Self-healing restoration engine for SQLite database corruption and stale index drift."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def heal(self, report: IntegrityCheckReport | None = None) -> RepairReport:
        """Attempt safe self-healing actions on the database."""
        start_time = time.perf_counter()
        repaired_items: list[str] = []
        error_details: list[str] = []
        cursor = self._conn.cursor()

        # 1. Rebuild standard indexes via REINDEX
        try:
            cursor.execute("REINDEX")
            repaired_items.append("REINDEX standard indexes completed")
        except sqlite3.DatabaseError as exc:
            error_details.append(f"REINDEX failed: {exc}")

        # 2. Rebuild FTS tables if present
        try:
            cursor.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            tables = cursor.fetchall()
            for name_val, sql_val in tables:
                tbl_name = str(name_val)
                sql_def = str(sql_val) if sql_val else ""
                if "fts5" in sql_def.lower():
                    try:
                        cursor.execute(f"INSERT INTO \"{tbl_name}\"(\"{tbl_name}\") VALUES('rebuild')")
                        repaired_items.append(f"FTS5 rebuild on table '{tbl_name}'")
                    except sqlite3.DatabaseError as fts_exc:
                        error_details.append(f"FTS5 rebuild failed on '{tbl_name}': {fts_exc}")
        except sqlite3.DatabaseError as schema_exc:
            error_details.append(f"Schema inspection for FTS rebuild failed: {schema_exc}")

        # 3. Commit rebuilt index changes before checkpointing
        try:
            self._conn.commit()
        except sqlite3.DatabaseError as commit_exc:
            error_details.append(f"Commit after index rebuild failed: {commit_exc}")

        # 4. WAL Checkpoint TRUNCATE to flush log frames safely
        try:
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            repaired_items.append("PRAGMA wal_checkpoint(TRUNCATE) flushed")
        except sqlite3.DatabaseError as wal_exc:
            error_details.append(f"WAL checkpoint failed: {wal_exc}")

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        if error_details and not repaired_items:
            status = RepairActionStatus.FAILED
        elif error_details:
            status = RepairActionStatus.PARTIAL
        else:
            status = RepairActionStatus.SUCCESS

        return RepairReport(
            status=status,
            repaired_items=repaired_items,
            error_details=error_details,
            duration_ms=round(duration_ms, 2),
        )
