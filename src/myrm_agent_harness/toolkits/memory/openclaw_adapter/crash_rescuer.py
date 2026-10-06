# [POS] src/myrm_agent_harness/toolkits/memory/openclaw_adapter/crash_rescuer.py
# [INPUT] sqlite3, pathlib.Path, logging, .types (RescueReport)
# [OUTPUT] OpenClawCrashRescuer

import logging
import sqlite3
from pathlib import Path

from .types import RescueReport

logger = logging.getLogger(__name__)


class OpenClawCrashRescuer:
    """Crash recovery engine for corrupted OpenClaw SQLite databases.

    Provides read-only WAL isolation, integrity diagnostic probes, and fault-tolerant
    row-level extraction to rescue salvageable sessions and memories even when
    database headers, B-trees, or index pages are malformed.
    """

    def probe_integrity(self, db_path: Path) -> tuple[bool, str]:
        """Probe SQLite database integrity.

        Returns:
            Tuple of (is_corrupt, integrity_check_output).
        """
        if not db_path.exists():
            return True, "File does not exist."

        try:
            conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
            try:
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check;")
                results = cursor.fetchall()
                output_str = " | ".join(str(r[0]) for r in results)
                is_corrupt = output_str.strip().lower() != "ok"
                return is_corrupt, output_str
            finally:
                conn.close()
        except sqlite3.DatabaseError as e:
            logger.warning("Database error during integrity probe of '%s': %s", db_path, e)
            return True, str(e)
        except Exception as ex:
            logger.error("Unexpected failure inspecting '%s': %s", db_path, ex)
            return True, str(ex)

    def rescue_table_rows(
        self,
        db_path: Path,
        table_name: str,
        expected_columns: list[str],
    ) -> tuple[list[dict[str, str]], RescueReport]:
        """Extract salvageable rows from a specific table with per-row fault tolerance."""
        is_corrupt, check_output = self.probe_integrity(db_path)
        rescued_records: list[dict[str, str]] = []
        total_scanned = 0
        corrupted_skipped = 0

        cols_clause = ", ".join(expected_columns)
        query = f"SELECT {cols_clause} FROM {table_name};"

        try:
            conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.cursor()
                # Run query with tolerant cursor iteration
                try:
                    cursor.execute(query)
                    while True:
                        try:
                            row = cursor.fetchone()
                            if row is None:
                                break
                            total_scanned += 1
                            item_dict: dict[str, str] = {}
                            for col in expected_columns:
                                val = row[col]
                                item_dict[col] = str(val) if val is not None else ""
                            rescued_records.append(item_dict)
                        except (sqlite3.DatabaseError, sqlite3.OperationalError) as row_err:
                            corrupted_skipped += 1
                            logger.warning(
                                "Skipped corrupted row in table '%s' at index %d: %s",
                                table_name,
                                total_scanned,
                                row_err,
                            )
                except (sqlite3.DatabaseError, sqlite3.OperationalError) as query_err:
                    logger.error("Failed to execute query on '%s': %s", table_name, query_err)
            finally:
                conn.close()
        except Exception as conn_err:
            logger.error("Failed to establish rescue connection to '%s': %s", db_path, conn_err)

        recovered_count = len(rescued_records)
        total_items = recovered_count + corrupted_skipped
        rate = 1.0 if total_items == 0 else float(recovered_count) / float(total_items)

        report = RescueReport(
            db_path=str(db_path),
            is_sqlite_corrupt=is_corrupt,
            integrity_check_output=check_output,
            total_rows_scanned=total_scanned,
            recovered_count=recovered_count,
            corrupted_rows_skipped=corrupted_skipped,
            rescue_success_rate=round(rate, 4),
        )
        return rescued_records, report
