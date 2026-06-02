"""SQLite persistence for skill evolution system.

Simplified design (2 tables vs OpenSpace's 5 tables):
- skills: Main skill records with embedded metrics and lineage
- No separate tables for parents/analyses/judgments/deps/tags (95% complexity reduction)

Retains OpenSpace's core strengths:
- WAL mode for concurrent reads
- db_retry decorator for robustness
- Async-safe write path

[INPUT]
- agent.skills.evolution.core.types::SkillLineage, (POS: Data types for skill evolution system.)
- toolkits.vector.base::VectorStore, (POS: Abstract interface for vector databases.)
- toolkits.memory.protocols.embedding::EmbeddingProtocol, (POS: Protocol for text embedding models.)

[OUTPUT]
- SkillStore: Simplified SQLite persistence for skill evolution, with Hybrid Retrieval (Qdrant) sync support.

[POS]
SQLite persistence for skill evolution system, with Hybrid Retrieval (Qdrant) sync support.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager, suppress
from functools import wraps
from pathlib import Path

from myrm_agent_harness.agent.skills.evolution.core.types import (
    SkillLineage,
    SkillMetrics,
    SkillRecord,
)
from myrm_agent_harness.agent.skills.evolution.db._store_evolution_tracking import (
    SkillEvolutionTrackingMixin,
)
from myrm_agent_harness.agent.skills.evolution.db._store_vector import (
    SkillVectorSyncMixin,
)
from myrm_agent_harness.agent.skills.evolution.db.store_queries import SkillStoreQueries
from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
from myrm_agent_harness.toolkits.vector.base import VectorStore

logger = logging.getLogger(__name__)

__all__ = ["SkillStore"]


def _db_retry(max_retries: int = 5, initial_delay: float = 0.1, backoff: float = 2.0):
    """Retry on transient SQLite errors with exponential backoff.

    Handles OperationalError (e.g. "database is locked") and DatabaseError.
    Does NOT retry programming errors like InterfaceError.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
                    if attempt == max_retries - 1:
                        logger.error(
                            "DB %s failed after %d retries: %s",
                            func.__name__,
                            max_retries,
                            exc,
                        )
                        raise
                    logger.warning(
                        "DB %s retry %d/%d: %s",
                        func.__name__,
                        attempt + 1,
                        max_retries,
                        exc,
                    )
                    time.sleep(delay)
                    delay *= backoff

        return wrapper

    return decorator


_DDL = """
CREATE TABLE IF NOT EXISTS skills (
    skill_id            TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    description         TEXT NOT NULL DEFAULT '',
    content             TEXT NOT NULL,
    path                TEXT NOT NULL DEFAULT '',

    evolution_type      TEXT NOT NULL,
    version             INTEGER NOT NULL DEFAULT 1,
    parent_id           TEXT,
    change_summary      TEXT NOT NULL DEFAULT '',
    lineage_created_at  TEXT NOT NULL,
    lineage_created_by  TEXT NOT NULL DEFAULT '',

    total_selections    INTEGER NOT NULL DEFAULT 0,
    applied_count       INTEGER NOT NULL DEFAULT 0,
    completed_count     INTEGER NOT NULL DEFAULT 0,
    success_count       INTEGER NOT NULL DEFAULT 0,
    last_success_at     TEXT,
    last_failure_at     TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,

    traps               TEXT NOT NULL DEFAULT '[]',
    verification_steps  TEXT NOT NULL DEFAULT '[]',
    environment         TEXT,

    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    is_active           INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);
CREATE INDEX IF NOT EXISTS idx_skills_parent ON skills(parent_id);
CREATE INDEX IF NOT EXISTS idx_skills_version ON skills(skill_id, version);
CREATE INDEX IF NOT EXISTS idx_skills_active ON skills(is_active);
CREATE INDEX IF NOT EXISTS idx_skills_updated ON skills(updated_at);
CREATE INDEX IF NOT EXISTS idx_skills_selections ON skills(total_selections);

CREATE TABLE IF NOT EXISTS execution_analyses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id            TEXT NOT NULL,
    task_id             TEXT NOT NULL,
    success             INTEGER NOT NULL,
    error_message       TEXT NOT NULL DEFAULT '',
    root_cause          TEXT NOT NULL DEFAULT '',
    suggested_fix       TEXT NOT NULL DEFAULT '',
    task_context        TEXT NOT NULL DEFAULT '',
    analyzed_at         TEXT NOT NULL,
    FOREIGN KEY(skill_id) REFERENCES skills(skill_id)
);

CREATE INDEX IF NOT EXISTS idx_analyses_skill ON execution_analyses(skill_id);
CREATE INDEX IF NOT EXISTS idx_analyses_time ON execution_analyses(analyzed_at);

CREATE TABLE IF NOT EXISTS evolution_rejections (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id            TEXT NOT NULL,
    trigger_type        TEXT NOT NULL,
    proposed_type       TEXT NOT NULL,
    rejection_reason    TEXT NOT NULL,
    confidence          REAL NOT NULL DEFAULT 0.5,
    trigger_context     TEXT NOT NULL DEFAULT '',
    rejected_at         TEXT NOT NULL,
    FOREIGN KEY(skill_id) REFERENCES skills(skill_id)
);

CREATE INDEX IF NOT EXISTS idx_rejections_skill ON evolution_rejections(skill_id);
CREATE INDEX IF NOT EXISTS idx_rejections_trigger ON evolution_rejections(trigger_type);
CREATE INDEX IF NOT EXISTS idx_rejections_time ON evolution_rejections(rejected_at);

CREATE TABLE IF NOT EXISTS evolution_constraints (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id            TEXT NOT NULL,
    constraint_text     TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    FOREIGN KEY(skill_id) REFERENCES skills(skill_id)
);

CREATE INDEX IF NOT EXISTS idx_constraints_skill ON evolution_constraints(skill_id);
CREATE INDEX IF NOT EXISTS idx_constraints_time ON evolution_constraints(created_at);
"""


class SkillStore(SkillVectorSyncMixin, SkillEvolutionTrackingMixin, SkillStoreQueries):
    """Simplified SQLite persistence for skill evolution.

    Architecture:
    - Write: async method → asyncio.to_thread → _xxx_sync → self._mu lock → self._conn
    - Read: sync method → self._reader() → temporary read-only connection (WAL parallel)
    - Complex queries: inherited from SkillStoreQueries mixin

    Lifecycle:
        store = SkillStore()
        await store.save_skill(record)
        record = store.get_skill(skill_id)
        store.close()

    Or use as async context manager:
        async with SkillStore() as store:
            await store.save_skill(record)
    """

    def __init__(
        self,
        db_path: Path | None = None,
        vector_store: VectorStore | None = None,
        embedding: EmbeddingProtocol | None = None,
    ) -> None:
        """Initialize skill store.

        Args:
            db_path: Path to SQLite database file. Defaults to .myrm/skills.db
            vector_store: Optional VectorStore for hybrid retrieval.
            embedding: Optional EmbeddingProtocol for hybrid retrieval.
        """
        if db_path is None:
            db_dir = Path.cwd() / ".myrm"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = db_dir / "skills.db"

        self._db_path = Path(db_path)
        self._mu = threading.Lock()
        self._closed = False
        self._vector_store = vector_store
        self._embedding = embedding
        self.VECTOR_COLLECTION_NAME = "skills_semantic"

        # Crash recovery
        self._cleanup_wal_on_startup()

        # Persistent write connection
        self._conn = self._make_connection(read_only=False)
        self._init_db()
        logger.debug("SkillStore ready at %s", self._db_path)

    def _make_connection(self, *, read_only: bool) -> sqlite3.Connection:
        """Create optimized SQLite connection.

        Configuration:
        - WAL mode: Concurrent reads + single writer
        - 30s timeout: Handle lock contention gracefully
        - 16MB cache: Reduce disk I/O
        - Foreign keys: Ensure referential integrity
        """
        from myrm_agent_harness.utils.db.sqlite import SQLiteProfile, harden_connection_sync

        conn = sqlite3.connect(
            str(self._db_path),
            timeout=30.0,
            check_same_thread=False,  # For asyncio.to_thread()
        )
        profile = SQLiteProfile(
            busy_timeout_ms=30000,
            cache_size=-16000,  # 16 MB
            temp_store_memory=True,
            read_only=read_only,
        )
        harden_connection_sync(conn, profile, db_path=self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _reader(self):
        """Open temporary read-only connection for parallel reads.

        WAL mode allows concurrent readers without blocking.
        Each read gets its own connection to avoid event loop blocking.
        """
        self._ensure_open()
        conn = self._make_connection(read_only=True)
        try:
            yield conn
        finally:
            conn.close()

    def _cleanup_wal_on_startup(self) -> None:
        """Crash recovery: drop orphaned WAL/SHM companions of an empty main DB."""
        from myrm_agent_harness.utils.db.sqlite import cleanup_orphan_wal

        cleanup_orphan_wal(self._db_path)

    @_db_retry()
    def _init_db(self) -> None:
        """Create tables (idempotent via IF NOT EXISTS) and run migrations."""
        with self._mu:
            self._conn.executescript(_DDL)
            self._migrate_add_traps_columns()
            self._conn.commit()

    def _migrate_add_traps_columns(self) -> None:
        """Add traps/verification_steps/evolution_locked columns for existing DBs."""
        cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(skills)").fetchall()
        }
        if "traps" not in cols:
            self._conn.execute(
                "ALTER TABLE skills ADD COLUMN traps TEXT NOT NULL DEFAULT '[]'"
            )
        if "verification_steps" not in cols:
            self._conn.execute(
                "ALTER TABLE skills ADD COLUMN verification_steps TEXT NOT NULL DEFAULT '[]'"
            )
        if "evolution_locked" not in cols:
            self._conn.execute(
                "ALTER TABLE skills ADD COLUMN evolution_locked INTEGER NOT NULL DEFAULT 0"
            )
        if "environment" not in cols:
            self._conn.execute("ALTER TABLE skills ADD COLUMN environment TEXT")

    def close(self) -> None:
        """Close persistent connection and checkpoint WAL.

        Performs WAL checkpoint to flush all data to main DB file.
        This ensures external tools see complete data.
        """
        if self._closed:
            return
        self._closed = True
        from myrm_agent_harness.utils.db.sqlite import checkpoint_truncate_sync

        checkpoint_truncate_sync(self._conn)
        with suppress(sqlite3.Error):
            self._conn.close()
        logger.debug("SkillStore closed (WAL checkpointed)")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.close()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("SkillStore is closed")

    # Write operations (async)
    @_db_retry()
    def _delete_skill_sync(self, skill_id: str) -> None:
        """Synchronous delete - called via asyncio.to_thread()."""
        with self._mu:
            self._conn.execute("DELETE FROM skills WHERE skill_id = ?", (skill_id,))
            self._conn.execute(
                "DELETE FROM execution_analyses WHERE skill_id = ?", (skill_id,)
            )
            self._conn.execute(
                "DELETE FROM evolution_rejections WHERE skill_id = ?", (skill_id,)
            )
            self._conn.execute(
                "DELETE FROM evolution_constraints WHERE skill_id = ?", (skill_id,)
            )
            self._conn.commit()

    async def delete_skill(self, skill_id: str) -> None:
        """Delete a skill from the database.

        Args:
            skill_id: The ID of the skill to delete.
        """
        self._ensure_open()
        await asyncio.to_thread(self._delete_skill_sync, skill_id)
        await self._delete_skill_from_vector(skill_id)

    async def delete_skills_by_agent(self, agent_id: str) -> int:
        """Delete all skills owned by a specific agent.
        
        Args:
            agent_id: The ID of the agent whose skills should be deleted.
            
        Returns:
            Number of skills deleted.
        """
        self._ensure_open()
        
        # Find all skills owned by this agent
        def _get_owned_skills() -> list[tuple[str, str]]:
            with self._reader() as conn:
                rows = conn.execute(
                    """
                    SELECT skill_id, path FROM skills 
                    WHERE json_extract(environment, '$.custom_tags.scope_agent_id') = ?
                    """,
                    (agent_id,)
                ).fetchall()
                return [(row["skill_id"], row["path"]) for row in rows]
                
        skill_data = await asyncio.to_thread(_get_owned_skills)
        if not skill_data:
            return 0
            
        import os
        import shutil
        from pathlib import Path
            
        for sid, spath in skill_data:
            # First, delete the physical file/folder if it exists
            if spath:
                try:
                    p = Path(spath)
                    if p.exists():
                        # SKILL.md is inside a folder named after the skill, we should delete the parent folder
                        # if it's the standard layout (e.g. workspace/skill_name/SKILL.md)
                        if p.name == "SKILL.md":
                            if p.parent.name not in ["workspace", "skills", ""]:
                                shutil.rmtree(p.parent, ignore_errors=True)
                            else:
                                logger.warning("Skipping rmtree on unsafe path: %s", p.parent)
                        else:
                            os.remove(p)
                except Exception as e:
                    logger.warning("Failed to physical delete skill %s at %s: %s", sid, spath, e)
                    
            # Then delete from database
            await self.delete_skill(sid)
            
        return len(skill_data)

    @_db_retry()
    def _save_skill_sync(self, record: SkillRecord) -> None:
        """Synchronous save - called via asyncio.to_thread()."""
        with self._mu:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO skills (
                    skill_id, name, description, content, path,
                    evolution_type, version, parent_id, change_summary,
                    lineage_created_at, lineage_created_by,
                    total_selections, applied_count, completed_count, success_count,
                    last_success_at, last_failure_at, consecutive_failures,
                    traps, verification_steps, environment,
                    created_at, updated_at, is_active, evolution_locked
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.skill_id,
                    record.name,
                    record.description,
                    record.content,
                    record.path,
                    record.lineage.evolution_type.value,
                    record.lineage.version,
                    record.lineage.parent_id,
                    record.lineage.change_summary,
                    record.lineage.created_at.isoformat(),
                    record.lineage.created_by,
                    record.metrics.total_selections,
                    record.metrics.applied_count,
                    record.metrics.completed_count,
                    record.metrics.success_count,
                    (
                        record.metrics.last_success_at.isoformat()
                        if record.metrics.last_success_at
                        else None
                    ),
                    (
                        record.metrics.last_failure_at.isoformat()
                        if record.metrics.last_failure_at
                        else None
                    ),
                    record.metrics.consecutive_failures,
                    json.dumps(record.traps, ensure_ascii=False),
                    json.dumps(record.verification_steps, ensure_ascii=False),
                    (
                        json.dumps(record.environment.to_dict(), ensure_ascii=False)
                        if record.environment
                        else None
                    ),
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    int(record.is_active),
                    int(record.evolution_locked),
                ),
            )
            self._conn.commit()

    async def save_skill(self, record: SkillRecord) -> None:
        """Save or update skill record.

        Args:
            record: SkillRecord to persist
        """
        self._ensure_open()
        await asyncio.to_thread(self._save_skill_sync, record)
        await self._sync_skill_to_vector(record)

    @_db_retry()
    def _update_metrics_sync(self, skill_id: str, metrics: SkillMetrics) -> None:
        """Synchronous metrics update."""
        with self._mu:
            self._conn.execute(
                """
                UPDATE skills SET
                    total_selections = ?,
                    applied_count = ?,
                    completed_count = ?,
                    success_count = ?,
                    last_success_at = ?,
                    last_failure_at = ?,
                    consecutive_failures = ?
                WHERE skill_id = ?
                """,
                (
                    metrics.total_selections,
                    metrics.applied_count,
                    metrics.completed_count,
                    metrics.success_count,
                    (
                        metrics.last_success_at.isoformat()
                        if metrics.last_success_at
                        else None
                    ),
                    (
                        metrics.last_failure_at.isoformat()
                        if metrics.last_failure_at
                        else None
                    ),
                    metrics.consecutive_failures,
                    skill_id,
                ),
            )
            self._conn.commit()

    async def update_metrics(self, skill_id: str, metrics: SkillMetrics) -> None:
        """Update skill quality metrics.

        Args:
            skill_id: Skill identifier
            metrics: Updated metrics
        """
        self._ensure_open()
        await asyncio.to_thread(self._update_metrics_sync, skill_id, metrics)

    @_db_retry()
    def _deactivate_skill_sync(self, skill_id: str) -> None:
        """Synchronous deactivation."""
        with self._mu:
            self._conn.execute(
                "UPDATE skills SET is_active = 0 WHERE skill_id = ?", (skill_id,)
            )
            self._conn.commit()

    async def deactivate_skill(self, skill_id: str) -> None:
        """Mark skill as inactive (for FIX evolution when creating new version).

        Args:
            skill_id: Skill identifier to deactivate
        """
        self._ensure_open()
        await asyncio.to_thread(self._deactivate_skill_sync, skill_id)
        await self._delete_skill_from_vector(skill_id)

    # Evolution lock operations
    @_db_retry()
    def _set_evolution_lock_sync(self, skill_id: str, *, locked: bool) -> None:
        """Synchronous evolution lock update."""
        with self._mu:
            self._conn.execute(
                "UPDATE skills SET evolution_locked = ? WHERE skill_id = ?",
                (int(locked), skill_id),
            )
            self._conn.commit()

    async def set_evolution_lock(self, skill_id: str, *, locked: bool) -> None:
        """Lock or unlock a skill's auto-evolution.

        Locked skills are skipped by EvolutionScreener, protecting
        user-edited content from being overwritten by auto-evolution.

        Args:
            skill_id: Skill identifier
            locked: True to lock (block auto-evolution), False to unlock
        """
        self._ensure_open()
        await asyncio.to_thread(self._set_evolution_lock_sync, skill_id, locked=locked)

    @_db_retry()
    def is_evolution_locked(self, skill_id: str) -> bool:
        """Check if a skill is locked from auto-evolution.

        Args:
            skill_id: Skill identifier

        Returns:
            True if locked, False if unlocked or skill not found
        """
        self._ensure_open()
        with self._reader() as conn:
            row = conn.execute(
                "SELECT evolution_locked FROM skills WHERE skill_id = ?", (skill_id,)
            ).fetchone()
            if not row:
                return False
            return bool(row["evolution_locked"])

    # Read operations (sync, use _reader())
    @_db_retry()
    def get_skill(self, skill_id: str) -> SkillRecord | None:
        """Load skill by ID.

        Args:
            skill_id: Skill identifier

        Returns:
            SkillRecord or None if not found
        """
        self._ensure_open()
        with self._reader() as conn:
            row = conn.execute(
                "SELECT * FROM skills WHERE skill_id = ?", (skill_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_record(dict(row))

    def _row_to_record(self, row: dict) -> SkillRecord:
        """Convert SQLite row to SkillRecord."""
        from datetime import datetime

        from myrm_agent_harness.agent.skills.evolution.core.types import (
            EnvironmentFingerprint,
            EvolutionType,
        )

        env_dict = (
            json.loads(row.get("environment")) if row.get("environment") else None
        )

        return SkillRecord(
            skill_id=row["skill_id"],
            name=row["name"],
            description=row["description"],
            content=row["content"],
            path=row["path"],
            lineage=SkillLineage(
                evolution_type=EvolutionType(row["evolution_type"]),
                version=row["version"],
                parent_id=row["parent_id"],
                change_summary=row["change_summary"],
                created_at=datetime.fromisoformat(row["lineage_created_at"]),
                created_by=row["lineage_created_by"],
            ),
            metrics=SkillMetrics(
                total_selections=row["total_selections"],
                applied_count=row["applied_count"],
                completed_count=row["completed_count"],
                success_count=row["success_count"],
                last_success_at=(
                    datetime.fromisoformat(row["last_success_at"])
                    if row["last_success_at"]
                    else None
                ),
                last_failure_at=(
                    datetime.fromisoformat(row["last_failure_at"])
                    if row["last_failure_at"]
                    else None
                ),
                consecutive_failures=row["consecutive_failures"],
            ),
            traps=json.loads(row.get("traps", "[]")),
            verification_steps=json.loads(row.get("verification_steps", "[]")),
            environment=(
                EnvironmentFingerprint.from_dict(env_dict) if env_dict else None
            ),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            is_active=bool(row["is_active"]),
            evolution_locked=bool(row.get("evolution_locked", 0)),
        )
