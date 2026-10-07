"""[POS]: src/myrm_agent_harness/toolkits/memory/repair/pruner.py
[INPUT]: Memory entries, recall statistics, and StalePrunePolicy constraints.
[OUTPUT]: Adaptive decay evaluator and pruning engine producing PruneSummary.
"""

import math
import sqlite3
import time

from .models import MemoryRecordItem, PruneSummary, StalePrunePolicy


class StaleEntryPruner:
    """Adaptive utility decay evaluator and stale entry pruner."""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self._conn = conn

    def calculate_utility_score(
        self,
        last_recalled_at_epoch: float,
        recall_count: int,
        decay_rate: float,
        now_epoch: float,
    ) -> float:
        """Calculate exponential utility decay score based on recall history and recency."""
        delta_days = max(0.0, (now_epoch - last_recalled_at_epoch) / 86400.0)
        frequency_boost = 1.0 + math.log(1.0 + max(0, recall_count))
        decay_factor = math.exp(-decay_rate * delta_days)
        return float(frequency_boost * decay_factor)

    def evaluate_entries(
        self,
        entries: list[MemoryRecordItem],
        policy: StalePrunePolicy,
        now_epoch: float | None = None,
    ) -> PruneSummary:
        """Evaluate memory records in-memory and identify stale items to archive."""
        start_time = time.perf_counter()
        current_now = now_epoch if now_epoch is not None else time.time()
        archived_ids: list[str] = []
        protected_count = 0

        for item in entries:
            if item.status == "archived":
                continue

            if policy.protect_pinned and item.is_pinned:
                protected_count += 1
                continue

            delta_days = (current_now - item.last_recalled_at_epoch) / 86400.0
            utility = self.calculate_utility_score(
                last_recalled_at_epoch=item.last_recalled_at_epoch,
                recall_count=item.recall_count,
                decay_rate=policy.decay_rate,
                now_epoch=current_now,
            )

            # Check if entry is stale
            is_stale = (
                delta_days >= policy.stale_days_threshold
                and item.recall_count <= policy.min_recall_count
            ) or (utility < 0.1 and delta_days >= 7.0)

            if is_stale:
                archived_ids.append(item.id)
                if not policy.dry_run:
                    item.status = "archived"
            else:
                protected_count += 1

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return PruneSummary(
            evaluated_count=len(entries),
            archived_count=len(archived_ids),
            protected_count=protected_count,
            archived_ids=archived_ids,
            duration_ms=round(duration_ms, 2),
        )

    def prune_sqlite_table(
        self,
        table_name: str,
        policy: StalePrunePolicy,
        now_epoch: float | None = None,
    ) -> PruneSummary:
        """Execute pruning directly against a SQLite storage table."""
        if self._conn is None:
            raise RuntimeError("SQLite connection required for database pruning")

        start_time = time.perf_counter()
        current_now = now_epoch if now_epoch is not None else time.time()
        cutoff_epoch = current_now - (policy.stale_days_threshold * 86400.0)

        cursor = self._conn.cursor()
        query = f"""
            SELECT id, last_recalled_at_epoch, recall_count, is_pinned
            FROM "{table_name}"
            WHERE status != 'archived'
        """
        cursor.execute(query)
        rows = cursor.fetchall()

        archived_ids: list[str] = []
        protected_count = 0

        for row in rows:
            entry_id = str(row[0])
            last_recalled = float(row[1]) if row[1] is not None else 0.0
            recall_count = int(row[2]) if row[2] is not None else 0
            is_pinned = bool(row[3]) if row[3] is not None else False

            if policy.protect_pinned and is_pinned:
                protected_count += 1
                continue

            if last_recalled <= cutoff_epoch and recall_count <= policy.min_recall_count:
                archived_ids.append(entry_id)
            else:
                protected_count += 1

        if archived_ids and not policy.dry_run:
            placeholders = ",".join("?" for _ in archived_ids)
            cursor.execute(
                f"UPDATE \"{table_name}\" SET status = 'archived' WHERE id IN ({placeholders})",
                archived_ids,
            )
            self._conn.commit()

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        return PruneSummary(
            evaluated_count=len(rows),
            archived_count=len(archived_ids),
            protected_count=protected_count,
            archived_ids=archived_ids,
            duration_ms=round(duration_ms, 2),
        )
