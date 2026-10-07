"""[POS]: src/myrm_agent_harness/toolkits/memory/reconciliation/disk_reconciler.py
[INPUT]: Roots directory paths, file system walkers, SQLite connections, and MemoryWriteGate.
[OUTPUT]: DiskMemoryFtsReconciler executing bi-directional reconciliation loops (Direction A indexing & Direction B dead-row pruning).
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from .models import FtsReconciledHit, ReconciliationReport
from .write_gate import MemoryWriteGate


class DiskMemoryFtsReconciler:
    """Bi-directional reconciliation engine synchronizing disk Markdown files with SQLite FTS5."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        write_gate: MemoryWriteGate | None = None,
    ) -> None:
        self._db_path = Path(db_path or "/tmp/myrm_memory_reconciliation.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_gate = write_gate or MemoryWriteGate()
        self._lock = Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA busy_timeout=5000;")
        self._has_fts5 = self._probe_fts5()
        self._init_schema()

    def _probe_fts5(self) -> bool:
        try:
            test_conn = sqlite3.connect(":memory:")
            test_conn.execute("CREATE VIRTUAL TABLE _test_fts USING fts5(content);")
            test_conn.close()
            return True
        except Exception:
            return False

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reconciled_files (
                    file_path TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    mtime REAL NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                );
                """
            )
            if self._has_fts5:
                self._conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS reconciled_fts USING fts5(
                        file_path UNINDEXED,
                        title,
                        content,
                        tokenize='unicode61'
                    );
                    """
                )
            self._conn.commit()

    def reconcile(
        self,
        roots: list[Path | str],
        session_id: str | None = None,
    ) -> ReconciliationReport:
        """Executes a bi-directional reconciliation pass over specified roots."""
        start_time = time.perf_counter()
        reconcile_id = f"rec_{uuid.uuid4().hex[:8]}"

        gate_check = self._write_gate.check_write_allowed(session_id=session_id)
        if not gate_check.is_allowed:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return ReconciliationReport(
                reconcile_id=reconcile_id,
                scanned_disk_files_count=0,
                indexed_or_updated_count=0,
                pruned_dead_rows_count=0,
                duration_ms=elapsed_ms,
                status=f"blocked_by_write_gate: {gate_check.reason}",
            )

        disk_files: dict[str, tuple[str, float, str, str]] = {}
        # 1. Discover all disk markdown files across roots
        for root in roots:
            root_path = Path(root).resolve()
            if not root_path.exists() or not root_path.is_dir():
                continue
            for file_path in root_path.rglob("*.md"):
                if not file_path.is_file():
                    continue
                try:
                    content_bytes = file_path.read_bytes()
                    content_str = content_bytes.decode("utf-8", errors="replace")
                    content_hash = hashlib.sha256(content_bytes).hexdigest()
                    mtime = file_path.stat().st_mtime
                    title = self._extract_title(content_str, file_path.stem)
                    disk_files[str(file_path)] = (content_hash, mtime, title, content_str)
                except OSError:
                    continue

        indexed_or_updated_count = 0
        pruned_dead_rows_count = 0

        with self._lock:
            # Query existing indexed files from DB
            cur = self._conn.execute("SELECT file_path, content_hash FROM reconciled_files;")
            existing_rows = {row[0]: row[1] for row in cur.fetchall()}

            # Direction A: index or update new and modified disk files
            now_iso = datetime.now(UTC).isoformat()
            for path_str, (chash, mtime, title, content) in disk_files.items():
                if path_str not in existing_rows or existing_rows[path_str] != chash:
                    self._conn.execute(
                        """
                        INSERT OR REPLACE INTO reconciled_files
                        (file_path, content_hash, mtime, title, content, indexed_at)
                        VALUES (?, ?, ?, ?, ?, ?);
                        """,
                        (path_str, chash, mtime, title, content, now_iso),
                    )
                    if self._has_fts5:
                        self._conn.execute("DELETE FROM reconciled_fts WHERE file_path = ?;", (path_str,))
                        self._conn.execute(
                            "INSERT INTO reconciled_fts (file_path, title, content) VALUES (?, ?, ?);",
                            (path_str, title, content),
                        )
                    indexed_or_updated_count += 1

            # Direction B: prune dead FTS rows where file no longer exists on disk
            disk_paths_set = set(disk_files.keys())
            dead_paths = set(existing_rows.keys()) - disk_paths_set
            for dead_path in dead_paths:
                self._conn.execute("DELETE FROM reconciled_files WHERE file_path = ?;", (dead_path,))
                if self._has_fts5:
                    self._conn.execute("DELETE FROM reconciled_fts WHERE file_path = ?;", (dead_path,))
                pruned_dead_rows_count += 1

            self._conn.commit()

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return ReconciliationReport(
            reconcile_id=reconcile_id,
            scanned_disk_files_count=len(disk_files),
            indexed_or_updated_count=indexed_or_updated_count,
            pruned_dead_rows_count=pruned_dead_rows_count,
            duration_ms=elapsed_ms,
            status="completed",
        )

    def search(self, query: str, limit: int = 20) -> list[FtsReconciledHit]:
        """Searches reconciled full-text index with ranked hit results."""
        cleaned = query.strip()
        if not cleaned:
            return []

        with self._lock:
            if self._has_fts5:
                sanitized = "".join(c for c in cleaned if c.isalnum() or c.isspace()).strip()
                if not sanitized:
                    return []
                sql = """
                    SELECT file_path, title,
                           snippet(reconciled_fts, 2, '<b>', '</b>', '...', 16) AS snippet,
                           bm25(reconciled_fts) AS rank_score
                    FROM reconciled_fts
                    WHERE reconciled_fts MATCH ?
                    ORDER BY rank_score ASC LIMIT ?;
                """
                try:
                    cur = self._conn.execute(sql, (sanitized, limit))
                    return [
                        FtsReconciledHit(
                            file_path=row[0],
                            title=row[1],
                            snippet=row[2] or "",
                            rank_score=round(float(row[3]), 4),
                        )
                        for row in cur.fetchall()
                    ]
                except sqlite3.OperationalError:
                    return []
            else:
                # Fallback to LIKE search
                sql = """
                    SELECT file_path, title, SUBSTR(content, 1, 120) AS snippet, 1.0 AS rank_score
                    FROM reconciled_files
                    WHERE content LIKE ? OR title LIKE ?
                    LIMIT ?;
                """
                like_term = f"%{cleaned}%"
                cur = self._conn.execute(sql, (like_term, like_term, limit))
                return [
                    FtsReconciledHit(
                        file_path=row[0],
                        title=row[1],
                        snippet=row[2] or "",
                        rank_score=1.0,
                    )
                    for row in cur.fetchall()
                ]

    def get_indexed_count(self) -> int:
        """Returns the total number of currently indexed active files."""
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM reconciled_files;")
            return int(cur.fetchone()[0])

    @staticmethod
    def _extract_title(content: str, default_name: str) -> str:
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
            if stripped.startswith("title:"):
                return stripped[6:].strip().strip("\"'")
        return default_name
