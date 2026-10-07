"""[POS]: src/myrm_agent_harness/toolkits/memory/ingestion_gateway/dedup.py
[INPUT]: ContextIngestionPayload and computed content SHA-256 fingerprints.
[OUTPUT]: IngestionIdempotencyGuard maintaining SQLite deduplication registry.
"""

import contextlib
import hashlib
import sqlite3
import time
from pathlib import Path


class IngestionIdempotencyGuard:
    """SQLite-backed idempotency guard preventing duplicate context ingestion."""

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
            CREATE TABLE IF NOT EXISTS myrm_ingestion_fingerprints (
                fingerprint TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                device_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at_epoch REAL NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_ingestion_epoch
            ON myrm_ingestion_fingerprints(created_at_epoch);
            """
        )
        conn.commit()

    @staticmethod
    def compute_fingerprint(raw_payload: str, device_id: str = "") -> str:
        """Compute stable SHA-256 hash from normalized content payload."""
        normalized = raw_payload.strip().encode("utf-8")
        hasher = hashlib.sha256(normalized)
        if device_id:
            hasher.update(device_id.strip().encode("utf-8"))
        return hasher.hexdigest()

    def is_recorded(self, fingerprint: str) -> bool:
        """Check if fingerprint already exists in the registry."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT 1 FROM myrm_ingestion_fingerprints WHERE fingerprint = ?;",
            (fingerprint,),
        )
        return cursor.fetchone() is not None

    def record_fingerprint(
        self,
        fingerprint: str,
        source_type: str,
        device_id: str,
        title: str,
    ) -> bool:
        """Record fingerprint. Returns True if inserted, False if already present."""
        now = time.time()
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO myrm_ingestion_fingerprints
                (fingerprint, source_type, device_id, title, created_at_epoch)
                VALUES (?, ?, ?, ?, ?);
                """,
                (fingerprint, source_type, device_id, title, now),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def list_records(self, limit: int = 50) -> list[dict[str, str | float]]:
        """List recently ingested context fingerprints."""
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT fingerprint, source_type, device_id, title, created_at_epoch
            FROM myrm_ingestion_fingerprints
            ORDER BY created_at_epoch DESC
            LIMIT ?;
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [
            {
                "fingerprint": str(row["fingerprint"]),
                "source_type": str(row["source_type"]),
                "device_id": str(row["device_id"]),
                "title": str(row["title"]),
                "created_at_epoch": float(row["created_at_epoch"]),
            }
            for row in rows
        ]

    def close(self) -> None:
        """Close SQLite connection if open."""
        if self._conn is not None:
            with contextlib.suppress(sqlite3.DatabaseError):
                self._conn.close()
            self._conn = None
