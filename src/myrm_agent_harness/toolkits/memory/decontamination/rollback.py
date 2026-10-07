"""[POS]: src/myrm_agent_harness/toolkits/memory/decontamination/rollback.py
[INPUT]: Active memory sets, snapshot identifiers, and session decontamination targets.
[OUTPUT]: MemorySnapshotRollbackEngine providing point-in-time snapshotting, rollback, and session purging.
"""

import json
import sqlite3
import time
import uuid
from pathlib import Path

from .attestation import ProvenanceAttestationManager
from .detector import DecontaminationGuard
from .models import MemorySnapshotRecord, RollbackReport


class MemorySnapshotRollbackEngine:
    """Manages memory snapshots, version time travel, and session-scoped decontamination rollbacks."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None

    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            if self.db_path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA busy_timeout = 5000;")
            self._init_schema(self._conn)
        return self._conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS myrm_memory_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                memory_ids_json TEXT NOT NULL,
                created_at_epoch REAL NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_snapshot_epoch
            ON myrm_memory_snapshots(created_at_epoch DESC);
            """
        )
        conn.commit()

    def create_snapshot(
        self,
        label: str,
        active_memory_ids: list[str],
    ) -> MemorySnapshotRecord:
        """Create a point-in-time baseline snapshot of current active memories."""
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        now = time.time()
        ids_json = json.dumps(active_memory_ids)

        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO myrm_memory_snapshots
            (snapshot_id, label, memory_ids_json, created_at_epoch)
            VALUES (?, ?, ?, ?);
            """,
            (snapshot_id, label, ids_json, now),
        )
        conn.commit()

        return MemorySnapshotRecord(
            snapshot_id=snapshot_id,
            label=label,
            memory_ids=active_memory_ids,
            created_at_epoch=now,
        )

    def get_snapshot(self, snapshot_id: str) -> MemorySnapshotRecord | None:
        """Retrieve snapshot record by ID."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT snapshot_id, label, memory_ids_json, created_at_epoch FROM myrm_memory_snapshots WHERE snapshot_id = ?;",
            (snapshot_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        m_ids = json.loads(str(row["memory_ids_json"]))
        return MemorySnapshotRecord(
            snapshot_id=str(row["snapshot_id"]),
            label=str(row["label"]),
            memory_ids=m_ids if isinstance(m_ids, list) else [],
            created_at_epoch=float(row["created_at_epoch"]),
        )

    def list_snapshots(self, limit: int = 50) -> list[MemorySnapshotRecord]:
        """List recently created memory snapshots."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT snapshot_id, label, memory_ids_json, created_at_epoch
            FROM myrm_memory_snapshots
            ORDER BY created_at_epoch DESC
            LIMIT ?;
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        result: list[MemorySnapshotRecord] = []
        for r in rows:
            m_ids = json.loads(str(r["memory_ids_json"]))
            result.append(
                MemorySnapshotRecord(
                    snapshot_id=str(r["snapshot_id"]),
                    label=str(r["label"]),
                    memory_ids=m_ids if isinstance(m_ids, list) else [],
                    created_at_epoch=float(r["created_at_epoch"]),
                )
            )
        return result

    def rollback_to_snapshot(
        self,
        snapshot_id: str,
        current_memory_ids: list[str],
        guard: DecontaminationGuard,
    ) -> RollbackReport:
        """Rollback state by quarantining all memories introduced after the target snapshot."""
        snapshot = self.get_snapshot(snapshot_id)
        now = time.time()
        if not snapshot:
            return RollbackReport(
                target_id=snapshot_id,
                label="Snapshot not found",
                quarantined_count=0,
                restored_count=0,
                timestamp_epoch=now,
            )

        baseline_set = set(snapshot.memory_ids)
        # Memories that did not exist in the snapshot baseline
        to_quarantine = [mid for mid in current_memory_ids if mid not in baseline_set]

        for mid in to_quarantine:
            guard.quarantine_memory(
                memory_id=mid,
                reason=f"Rolled back to snapshot [{snapshot.label}] ({snapshot_id})",
            )

        # Memories in baseline that are currently quarantined get pardoned
        for mid in snapshot.memory_ids:
            if guard.is_quarantined(mid):
                guard.pardon_memory(mid)

        return RollbackReport(
            target_id=snapshot_id,
            label=snapshot.label,
            quarantined_count=len(to_quarantine),
            restored_count=len(snapshot.memory_ids),
            timestamp_epoch=now,
        )

    def quarantine_by_session(
        self,
        session_id: str,
        attestation_mgr: ProvenanceAttestationManager,
        guard: DecontaminationGuard,
    ) -> int:
        """Trace all memories originating from session_id and quarantine them immediately."""
        attestations = attestation_mgr.list_attestations_by_session(session_id)
        count = 0
        for att in attestations:
            guard.quarantine_memory(
                memory_id=att.memory_id,
                reason=f"Session-wide decontamination purge for session [{session_id}]",
            )
            count += 1
        return count
