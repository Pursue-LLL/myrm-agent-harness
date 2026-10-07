"""[POS]: src/myrm_agent_harness/toolkits/memory/repair/service.py
[INPUT]: SQLite connection, integrity detector, auto healer, and pruning engines.
[OUTPUT]: Unified facade service orchestrating database health, repair, and pruning.
"""

import sqlite3
import time

from .barrier import CachePreservingCompactionBarrier
from .detector import DatabaseIntegrityDetector
from .healer import DatabaseAutoHealer
from .models import (
    HealthMetric,
    IntegrityCheckReport,
    IntegrityStatus,
    PruneSummary,
    RepairReport,
    StalePrunePolicy,
)
from .pruner import StaleEntryPruner


class MemoryRepairService:
    """Unified service facade for memory integrity diagnostics, repair, and stale pruning."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        barrier: CachePreservingCompactionBarrier | None = None,
    ) -> None:
        self._conn = conn
        self._detector = DatabaseIntegrityDetector(conn)
        self._healer = DatabaseAutoHealer(conn)
        self._pruner = StaleEntryPruner(conn)
        self._barrier = barrier or CachePreservingCompactionBarrier()

    @property
    def barrier(self) -> CachePreservingCompactionBarrier:
        """Access the cache-preserving barrier instance."""
        return self._barrier

    def check_integrity(self) -> IntegrityCheckReport:
        """Perform non-destructive database health and index diagnostics."""
        return self._detector.inspect()

    def repair_database(self) -> RepairReport:
        """Trigger physical self-healing on indexes, FTS tables, and WAL checkpoint."""
        report = self.check_integrity()
        return self._healer.heal(report)

    def prune_stale_entries(
        self,
        table_name: str = "myrm_memories",
        policy: StalePrunePolicy | None = None,
        active_session_id: str | None = None,
    ) -> PruneSummary:
        """Prune decayed stale memories while respecting prompt cache barrier."""
        active_policy = policy or StalePrunePolicy()

        # Check if table exists before pruning
        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        if not cursor.fetchone():
            return PruneSummary(
                evaluated_count=0,
                archived_count=0,
                protected_count=0,
                archived_ids=[],
                duration_ms=0.0,
            )

        summary = self._pruner.prune_sqlite_table(
            table_name=table_name,
            policy=active_policy,
        )

        if active_session_id and summary.archived_ids:
            self._barrier.defer_compaction_if_active(active_session_id, summary.archived_ids)

        return summary

    def get_health_metric(self, table_name: str = "myrm_memories") -> HealthMetric:
        """Calculate holistic health score and statistics for memory storage."""
        report = self.check_integrity()

        total_entries = 0
        active_entries = 0
        stale_entries = 0

        cursor = self._conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        if cursor.fetchone():
            cursor.execute(f"SELECT COUNT(*) FROM \"{table_name}\"")
            row = cursor.fetchone()
            total_entries = int(row[0]) if row else 0

            cursor.execute(f"SELECT COUNT(*) FROM \"{table_name}\" WHERE status != 'archived'")
            active_row = cursor.fetchone()
            active_entries = int(active_row[0]) if active_row else 0

            # Count stale candidates (30+ days without recall)
            cutoff_epoch = time.time() - (30 * 86400.0)
            cursor.execute(
                f"""
                SELECT COUNT(*) FROM \"{table_name}\"
                WHERE status != 'archived'
                  AND is_pinned = 0
                  AND last_recalled_at_epoch <= ?
                """,
                (cutoff_epoch,),
            )
            stale_row = cursor.fetchone()
            stale_entries = int(stale_row[0]) if stale_row else 0

        # Health score calculation: 100 baseline, deductions for corruption & stale ratio
        base_score = 100.0
        if report.db_status == IntegrityStatus.CORRUPTED:
            base_score = 0.0
        elif report.db_status == IntegrityStatus.DEGRADED:
            base_score = 60.0

        if not report.fts_healthy:
            base_score = max(0.0, base_score - 20.0)

        if total_entries > 0:
            stale_ratio = stale_entries / total_entries
            penalty = stale_ratio * 20.0
            base_score = max(0.0, base_score - penalty)

        return HealthMetric(
            overall_health_score=round(base_score, 1),
            total_entries=total_entries,
            active_entries=active_entries,
            stale_entries=stale_entries,
            integrity_status=report.db_status,
        )
