"""Orchestrates two-phase session archival, reliable boundary gating, and memory_diff auditing.

[INPUT]
- toolkits.memory.session_commit.models::CommitBoundaryKind, CommitPhase, CommitTaskStatus, MemoryDiffAudit,
  MemoryDiffChangeKind, MemoryDiffItem, MemoryDiffStats, SessionArchiveMessage, SessionCommitResult (POS:
  Types and models for session commit.)

[OUTPUT]
- SessionCommitTwoPhaseEngine: Orchestrates two-phase session archival, reliable boundary gating, and
  memory_diff auditing.

[POS]
Orchestrates two-phase session archival, reliable boundary gating, and memory_diff auditing.
"""

# [POS]: src/myrm_agent_harness/toolkits/memory/session_commit/two_phase_pipeline.py
# [INPUT]: .models (CommitBoundaryKind, CommitPhase, MemoryDiffAudit, MemoryDiffItem, MemoryDiffStats, SessionArchiveMessage, CommitTaskStatus, SessionCommitResult)
# [OUTPUT]: SessionCommitTwoPhaseEngine

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Mapping
from pathlib import Path

from myrm_agent_harness.toolkits.memory.session_commit.models import (
    CommitBoundaryKind,
    CommitPhase,
    CommitTaskStatus,
    MemoryDiffAudit,
    MemoryDiffChangeKind,
    MemoryDiffItem,
    MemoryDiffStats,
    SessionArchiveMessage,
    SessionCommitResult,
)

logger = logging.getLogger(__name__)


class SessionCommitTwoPhaseEngine:
    """Orchestrates two-phase session archival, reliable boundary gating, and memory_diff auditing."""

    def __init__(self, base_storage_dir: str | Path | None = None) -> None:
        self._base_dir = Path(base_storage_dir or ".sessions").resolve()
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, CommitTaskStatus] = {}

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def _get_next_archive_id(self, session_dir: Path) -> str:
        """Derive sequential archive ID (e.g. archive_001, archive_002)."""
        existing = [d.name for d in session_dir.iterdir() if d.is_dir() and d.name.startswith("archive_")]
        seq = len(existing) + 1
        return f"archive_{seq:03d}"

    def commit(
        self,
        session_id: str,
        messages: list[SessionArchiveMessage],
        boundary_kind: CommitBoundaryKind,
        metadata: Mapping[str, str] | None = None,
    ) -> SessionCommitResult:
        """Phase 1: Synchronously persist messages.jsonl in milliseconds and gate Phase 2."""
        session_dir = self._base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        archive_id = self._get_next_archive_id(session_dir)
        archive_dir = session_dir / archive_id
        archive_dir.mkdir(parents=True, exist_ok=True)

        # 1. Synchronously persist messages.jsonl
        messages_path = archive_dir / "messages.jsonl"
        with open(messages_path, "w", encoding="utf-8") as f:
            for msg in messages:
                row = {
                    "role": msg.role,
                    "content": msg.content,
                    "tool_calls": list(msg.tool_calls),
                    "tool_results": list(msg.tool_results),
                    "timestamp": msg.timestamp or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "referenced_uris": list(msg.referenced_uris),
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # 2. Gate Phase 2: only run full extraction if meeting reliable task boundaries
        should_schedule_phase2 = boundary_kind in (
            CommitBoundaryKind.TARGET_COMPLETED,
            CommitBoundaryKind.FAILURE_REPAIRED,
            CommitBoundaryKind.USER_CORRECTION,
            CommitBoundaryKind.CONTEXT_COMPACTION,
            CommitBoundaryKind.MANUAL,
        )

        task_status = CommitTaskStatus(
            task_id=task_id,
            session_id=session_id,
            archive_id=archive_id,
            phase=CommitPhase.PHASE1_SYNC_ARCHIVED,
            boundary_kind=boundary_kind,
            created_at=now_str,
            message_count=len(messages),
        )
        self._tasks[task_id] = task_status

        logger.info(
            "Phase 1 commit complete for session %s, archive %s, boundary=%s, phase2_scheduled=%s",
            session_id,
            archive_id,
            boundary_kind.value,
            should_schedule_phase2,
        )

        return SessionCommitResult(
            task_id=task_id,
            session_id=session_id,
            archive_id=archive_id,
            phase1_persisted=True,
            messages_path=str(messages_path),
            phase2_scheduled=should_schedule_phase2,
        )

    def execute_phase2_sync(
        self,
        task_id: str,
        memory_diff_items: list[MemoryDiffItem] | None = None,
    ) -> CommitTaskStatus:
        """Phase 2: Generate abstract/overview, write memory_diff.json, and stamp .done marker."""
        if task_id not in self._tasks:
            raise KeyError(f"Commit task '{task_id}' not found.")

        current = self._tasks[task_id]
        archive_dir = self._base_dir / current.session_id / current.archive_id
        if not archive_dir.exists():
            raise FileNotFoundError(f"Archive directory not found: {archive_dir}")

        # Update to extracting
        self._tasks[task_id] = CommitTaskStatus(
            task_id=current.task_id,
            session_id=current.session_id,
            archive_id=current.archive_id,
            phase=CommitPhase.PHASE2_EXTRACTING,
            boundary_kind=current.boundary_kind,
            created_at=current.created_at,
            message_count=current.message_count,
        )

        # 1. Write .abstract.md and .overview.md
        abstract_path = archive_dir / ".abstract.md"
        abstract_content = (
            f"# Session Abstract: {current.session_id}\n\n"
            f"- Boundary: {current.boundary_kind.value}\n"
            f"- Archived Messages: {current.message_count}\n"
            f"- Phase 2 Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
        )
        abstract_path.write_text(abstract_content, encoding="utf-8")

        overview_path = archive_dir / ".overview.md"
        overview_content = (
            f"# Execution Timeline Overview\n\n"
            f"Archival bundle for session `{current.session_id}` (`{current.archive_id}`).\n"
            f"Verified task closure under boundary policy `{current.boundary_kind.value}`.\n"
        )
        overview_path.write_text(overview_content, encoding="utf-8")

        # 2. Compile memory_diff.json audit (always outputs valid schema even on 0 changes)
        items = memory_diff_items or []
        added_count = sum(1 for i in items if i.change_kind == MemoryDiffChangeKind.ADDED)
        updated_count = sum(1 for i in items if i.change_kind == MemoryDiffChangeKind.UPDATED)
        superseded_count = sum(1 for i in items if i.change_kind == MemoryDiffChangeKind.SUPERSEDED)
        deleted_count = sum(1 for i in items if i.change_kind == MemoryDiffChangeKind.DELETED)

        stats = MemoryDiffStats(
            total_added=added_count,
            total_updated=updated_count,
            total_superseded=superseded_count,
            total_deleted=deleted_count,
        )

        diff_payload = {
            "session_id": current.session_id,
            "archive_id": current.archive_id,
            "task_id": current.task_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "boundary_kind": current.boundary_kind.value,
            "changes": [
                {
                    "change_kind": item.change_kind.value,
                    "memory_type": item.memory_type,
                    "item_id": item.item_id,
                    "before_summary": item.before_summary,
                    "after_summary": item.after_summary,
                    "timestamp": item.timestamp or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                for item in items
            ],
            "stats": {
                "total_added": stats.total_added,
                "total_updated": stats.total_updated,
                "total_superseded": stats.total_superseded,
                "total_deleted": stats.total_deleted,
            },
        }

        diff_path = archive_dir / "memory_diff.json"
        diff_path.write_text(json.dumps(diff_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        # 3. Write atomic .done marker
        done_path = archive_dir / ".done"
        done_marker = {
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "task_id": current.task_id,
            "total_memory_diffs": len(items),
        }
        done_path.write_text(json.dumps(done_marker, ensure_ascii=False), encoding="utf-8")

        completed_task = CommitTaskStatus(
            task_id=current.task_id,
            session_id=current.session_id,
            archive_id=current.archive_id,
            phase=CommitPhase.PHASE2_COMPLETED,
            boundary_kind=current.boundary_kind,
            created_at=current.created_at,
            completed_at=done_marker["completed_at"],
            message_count=current.message_count,
            diff_stats=stats,
        )
        self._tasks[task_id] = completed_task
        return completed_task

    def get_task(self, task_id: str) -> CommitTaskStatus | None:
        """Fetch current status of a commit task."""
        return self._tasks.get(task_id)

    def get_memory_diff(self, session_id: str, archive_id: str) -> MemoryDiffAudit | None:
        """Read persisted memory_diff.json from archive directory."""
        diff_file = self._base_dir / session_id / archive_id / "memory_diff.json"
        if not diff_file.exists():
            return None

        try:
            data = json.loads(diff_file.read_text(encoding="utf-8"))
            changes = tuple(
                MemoryDiffItem(
                    change_kind=MemoryDiffChangeKind(c["change_kind"]),
                    memory_type=c["memory_type"],
                    item_id=c["item_id"],
                    before_summary=c.get("before_summary"),
                    after_summary=c.get("after_summary"),
                    timestamp=c.get("timestamp"),
                )
                for c in data.get("changes", [])
            )
            raw_stats = data.get("stats", {})
            stats = MemoryDiffStats(
                total_added=raw_stats.get("total_added", 0),
                total_updated=raw_stats.get("total_updated", 0),
                total_superseded=raw_stats.get("total_superseded", 0),
                total_deleted=raw_stats.get("total_deleted", 0),
            )
            return MemoryDiffAudit(
                session_id=data["session_id"],
                archive_id=data["archive_id"],
                task_id=data["task_id"],
                timestamp=data["timestamp"],
                boundary_kind=CommitBoundaryKind(data["boundary_kind"]),
                changes=changes,
                stats=stats,
            )
        except Exception as e:
            logger.error("Failed to parse memory_diff.json: %s", e)
            return None

    def list_session_archives(self, session_id: str) -> list[str]:
        """List all archive directories for a session."""
        session_dir = self._base_dir / session_id
        if not session_dir.exists():
            return []
        return sorted([d.name for d in session_dir.iterdir() if d.is_dir() and d.name.startswith("archive_")])

    def is_archive_done(self, session_id: str, archive_id: str) -> bool:
        """Check whether .done marker exists for the archive."""
        done_path = self._base_dir / session_id / archive_id / ".done"
        return done_path.exists()
