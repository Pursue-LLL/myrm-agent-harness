"""[POS]: src/myrm_agent_harness/toolkits/memory/decontamination/detector.py
[INPUT]: Memory texts, identifiers, and candidate origin source types.
[OUTPUT]: DecontaminationGuard inspecting poisoning threats, enforcing quarantine barriers, and pardoning clean memories.
"""

import re
import sqlite3
import time
from pathlib import Path

from .models import DecontaminationReport, DecontaminationStatus


class DecontaminationGuard:
    """Active detector and quarantine gate preventing poisoned memories from polluting context."""

    _INJECTION_PATTERNS = (
        r"ignore\s+(all\s+)?(previous|prior)\s+instructions",
        r"system\s+prompt\s+override",
        r"you\s+are\s+now\s+in\s+developer\s+mode",
        r"bypass\s+(safety|content)\s+filters?",
        r"disregard\s+all\s+rules",
        r"jailbreak\s+active",
        r"sudo\s+mode\s+enabled",
    )

    _DESTRUCTIVE_PATTERNS = (
        r"rm\s+-rf\s+[/~]",
        r"delete\s+all\s+(memories|databases?)",
        r"drop\s+database",
        r"reveal\s+api\s+keys?",
        r"leak\s+(credentials|tokens?)",
        r"format\s+c:\s*",
    )

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
            CREATE TABLE IF NOT EXISTS myrm_memory_quarantine (
                memory_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                reason TEXT NOT NULL,
                updated_at_epoch REAL NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_quarantine_status
            ON myrm_memory_quarantine(status);
            """
        )
        conn.commit()

    def evaluate_content(
        self,
        memory_id: str,
        content: str,
        source_kind: str = "",
    ) -> DecontaminationReport:
        """Scan candidate memory content for injection attacks and destructive payloads."""
        threat_reasons: list[str] = []
        lowered = content.lower()

        for pattern in self._INJECTION_PATTERNS:
            if re.search(pattern, lowered):
                threat_reasons.append(f"Prompt injection pattern detected: {pattern}")

        for pattern in self._DESTRUCTIVE_PATTERNS:
            if re.search(pattern, lowered):
                threat_reasons.append(f"Destructive operation payload detected: {pattern}")

        now = time.time()
        if threat_reasons:
            status = DecontaminationStatus.QUARANTINED
            self.quarantine_memory(memory_id, "; ".join(threat_reasons))
        else:
            status = self.get_status(memory_id)

        return DecontaminationReport(
            memory_id=memory_id,
            status=status,
            threat_reasons=threat_reasons,
            evaluated_at_epoch=now,
        )

    def quarantine_memory(self, memory_id: str, reason: str) -> None:
        """Place memory into quarantine barrier, blocking retrieval."""
        now = time.time()
        conn = self._get_connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO myrm_memory_quarantine
            (memory_id, status, reason, updated_at_epoch)
            VALUES (?, ?, ?, ?);
            """,
            (memory_id, DecontaminationStatus.QUARANTINED.value, reason, now),
        )
        conn.commit()

    def pardon_memory(self, memory_id: str) -> None:
        """Pardon memory, lifting quarantine back to CLEAN status."""
        conn = self._get_connection()
        conn.execute(
            "DELETE FROM myrm_memory_quarantine WHERE memory_id = ?;",
            (memory_id,),
        )
        conn.commit()

    def get_status(self, memory_id: str) -> DecontaminationStatus:
        """Get current sanitation status for memory ID."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT status FROM myrm_memory_quarantine WHERE memory_id = ?;",
            (memory_id,),
        )
        row = cursor.fetchone()
        if not row:
            return DecontaminationStatus.CLEAN
        return DecontaminationStatus(row["status"])

    def is_quarantined(self, memory_id: str) -> bool:
        """Check if memory is blocked under quarantine."""
        return self.get_status(memory_id) in (
            DecontaminationStatus.QUARANTINED,
            DecontaminationStatus.EXPUNGED,
        )

    def filter_clean_memories(self, memory_ids: list[str]) -> list[str]:
        """Filter memory IDs list, excluding any quarantined items."""
        if not memory_ids:
            return []
        conn = self._get_connection()
        placeholders = ",".join("?" for _ in memory_ids)
        cursor = conn.execute(
            f"SELECT memory_id FROM myrm_memory_quarantine WHERE memory_id IN ({placeholders}) AND status = ?;",
            (*memory_ids, DecontaminationStatus.QUARANTINED.value),
        )
        blocked = {str(row["memory_id"]) for row in cursor.fetchall()}
        return [mid for mid in memory_ids if mid not in blocked]

    def list_quarantined(self, limit: int = 50) -> list[dict[str, str | float]]:
        """List currently quarantined memories with reasons and timestamps."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT memory_id, status, reason, updated_at_epoch
            FROM myrm_memory_quarantine
            WHERE status = ?
            ORDER BY updated_at_epoch DESC
            LIMIT ?;
            """,
            (DecontaminationStatus.QUARANTINED.value, limit),
        )
        rows = cursor.fetchall()
        return [
            {
                "memory_id": str(r["memory_id"]),
                "status": str(r["status"]),
                "reason": str(r["reason"]),
                "updated_at_epoch": float(r["updated_at_epoch"]),
            }
            for r in rows
        ]
