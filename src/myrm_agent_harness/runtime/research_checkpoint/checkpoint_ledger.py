"""Persistent research checkpoint ledger for long-horizon study workflows.

Maintains relational checkpoint vectors tracking completed chapters, pending work,
and cumulative resource expenditure across process lifecycles.

[OUTPUT]
- ResearchCheckpointLedger: SQLite-backed state ledger for research checkpoints.

[INPUT]
- __future__
- json
- sqlite3
- time
- pathlib
- typing

[OUTPUT]
- ResearchCheckpointLedger

[POS]
Persistent research checkpoint ledger for long-horizon study workflows.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import cast

from myrm_agent_harness.runtime.research_checkpoint.checkpoint_types import (
    ResearchCheckpoint,
    ResearchStatus,
)


class ResearchCheckpointLedger:
    """Manages transactional state checkpoints for long-running research tasks."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            self.db_path: str = ":memory:"
        elif str(db_path) == ":memory:":
            self.db_path = ":memory:"
        else:
            p = Path(db_path).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            self.db_path = str(p)

        self._conn: sqlite3.Connection = sqlite3.connect(
            self.db_path, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    current_status TEXT NOT NULL,
                    completed_chapters_json TEXT NOT NULL,
                    pending_chapters_json TEXT NOT NULL,
                    total_tokens_consumed INTEGER NOT NULL DEFAULT 0,
                    total_duration_ms REAL NOT NULL DEFAULT 0.0,
                    timestamp REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_chk_task ON research_checkpoints(task_id, timestamp DESC);
                """
            )

    def commit_checkpoint(self, checkpoint: ResearchCheckpoint) -> None:
        """Persist a research checkpoint into the ledger."""
        completed_json = json.dumps(list(checkpoint.completed_chapters))
        pending_json = json.dumps(list(checkpoint.pending_chapters))

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO research_checkpoints (
                    checkpoint_id, task_id, session_id, current_status,
                    completed_chapters_json, pending_chapters_json,
                    total_tokens_consumed, total_duration_ms, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(checkpoint_id) DO UPDATE SET
                    current_status = excluded.current_status,
                    completed_chapters_json = excluded.completed_chapters_json,
                    pending_chapters_json = excluded.pending_chapters_json,
                    total_tokens_consumed = excluded.total_tokens_consumed,
                    total_duration_ms = excluded.total_duration_ms,
                    timestamp = excluded.timestamp
                """,
                (
                    checkpoint.checkpoint_id,
                    checkpoint.task_id,
                    checkpoint.session_id,
                    checkpoint.current_status.value,
                    completed_json,
                    pending_json,
                    checkpoint.total_tokens_consumed,
                    checkpoint.total_duration_ms,
                    checkpoint.timestamp,
                ),
            )

    def get_latest_checkpoint(self, task_id: str) -> ResearchCheckpoint | None:
        """Fetch the most recent valid checkpoint for a research task."""
        cursor = self._conn.execute(
            """
            SELECT checkpoint_id, task_id, session_id, current_status,
                   completed_chapters_json, pending_chapters_json,
                   total_tokens_consumed, total_duration_ms, timestamp
            FROM research_checkpoints
            WHERE task_id = ?
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (task_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        comp_list = json.loads(str(row["completed_chapters_json"]))
        pend_list = json.loads(str(row["pending_chapters_json"]))

        return ResearchCheckpoint(
            checkpoint_id=str(row["checkpoint_id"]),
            task_id=str(row["task_id"]),
            session_id=str(row["session_id"]),
            current_status=ResearchStatus(str(row["current_status"])),
            completed_chapters=tuple(int(x) for x in comp_list),
            pending_chapters=tuple(int(x) for x in pend_list),
            total_tokens_consumed=int(cast(int, row["total_tokens_consumed"])),
            total_duration_ms=float(cast(float, row["total_duration_ms"])),
            timestamp=float(cast(float, row["timestamp"])),
        )

    def advance_chapter_progress(
        self,
        task_id: str,
        finished_chapter_index: int,
        tokens_used: int = 0,
        duration_ms: float = 0.0,
    ) -> ResearchCheckpoint:
        """Advance the checkpoint state machine by marking a chapter finished."""
        latest = self.get_latest_checkpoint(task_id)
        if latest is None:
            raise KeyError(f"No existing checkpoint found for research task '{task_id}'")

        # Move chapter from pending to completed
        new_completed = sorted(set((*latest.completed_chapters, finished_chapter_index)))
        new_pending = [idx for idx in latest.pending_chapters if idx != finished_chapter_index]
        new_pending.sort()

        new_status = (
            ResearchStatus.COMPLETED if not new_pending else ResearchStatus.IN_PROGRESS
        )

        new_chk = ResearchCheckpoint(
            checkpoint_id=f"chk_{task_id}_{int(time.time() * 1000)}",
            task_id=task_id,
            session_id=latest.session_id,
            current_status=new_status,
            completed_chapters=tuple(new_completed),
            pending_chapters=tuple(new_pending),
            total_tokens_consumed=latest.total_tokens_consumed + tokens_used,
            total_duration_ms=latest.total_duration_ms + duration_ms,
            timestamp=time.time(),
        )
        self.commit_checkpoint(new_chk)
        return new_chk

    def close(self) -> None:
        """Close SQLite connection."""
        self._conn.close()
