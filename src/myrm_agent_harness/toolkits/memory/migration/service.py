"""[POS]: src/myrm_agent_harness/toolkits/memory/migration/service.py
[INPUT]: Competitor artifacts, filesystem paths, and raw memory payload streams.
[OUTPUT]: SQLite-backed competitor migration service with idempotent deduplication and ledger auditing.
"""

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from myrm_agent_harness.toolkits.memory.migration.detector import (
    CompetitorAssetScanner,
)
from myrm_agent_harness.toolkits.memory.migration.models import (
    CompetitorSourceKind,
    DetectedCompetitorArtifact,
    MigrationExecutionReport,
    NormalizedMemoryPayload,
)
from myrm_agent_harness.toolkits.memory.migration.translators import (
    UniversalMemoryTranslator,
)


class CompetitorMigrationService:
    """Thread-safe SQLite migration service driving asset discovery, schema normalization, and deduplicated ingestion."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        home_dir: Path | None = None,
    ) -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._scanner = CompetitorAssetScanner(home_dir=home_dir)
        self._translator = UniversalMemoryTranslator()

        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA busy_timeout = 5000;")
            self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS competitor_migration_ledger (
            migration_id TEXT PRIMARY KEY,
            source_kind TEXT NOT NULL,
            source_path TEXT NOT NULL,
            total_scanned INTEGER NOT NULL,
            total_imported INTEGER NOT NULL,
            total_skipped_duplicates INTEGER NOT NULL,
            timestamp REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS imported_memory_fingerprints (
            content_hash TEXT PRIMARY KEY,
            migration_id TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_id TEXT NOT NULL,
            normalized_content TEXT NOT NULL,
            layer TEXT NOT NULL,
            tags TEXT NOT NULL,
            provenance_meta TEXT NOT NULL,
            imported_at REAL NOT NULL
        );
        """)
        self._conn.commit()

    def scan_local_artifacts(
        self, custom_candidates: list[str] | None = None
    ) -> list[DetectedCompetitorArtifact]:
        """Scan local filesystem to discover potential competitor memory artifacts."""
        return self._scanner.scan(custom_candidates=custom_candidates)

    def import_from_artifact(
        self, source_kind: CompetitorSourceKind, file_path: str | Path
    ) -> MigrationExecutionReport:
        """Translate and ingest memory records from a local competitor file path."""
        payloads = self._translator.translate_file(
            source_kind=source_kind, file_path=file_path
        )
        return self._execute_migration_batch(
            source_kind=source_kind,
            source_path=str(file_path),
            payloads=payloads,
        )

    def import_raw_text(
        self,
        source_kind: CompetitorSourceKind,
        raw_text: str,
        source_label: str = "raw_buffer",
    ) -> MigrationExecutionReport:
        """Translate and ingest memory records from an in-memory raw payload string."""
        payloads = self._translator.translate_raw(
            source_kind=source_kind, raw_text=raw_text, source_id=source_label
        )
        return self._execute_migration_batch(
            source_kind=source_kind,
            source_path=f"memory://{source_label}",
            payloads=payloads,
        )

    def _execute_migration_batch(
        self,
        source_kind: CompetitorSourceKind,
        source_path: str,
        payloads: list[NormalizedMemoryPayload],
    ) -> MigrationExecutionReport:
        migration_id = f"mig-{uuid.uuid4().hex[:10]}"
        now = time.time()
        imported: list[NormalizedMemoryPayload] = []
        skipped_count = 0

        with self._lock:
            for item in payloads:
                cursor = self._conn.execute(
                    "SELECT content_hash FROM imported_memory_fingerprints WHERE content_hash = ?",
                    (item.content_hash,),
                )
                if cursor.fetchone() is not None:
                    skipped_count += 1
                    continue

                self._conn.execute(
                    """
                    INSERT INTO imported_memory_fingerprints (
                        content_hash, migration_id, source_kind, source_id,
                        normalized_content, layer, tags, provenance_meta, imported_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.content_hash,
                        migration_id,
                        source_kind.value,
                        item.source_id,
                        item.normalized_content,
                        item.layer_recommendation,
                        json.dumps(item.tags, ensure_ascii=False),
                        json.dumps(item.provenance_meta, ensure_ascii=False),
                        now,
                    ),
                )
                imported.append(item)

            self._conn.execute(
                """
                INSERT INTO competitor_migration_ledger (
                    migration_id, source_kind, source_path, total_scanned,
                    total_imported, total_skipped_duplicates, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    migration_id,
                    source_kind.value,
                    source_path,
                    len(payloads),
                    len(imported),
                    skipped_count,
                    now,
                ),
            )
            self._conn.commit()

        return MigrationExecutionReport(
            migration_id=migration_id,
            source_kind=source_kind,
            source_path=source_path,
            total_scanned=len(payloads),
            total_imported=len(imported),
            total_skipped_duplicates=skipped_count,
            imported_entries=imported,
            timestamp=now,
        )

    def list_migration_history(self) -> list[MigrationExecutionReport]:
        """Query migration runs recorded in audit ledger."""
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT migration_id, source_kind, source_path, total_scanned,
                       total_imported, total_skipped_duplicates, timestamp
                FROM competitor_migration_ledger
                ORDER BY timestamp DESC
                """
            )
            rows = cursor.fetchall()

        reports: list[MigrationExecutionReport] = []
        for r in rows:
            reports.append(
                MigrationExecutionReport(
                    migration_id=str(r["migration_id"]),
                    source_kind=CompetitorSourceKind(str(r["source_kind"])),
                    source_path=str(r["source_path"]),
                    total_scanned=int(r["total_scanned"]),
                    total_imported=int(r["total_imported"]),
                    total_skipped_duplicates=int(r["total_skipped_duplicates"]),
                    imported_entries=[],
                    timestamp=float(r["timestamp"]),
                )
            )
        return reports

    def list_imported_fingerprints(
        self, limit: int = 100
    ) -> list[dict[str, str | float]]:
        """Fetch ingested memory records with provenance tags."""
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT content_hash, migration_id, source_kind, source_id,
                       normalized_content, layer, tags, imported_at
                FROM imported_memory_fingerprints
                ORDER BY imported_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        return [
            {
                "content_hash": str(r["content_hash"]),
                "migration_id": str(r["migration_id"]),
                "source_kind": str(r["source_kind"]),
                "source_id": str(r["source_id"]),
                "normalized_content": str(r["normalized_content"]),
                "layer": str(r["layer"]),
                "tags": str(r["tags"]),
                "imported_at": float(r["imported_at"]),
            }
            for r in rows
        ]

    def close(self) -> None:
        """Close sqlite connection."""
        with self._lock:
            self._conn.close()
