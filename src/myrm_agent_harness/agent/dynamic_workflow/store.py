"""WorkflowEventStore — SQLite-based durable execution cache for Dynamic Workflows.

[INPUT]
- utils.db.sqlite::CACHE, harden_connection_sync (POS: Unified SQLite hardening profile)

[OUTPUT]
- WorkflowEventStore: Persistent cache for sub-agent spawn results

[POS]
Provides L2 persistent caching for the Dynamic Workflow Engine. When a PTC script
crashes or the network reconnects, completed sub-agent results are replayed from
cache rather than re-executed. Connections use harden_connection_sync(CACHE) for
WAL journaling, concurrent write safety, and filesystem fallback.
"""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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

    def get_cached_result(self, workflow_id: str, task_id: str) -> dict[str, object] | None:
        """Retrieve a previously completed sub-agent result."""
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT result_json FROM subagent_events WHERE workflow_id = ? AND task_id = ?", (workflow_id, task_id)
            )
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        return None

    def save_result(
        self,
        workflow_id: str,
        task_id: str,
        agent_type: str,
        task_description: str,
        result: dict[str, object],
    ) -> None:
        """Save a completed sub-agent result."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO subagent_events
                (workflow_id, task_id, agent_type, task_description, result_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (workflow_id, task_id, agent_type, task_description, json.dumps(result)),
            )
