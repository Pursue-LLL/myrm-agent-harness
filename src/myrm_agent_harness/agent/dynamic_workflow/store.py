"""WorkflowEventStore — SQLite-based durable execution cache for Dynamic Workflows.

[INPUT]
- utils.db.sqlite::CACHE, harden_connection_sync (POS: Unified SQLite hardening profile)
- dynamic_workflow.spawn_cache::SpawnCacheParams (POS: Cache fingerprint SSOT)

[OUTPUT]
- WorkflowEventStore: Persistent cache for sub-agent spawn results and orchestration scripts

[POS]
Provides L2 persistent caching for the Dynamic Workflow Engine. When a PTC script
crashes or the network reconnects, completed sub-agent results are replayed from
cache rather than re-executed. Cache hits require matching spawn parameters
(readonly, verification_mode, task_description, etc.).
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import cast

from myrm_agent_harness.agent.dynamic_workflow.spawn_cache import (
    SpawnCacheParams,
    spawn_cache_params_from_json,
)
from myrm_agent_harness.utils.db.sqlite import CACHE, harden_connection_sync


class WorkflowEventStore:
    """SQLite-based Event Sourcing for Dynamic Workflows.

    Records every sub-agent spawn result to allow durable execution and resume.
    Uses the Harness unified SQLite hardening profile (CACHE) for WAL journaling,
    concurrent write safety, and proper fallback when the filesystem cannot host WAL.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        harden_connection_sync(conn, CACHE, db_path=self.db_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS subagent_events (
                    workflow_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    agent_type TEXT NOT NULL,
                    task_description TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (workflow_id, task_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orchestration_scripts (
                    workflow_id TEXT PRIMARY KEY,
                    script_code TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(subagent_events)").fetchall()
            }
            if "spawn_params_json" not in columns:
                conn.execute(
                    "ALTER TABLE subagent_events ADD COLUMN spawn_params_json TEXT NOT NULL DEFAULT ''"
                )
            if "identity_hash" not in columns:
                conn.execute(
                    "ALTER TABLE subagent_events ADD COLUMN identity_hash TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_subagent_events_identity_hash
                ON subagent_events (identity_hash, created_at DESC)
                """
            )

    def get_cached_result(
        self,
        workflow_id: str,
        task_id: str,
        *,
        expected: SpawnCacheParams,
        allow_identity_fallback: bool = True,
    ) -> dict[str, object] | None:
        """Retrieve a cached result.

        L1: Exact match on (workflow_id, task_id).
        L2: If L1 misses, allow_identity_fallback is True, and expected.readonly is True,
            falls back to querying by identity_hash across previous runs/forks.
        """
        with self._connect() as conn:
            # L1: Exact match on (workflow_id, task_id)
            cursor = conn.execute(
                """
                SELECT result_json, spawn_params_json, agent_type, task_description
                FROM subagent_events
                WHERE workflow_id = ? AND task_id = ?
                """,
                (workflow_id, task_id),
            )
            row = cursor.fetchone()
            if row:
                (
                    result_json,
                    spawn_params_json,
                    stored_agent_type,
                    stored_task_description,
                ) = row
                if self._params_match(
                    expected=expected,
                    spawn_params_json=str(spawn_params_json or ""),
                    _stored_agent_type=str(stored_agent_type),
                    _stored_task_description=str(stored_task_description),
                ):
                    return cast("dict[str, object] | None", json.loads(result_json))

            # L2: Identity-hash fallback across runs/forks (strictly for readonly subagents)
            if allow_identity_fallback and expected.readonly:
                identity_hash = expected.fingerprint()
                cursor = conn.execute(
                    """
                    SELECT result_json, spawn_params_json, agent_type, task_description
                    FROM subagent_events
                    WHERE identity_hash = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (identity_hash,),
                )
                row = cursor.fetchone()
                if row:
                    (
                        result_json,
                        spawn_params_json,
                        stored_agent_type,
                        stored_task_description,
                    ) = row
                    if self._params_match(
                        expected=expected,
                        spawn_params_json=str(spawn_params_json or ""),
                        _stored_agent_type=str(stored_agent_type),
                        _stored_task_description=str(stored_task_description),
                    ):
                        try:
                            parsed = cast("dict[str, object]", json.loads(result_json))
                            # Only reuse successful cached results
                            if parsed.get("success") is True or (
                                not parsed.get("error") and "result" in parsed
                            ):
                                return parsed
                        except Exception:
                            pass

        return None

    def update_stored_result(
        self,
        workflow_id: str,
        task_id: str,
        result: dict[str, object],
    ) -> None:
        """Update cached spawn result JSON after post-execution merge."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE subagent_events
                SET result_json = ?
                WHERE workflow_id = ? AND task_id = ?
                """,
                (json.dumps(result), workflow_id, task_id),
            )

    @staticmethod
    def _params_match(
        *,
        expected: SpawnCacheParams,
        spawn_params_json: str,
        _stored_agent_type: str,
        _stored_task_description: str,
    ) -> bool:
        if spawn_params_json:
            stored = spawn_cache_params_from_json(spawn_params_json)
            if stored is None:
                return False
            return stored.fingerprint() == expected.fingerprint()

        return False

    def save_result(
        self,
        workflow_id: str,
        task_id: str,
        agent_type: str,
        task_description: str,
        result: dict[str, object],
        *,
        spawn_params: SpawnCacheParams,
    ) -> None:
        """Save a completed sub-agent result with spawn parameter fingerprint and identity_hash."""
        params_json = json.dumps(asdict(spawn_params), ensure_ascii=False)
        identity_hash = spawn_params.fingerprint()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO subagent_events
                (workflow_id, task_id, agent_type, task_description, result_json, spawn_params_json, identity_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow_id,
                    task_id,
                    agent_type,
                    task_description,
                    json.dumps(result),
                    params_json,
                    identity_hash,
                ),
            )

    def append_journal_entry(
        self,
        journal_path: str | Path,
        *,
        workflow_id: str,
        task_id: str,
        agent_type: str,
        task_description: str,
        result: dict[str, object],
        spawn_params: SpawnCacheParams,
    ) -> None:
        """Append a subagent execution event to workspace .workflow-journal.jsonl sidecar."""
        try:
            path = Path(journal_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "workflow_id": workflow_id,
                "task_id": task_id,
                "agent_type": agent_type,
                "task_description": task_description,
                "identity_hash": spawn_params.fingerprint(),
                "readonly": spawn_params.readonly,
                "verification_mode": spawn_params.verification_mode,
                "success": bool(result.get("success", False)),
                "result": result,
            }
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def save_orchestration_script(self, workflow_id: str, script_code: str) -> None:
        """Persist generated orchestration script for approval resume."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO orchestration_scripts (workflow_id, script_code)
                VALUES (?, ?)
                """,
                (workflow_id, script_code),
            )

    def get_orchestration_script(self, workflow_id: str) -> str | None:
        """Load a previously generated orchestration script."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT script_code FROM orchestration_scripts WHERE workflow_id = ?",
                (workflow_id,),
            )
            row = cursor.fetchone()
            if row and isinstance(row[0], str):
                return row[0]
        return None
