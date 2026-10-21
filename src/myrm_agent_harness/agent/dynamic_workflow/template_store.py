"""Named workflow template persistence for Dynamic Workflow reruns.

[INPUT]
- dynamic_workflow.store::WorkflowEventStore (POS: per-run orchestration script source for save-from-run)
- dynamic_workflow.template_validation (POS: script validation and placeholder substitution helpers)

[OUTPUT]
- WorkflowTemplateStore: CRUD for user-named orchestration scripts
- compute_workflow_id: stable workflow_id from chat_id + message_id

[POS]
User-facing template library persistence layer. Distinct from per-run orchestration_scripts cache.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.agent.dynamic_workflow.store import WorkflowEventStore
from myrm_agent_harness.agent.dynamic_workflow.template_validation import (
    compute_script_hash,
    extract_required_agent_types,
    validate_orchestration_script,
)
from myrm_agent_harness.utils.db.sqlite import CACHE, harden_connection_sync

_TEMPLATE_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


def compute_workflow_id(chat_id: str, message_id: str) -> str:
    hash_input = f"{chat_id}:{message_id}".encode()
    return f"wf_{hashlib.md5(hash_input).hexdigest()[:12]}"


@dataclass(frozen=True, slots=True)
class WorkflowTemplateRecord:
    template_id: str
    display_name: str
    script_code: str
    script_hash: str
    trust_latch: bool
    required_agent_types: tuple[str, ...]
    created_at: str
    updated_at: str


def normalize_template_id(raw: str) -> str:
    cleaned = raw.strip().lower().replace("_", "-")
    cleaned = re.sub(r"[^a-z0-9-]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned


def is_valid_template_id(template_id: str) -> bool:
    return bool(_TEMPLATE_ID_PATTERN.match(template_id))


class WorkflowTemplateStore:
    """CRUD for user-named orchestration scripts."""

    def __init__(self, db_path: str | Path) -> None:
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
                CREATE TABLE IF NOT EXISTS workflow_templates (
                    template_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    script_code TEXT NOT NULL,
                    script_hash TEXT NOT NULL,
                    trust_latch INTEGER NOT NULL DEFAULT 0,
                    required_agent_types_json TEXT NOT NULL DEFAULT '[]',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> WorkflowTemplateRecord:
        required_raw = json.loads(str(row["required_agent_types_json"] or "[]"))
        required = tuple(str(item) for item in required_raw) if isinstance(required_raw, list) else ()
        return WorkflowTemplateRecord(
            template_id=str(row["template_id"]),
            display_name=str(row["display_name"]),
            script_code=str(row["script_code"]),
            script_hash=str(row["script_hash"]),
            trust_latch=bool(row["trust_latch"]),
            required_agent_types=required,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def list_templates(self) -> list[WorkflowTemplateRecord]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT template_id, display_name, script_code, script_hash, trust_latch,
                       required_agent_types_json, created_at, updated_at
                FROM workflow_templates
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_template(self, template_id: str) -> WorkflowTemplateRecord | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT template_id, display_name, script_code, script_hash, trust_latch,
                       required_agent_types_json, created_at, updated_at
                FROM workflow_templates
                WHERE template_id = ?
                """,
                (template_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def save_template(
        self,
        *,
        template_id: str,
        display_name: str,
        script_code: str,
        trust_latch: bool = False,
    ) -> WorkflowTemplateRecord:
        normalized_id = normalize_template_id(template_id)
        if not is_valid_template_id(normalized_id):
            raise ValueError("Invalid template_id slug.")

        ok, error = validate_orchestration_script(script_code)
        if not ok:
            raise ValueError(error or "Invalid orchestration script.")

        script_hash = compute_script_hash(script_code)
        required = extract_required_agent_types(script_code)
        now = datetime.now(UTC).isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workflow_templates (
                    template_id, display_name, script_code, script_hash, trust_latch,
                    required_agent_types_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    script_code = excluded.script_code,
                    script_hash = excluded.script_hash,
                    trust_latch = excluded.trust_latch,
                    required_agent_types_json = excluded.required_agent_types_json,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_id,
                    display_name.strip() or normalized_id,
                    script_code,
                    script_hash,
                    1 if trust_latch else 0,
                    json.dumps(required, ensure_ascii=False),
                    now,
                    now,
                ),
            )

        record = self.get_template(normalized_id)
        if record is None:
            raise RuntimeError("Failed to persist workflow template.")
        return record

    def delete_template(self, template_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM workflow_templates WHERE template_id = ?",
                (template_id,),
            )
            return cursor.rowcount > 0

    def save_from_orchestration_run(
        self,
        *,
        chat_id: str,
        message_id: str,
        template_id: str,
        display_name: str,
        trust_latch: bool = False,
        event_store: WorkflowEventStore | None = None,
    ) -> WorkflowTemplateRecord:
        workflow_id = compute_workflow_id(chat_id, message_id)
        script_source = event_store or WorkflowEventStore(self.db_path)
        script_code = script_source.get_orchestration_script(workflow_id)
        if script_code is None:
            raise ValueError("Orchestration script for this run was not found.")
        return self.save_template(
            template_id=template_id,
            display_name=display_name,
            script_code=script_code,
            trust_latch=trust_latch,
        )
