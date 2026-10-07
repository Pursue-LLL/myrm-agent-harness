"""[POS]: src/myrm_agent_harness/toolkits/memory/tombstone/service.py
[INPUT]: Memory candidate entries, SQLite database path, and lifecycle transition instructions.
[OUTPUT]: MemoryTombstoneCurationService providing automated contradiction curation, tombstone masking, and eviction.
"""

import sqlite3
import time
from pathlib import Path

from myrm_agent_harness.toolkits.memory.tombstone.detector import (
    PreferenceContradictionDetector,
)
from myrm_agent_harness.toolkits.memory.tombstone.models import (
    TombstoneAuditRecord,
    TombstoneCandidateItem,
    TombstoneCurationReport,
    TombstoneState,
)


class MemoryTombstoneCurationService:
    """Orchestrates memory contradiction detection, tombstone isolation, revival, and eviction."""

    def __init__(
        self,
        db_path: str | Path,
        detector: PreferenceContradictionDetector | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.detector = detector or PreferenceContradictionDetector()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tombstone_records (
                    memory_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    tombstoned_at REAL,
                    superseded_by_id TEXT,
                    reason TEXT,
                    evicted_at REAL,
                    updated_at REAL NOT NULL
                );
            """)
            conn.commit()

    def curate_and_tombstone(
        self,
        memories: list[TombstoneCandidateItem],
        auto_tombstone: bool = True,
    ) -> TombstoneCurationReport:
        """Scan candidate memories for antithetical contradictions and apply tombstone masking."""
        contradictions = self.detector.detect_contradictions(memories)
        target_state = TombstoneState.TOMBSTONED if auto_tombstone else TombstoneState.SUPERSEDED_CANDIDATE
        now = time.time()
        tombstoned_count = 0

        with self._get_connection() as conn:
            for pair in contradictions:
                # Outdated memory gets marked with tombstone
                conn.execute(
                    """
                    INSERT INTO tombstone_records (
                        memory_id, state, tombstoned_at, superseded_by_id, reason, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(memory_id) DO UPDATE SET
                        state = excluded.state,
                        tombstoned_at = excluded.tombstoned_at,
                        superseded_by_id = excluded.superseded_by_id,
                        reason = excluded.reason,
                        updated_at = excluded.updated_at
                    """,
                    (
                        pair.outdated_memory_id,
                        target_state.value,
                        now,
                        pair.new_memory_id,
                        pair.reason,
                        now,
                    ),
                )
                tombstoned_count += 1
            conn.commit()

        return TombstoneCurationReport(
            total_scanned=len(memories),
            total_contradictions_found=len(contradictions),
            total_tombstoned=tombstoned_count,
            total_evicted=0,
            contradictions=contradictions,
            timestamp=now,
        )

    def filter_active_memories(
        self, candidates: list[TombstoneCandidateItem]
    ) -> list[TombstoneCandidateItem]:
        """Hard recall gate filtering out tombstoned or evicted memories before system prompt injection."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT memory_id FROM tombstone_records WHERE state IN (?, ?)",
                (TombstoneState.TOMBSTONED.value, TombstoneState.EVICTED.value),
            )
            blocked_ids = {str(row["memory_id"]) for row in cursor.fetchall()}

        return [m for m in candidates if m.memory_id not in blocked_ids]

    def revive_tombstone(self, memory_id: str) -> bool:
        """Reinstate a tombstoned memory item back to active recall pool upon user or admin intervention."""
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE tombstone_records
                SET state = ?, updated_at = ?
                WHERE memory_id = ? AND state IN (?, ?)
                """,
                (
                    TombstoneState.REVIVED.value,
                    now,
                    memory_id,
                    TombstoneState.TOMBSTONED.value,
                    TombstoneState.SUPERSEDED_CANDIDATE.value,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def evict_tombstones(self, memory_ids: list[str] | None = None) -> int:
        """Physically evict tombstoned entries after retention expiration or explicit confirmation."""
        now = time.time()
        with self._get_connection() as conn:
            if memory_ids:
                placeholders = ",".join("?" for _ in memory_ids)
                cursor = conn.execute(
                    f"""
                    UPDATE tombstone_records
                    SET state = ?, evicted_at = ?, updated_at = ?
                    WHERE memory_id IN ({placeholders}) AND state = ?
                    """,
                    [TombstoneState.EVICTED.value, now, now, *memory_ids, TombstoneState.TOMBSTONED.value],
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE tombstone_records
                    SET state = ?, evicted_at = ?, updated_at = ?
                    WHERE state = ?
                    """,
                    (TombstoneState.EVICTED.value, now, now, TombstoneState.TOMBSTONED.value),
                )
            conn.commit()
            return cursor.rowcount

    def get_tombstone_record(self, memory_id: str) -> TombstoneAuditRecord | None:
        """Fetch audit lifecycle record for a specific memory identifier."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM tombstone_records WHERE memory_id = ?",
                (memory_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return TombstoneAuditRecord(
                memory_id=str(row["memory_id"]),
                state=TombstoneState(row["state"]),
                tombstoned_at=float(row["tombstoned_at"]) if row["tombstoned_at"] is not None else None,
                superseded_by_id=str(row["superseded_by_id"]) if row["superseded_by_id"] else None,
                reason=str(row["reason"]) if row["reason"] else None,
                evicted_at=float(row["evicted_at"]) if row["evicted_at"] is not None else None,
            )

    def list_curation_records(self) -> list[TombstoneAuditRecord]:
        """List all non-active records for UI curation panel inspection."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM tombstone_records ORDER BY updated_at DESC",
            )
            records: list[TombstoneAuditRecord] = []
            for row in cursor.fetchall():
                records.append(
                    TombstoneAuditRecord(
                        memory_id=str(row["memory_id"]),
                        state=TombstoneState(row["state"]),
                        tombstoned_at=float(row["tombstoned_at"]) if row["tombstoned_at"] is not None else None,
                        superseded_by_id=str(row["superseded_by_id"]) if row["superseded_by_id"] else None,
                        reason=str(row["reason"]) if row["reason"] else None,
                        evicted_at=float(row["evicted_at"]) if row["evicted_at"] is not None else None,
                    )
                )
            return records

    def close(self) -> None:
        """Lifecycle hook for clean service teardown."""
