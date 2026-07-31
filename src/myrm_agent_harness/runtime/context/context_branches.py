"""Context snapshot branch manifest for GUI restore flows.

[INPUT]
- runtime.execution_paths::PERSISTENT_ROOT (POS: persistent volume root)

[OUTPUT]
- list_context_branches / append_context_branch / get_context_branch / ContextBranchRecord

[POS]
Volume-backed branch manifest pointing at existing conversation snapshots.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from myrm_agent_harness.runtime.execution_paths import PERSISTENT_ROOT

_BRANCH_FILENAME = "branches.json"
_MAX_BRANCHES = 20


@dataclass(frozen=True, slots=True)
class ContextBranchRecord:
    branch_id: str
    label: str
    snapshot_path: str
    created_at: str


def _branch_path(session_id: str) -> Path:
    return Path(PERSISTENT_ROOT) / ".context" / session_id / _BRANCH_FILENAME


def get_context_branch(session_id: str, branch_id: str) -> ContextBranchRecord | None:
    """Return one bookmark record by id, or None when missing."""
    if not session_id or not branch_id:
        return None
    for item in list_context_branches(session_id):
        if item.branch_id == branch_id:
            return item
    return None


def list_context_branches(session_id: str) -> list[ContextBranchRecord]:
    if not session_id:
        return []
    path = _branch_path(session_id)
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    records: list[ContextBranchRecord] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        branch_id = item.get("branch_id")
        label = item.get("label")
        snapshot_path = item.get("snapshot_path")
        created_at = item.get("created_at")
        if (
            isinstance(branch_id, str)
            and isinstance(label, str)
            and isinstance(snapshot_path, str)
            and isinstance(created_at, str)
        ):
            records.append(
                ContextBranchRecord(
                    branch_id=branch_id,
                    label=label,
                    snapshot_path=snapshot_path,
                    created_at=created_at,
                )
            )
    return records


def append_context_branch(
    session_id: str,
    *,
    snapshot_path: str,
    label: str,
) -> ContextBranchRecord:
    if not session_id:
        raise ValueError("session_id is required")
    normalized_snapshot = snapshot_path.strip()
    normalized_label = label.strip() or "Snapshot branch"
    if not normalized_snapshot:
        raise ValueError("snapshot_path is required")

    existing = list_context_branches(session_id)
    record = ContextBranchRecord(
        branch_id=uuid.uuid4().hex[:12],
        label=normalized_label,
        snapshot_path=normalized_snapshot,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    merged = [*existing, record]
    if len(merged) > _MAX_BRANCHES:
        merged = merged[-_MAX_BRANCHES:]
    serialized = [
        {
            "branch_id": item.branch_id,
            "label": item.label,
            "snapshot_path": item.snapshot_path,
            "created_at": item.created_at,
        }
        for item in merged
    ]
    path = _branch_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8")
    return record
