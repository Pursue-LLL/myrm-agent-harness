"""[POS]: src/myrm_agent_harness/toolkits/memory/repair/detector.py
[INPUT]: SQLite connection and schema introspection parameters.
[OUTPUT]: Integrity inspection probe returning strongly typed IntegrityCheckReport.
"""

import sqlite3
import time

from .models import IntegrityCheckReport, IntegrityStatus


class DatabaseIntegrityDetector:
    """Probing engine for physical integrity and index health of SQLite databases."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def inspect(self) -> IntegrityCheckReport:
        """Execute integrity diagnostics and return an evaluation report."""
        cursor = self._conn.cursor()
        issues: list[str] = []
        table_counts: dict[str, int] = {}
        fts_healthy = True

        # 1. PRAGMA integrity_check
        try:
            cursor.execute("PRAGMA integrity_check(10)")
            rows = cursor.fetchall()
            for row in rows:
                val = str(row[0])
                if val.lower() != "ok":
                    issues.append(f"integrity_check: {val}")
        except sqlite3.DatabaseError as exc:
            issues.append(f"integrity_check failed: {exc}")

        # 2. PRAGMA quick_check
        try:
            cursor.execute("PRAGMA quick_check(10)")
            quick_rows = cursor.fetchall()
            for row in quick_rows:
                val = str(row[0])
                if val.lower() != "ok":
                    issues.append(f"quick_check: {val}")
        except sqlite3.DatabaseError as exc:
            issues.append(f"quick_check failed: {exc}")

        # 3. Tables row counting and FTS index check
        try:
            cursor.execute(
                "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            tables = cursor.fetchall()
            for name_val, sql_val in tables:
                tbl_name = str(name_val)
                sql_def = str(sql_val) if sql_val else ""

                # Count rows
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM \"{tbl_name}\"")
                    count_row = cursor.fetchone()
                    table_counts[tbl_name] = int(count_row[0]) if count_row else 0
                except sqlite3.DatabaseError as count_err:
                    issues.append(f"Table count failed for {tbl_name}: {count_err}")

                # Check FTS5 tables
                if "fts5" in sql_def.lower() or "fts4" in sql_def.lower():
                    try:
                        cursor.execute(
                            f"INSERT INTO \"{tbl_name}\"(\"{tbl_name}\") VALUES('integrity-check')"
                        )
                    except sqlite3.DatabaseError as fts_err:
                        fts_healthy = False
                        issues.append(f"FTS integrity check failed for {tbl_name}: {fts_err}")
        except sqlite3.DatabaseError as meta_err:
            issues.append(f"Master schema query failed: {meta_err}")

        # Determine overall integrity status
        if not issues:
            status = IntegrityStatus.HEALTHY
        elif any("malformed" in issue.lower() or "corrupt" in issue.lower() for issue in issues):
            status = IntegrityStatus.CORRUPTED
        else:
            status = IntegrityStatus.DEGRADED

        return IntegrityCheckReport(
            db_status=status,
            fts_healthy=fts_healthy,
            issues=issues,
            checked_at_epoch=time.time(),
            table_counts=table_counts,
        )
