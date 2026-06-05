import json
import sqlite3
from pathlib import Path

_BUSY_TIMEOUT_MS = 5000


class WorkflowEventStore:
    """SQLite-based Event Sourcing for Dynamic Workflows.

    Records every sub-agent spawn result to allow durable execution and resume.
    Uses WAL journal mode for concurrent read/write safety when multiple
    sub-agents complete in parallel via ThreadPoolExecutor PTC scripts.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=_BUSY_TIMEOUT_MS / 1000)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        return conn

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
                "SELECT result_json FROM subagent_events WHERE workflow_id = ? AND task_id = ?",
                (workflow_id, task_id)
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
