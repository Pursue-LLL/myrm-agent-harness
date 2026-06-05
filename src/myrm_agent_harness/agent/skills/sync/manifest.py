"""Skill sync manifest — persistent sync state.

Tracks which skills have been synced, their content hashes, and sync timestamps.
Enables incremental sync (only transfer what changed) instead of full-scan every time.

[INPUT]
- sqlite3 (POS: SQLite database)

[OUTPUT]
- SkillSyncManifest: SQLite-backed persistent sync state

[POS]
Persistent sync state for incremental skill synchronization.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_DDL = """
CREATE TABLE IF NOT EXISTS sync_manifest (
    skill_name      TEXT PRIMARY KEY,
    local_sha256    TEXT NOT NULL,
    remote_sha256   TEXT NOT NULL DEFAULT '',
    local_version   TEXT NOT NULL DEFAULT '1.0.0',
    remote_version  TEXT NOT NULL DEFAULT '',
    last_pushed_at  TEXT,
    last_pulled_at  TEXT,
    sync_status     TEXT NOT NULL DEFAULT 'local_only'
);

CREATE TABLE IF NOT EXISTS sync_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_SYNC_STATUS_LOCAL_ONLY = "local_only"
_SYNC_STATUS_SYNCED = "synced"
_SYNC_STATUS_LOCAL_AHEAD = "local_ahead"
_SYNC_STATUS_REMOTE_AHEAD = "remote_ahead"
_SYNC_STATUS_CONFLICT = "conflict"


class SkillSyncManifest:
    """SQLite-backed persistent sync state.

    Stores per-skill SHA256 hashes and timestamps to enable
    incremental sync without full content comparison.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path).resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)

    def _connect(self) -> sqlite3.Connection:
        from myrm_agent_harness.utils.db.sqlite import DEFAULT, harden_connection_sync

        conn = sqlite3.connect(self._db_path, timeout=10.0)
        harden_connection_sync(conn, DEFAULT, db_path=self._db_path)
        return conn

    def update_local(self, skill_name: str, sha256: str, version: str = "1.0.0") -> None:
        """Record local skill state after evolution or modification."""
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT remote_sha256 FROM sync_manifest WHERE skill_name = ?",
                (skill_name,),
            ).fetchone()

            if existing:
                remote_sha = existing[0]
                status = _SYNC_STATUS_LOCAL_AHEAD if remote_sha and remote_sha != sha256 else _SYNC_STATUS_LOCAL_ONLY
                conn.execute(
                    """UPDATE sync_manifest
                       SET local_sha256 = ?, local_version = ?, sync_status = ?
                       WHERE skill_name = ?""",
                    (sha256, version, status, skill_name),
                )
            else:
                conn.execute(
                    """INSERT INTO sync_manifest (skill_name, local_sha256, local_version, sync_status)
                       VALUES (?, ?, ?, ?)""",
                    (skill_name, sha256, version, _SYNC_STATUS_LOCAL_ONLY),
                )

    def update_remote(self, skill_name: str, sha256: str, version: str = "") -> None:
        """Record remote skill state after pull."""
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT local_sha256 FROM sync_manifest WHERE skill_name = ?",
                (skill_name,),
            ).fetchone()

            if existing:
                local_sha = existing[0]
                status = _SYNC_STATUS_SYNCED if local_sha == sha256 else _SYNC_STATUS_REMOTE_AHEAD
                conn.execute(
                    """UPDATE sync_manifest
                       SET remote_sha256 = ?, remote_version = ?, last_pulled_at = ?, sync_status = ?
                       WHERE skill_name = ?""",
                    (sha256, version, now, status, skill_name),
                )
            else:
                conn.execute(
                    """INSERT INTO sync_manifest
                       (skill_name, local_sha256, remote_sha256, remote_version, last_pulled_at, sync_status)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (skill_name, "", sha256, version, now, _SYNC_STATUS_REMOTE_AHEAD),
                )

    def mark_pushed(self, skill_name: str) -> None:
        """Mark a skill as successfully pushed."""
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """UPDATE sync_manifest
                   SET remote_sha256 = local_sha256, last_pushed_at = ?, sync_status = ?
                   WHERE skill_name = ?""",
                (now, _SYNC_STATUS_SYNCED, skill_name),
            )

    def mark_synced(self, skill_name: str, sha256: str) -> None:
        """Mark a skill as fully synced (local == remote)."""
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """UPDATE sync_manifest
                   SET local_sha256 = ?, remote_sha256 = ?,
                       last_pulled_at = ?, sync_status = ?
                   WHERE skill_name = ?""",
                (sha256, sha256, now, _SYNC_STATUS_SYNCED, skill_name),
            )

    def get_pending_push(self) -> list[str]:
        """Get skill names that have local changes not yet pushed."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT skill_name FROM sync_manifest WHERE sync_status IN (?, ?)",
                (_SYNC_STATUS_LOCAL_ONLY, _SYNC_STATUS_LOCAL_AHEAD),
            ).fetchall()
            return [r[0] for r in rows]

    def get_pending_pull(self) -> list[str]:
        """Get skill names that have remote updates not yet pulled."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT skill_name FROM sync_manifest WHERE sync_status = ?",
                (_SYNC_STATUS_REMOTE_AHEAD,),
            ).fetchall()
            return [r[0] for r in rows]

    def get_conflicts(self) -> list[str]:
        """Get skill names with unresolved conflicts."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT skill_name FROM sync_manifest WHERE sync_status = ?",
                (_SYNC_STATUS_CONFLICT,),
            ).fetchall()
            return [r[0] for r in rows]

    def get_local_sha256(self, skill_name: str) -> str:
        """Get local SHA256 for a skill, empty string if not tracked."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT local_sha256 FROM sync_manifest WHERE skill_name = ?",
                (skill_name,),
            ).fetchone()
            return row[0] if row else ""

    def get_last_sync_time(self) -> datetime | None:
        """Get the most recent sync timestamp."""
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM sync_meta WHERE key = 'last_sync_at'").fetchone()
            if row:
                return datetime.fromisoformat(row[0])
            return None

    def set_last_sync_time(self, ts: datetime | None = None) -> None:
        """Record the last sync timestamp."""
        ts = ts or datetime.now(UTC)
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('last_sync_at', ?)""",
                (ts.isoformat(),),
            )

    def get_sync_counts(self) -> dict[str, int]:
        """Get counts by sync status for UI display."""
        with self._connect() as conn:
            rows = conn.execute("SELECT sync_status, COUNT(*) FROM sync_manifest GROUP BY sync_status").fetchall()
            return {r[0]: r[1] for r in rows}
