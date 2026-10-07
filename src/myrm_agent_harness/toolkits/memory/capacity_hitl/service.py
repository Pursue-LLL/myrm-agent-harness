"""[POS]: src/myrm_agent_harness/toolkits/memory/capacity_hitl/service.py
[INPUT]: Candidate memory entries, capacity metrics, and human resolution decisions.
[OUTPUT]: SQLite-backed HITL candidate management service with CAS concurrency protection.
"""

import json
import sqlite3
import threading
import time
from pathlib import Path

from myrm_agent_harness.toolkits.memory.capacity_hitl.detector import (
    CapacityThresholdDetector,
)
from myrm_agent_harness.toolkits.memory.capacity_hitl.models import (
    CandidateActionKind,
    CapacityStatusReport,
    HitlCandidateProposal,
    HitlCandidateStatus,
    MemoryEntryRef,
)
from myrm_agent_harness.toolkits.memory.capacity_hitl.proposer import (
    MergeArchiveCandidateProposer,
)


class CapacityHitlService:
    """Thread-safe SQLite service for human-in-the-loop near-capacity candidate management."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        default_max_entries: int = 1000,
    ) -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._detector = CapacityThresholdDetector(default_max_entries=default_max_entries)
        self._proposer = MergeArchiveCandidateProposer()

        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA busy_timeout = 5000;")
            self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS capacity_hitl_proposals (
            candidate_id TEXT PRIMARY KEY,
            action_kind TEXT NOT NULL,
            source_entries TEXT NOT NULL,
            proposed_content TEXT NOT NULL,
            reason TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL,
            created_at REAL NOT NULL,
            resolved_at REAL,
            reviewer_note TEXT
        );

        CREATE TABLE IF NOT EXISTS archived_memory_entries (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            tags TEXT NOT NULL,
            archived_at REAL NOT NULL,
            origin_candidate_id TEXT NOT NULL
        );
        """)
        self._conn.commit()

    def check_capacity_status(
        self, total_entries: int, max_entries: int | None = None
    ) -> CapacityStatusReport:
        """Inspect capacity utilization against threshold ladders."""
        pending_count = len(self.list_proposals(status=HitlCandidateStatus.PENDING))
        return self._detector.evaluate(
            total_entries=total_entries,
            max_entries=max_entries,
            pending_candidates=pending_count,
        )

    def generate_and_store_proposals(
        self,
        entries: list[dict[str, str | int | float | list[str]]],
        max_entries: int | None = None,
        max_proposals: int = 10,
    ) -> list[HitlCandidateProposal]:
        """Generate remediation candidates and persist into HITL proposal queue."""
        proposals = self._proposer.propose_candidates(
            entries=entries, max_proposals=max_proposals
        )

        with self._lock:
            for p in proposals:
                source_json = json.dumps(
                    [e.model_dump() for e in p.source_entries], ensure_ascii=False
                )
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO capacity_hitl_proposals (
                        candidate_id, action_kind, source_entries, proposed_content,
                        reason, confidence, status, created_at, resolved_at, reviewer_note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        p.candidate_id,
                        p.action_kind.value,
                        source_json,
                        p.proposed_content,
                        p.reason,
                        p.confidence,
                        p.status.value,
                        p.created_at,
                        p.resolved_at,
                        p.reviewer_note,
                    ),
                )
            self._conn.commit()

        return proposals

    def list_proposals(
        self, status: HitlCandidateStatus | None = None
    ) -> list[HitlCandidateProposal]:
        """Query stored HITL candidate proposals."""
        query = (
            "SELECT candidate_id, action_kind, source_entries, proposed_content, "
            "reason, confidence, status, created_at, resolved_at, reviewer_note "
            "FROM capacity_hitl_proposals"
        )
        params: list[str] = []
        if status is not None:
            query += " WHERE status = ?"
            params.append(status.value)
        query += " ORDER BY created_at DESC"

        with self._lock:
            cursor = self._conn.execute(query, params)
            rows = cursor.fetchall()

        results: list[HitlCandidateProposal] = []
        for r in rows:
            source_raw: list[dict[str, str | int | float | list[str]]] = json.loads(
                str(r["source_entries"])
            )
            entries = [
                MemoryEntryRef(
                    id=str(e["id"]),
                    content=str(e["content"]),
                    content_hash=str(e["content_hash"]),
                    tags=[str(t) for t in e.get("tags", [])]
                    if isinstance(e.get("tags"), list)
                    else [],
                    created_at=float(e.get("created_at", 0.0)),
                    access_count=int(e.get("access_count", 0)),
                )
                for e in source_raw
            ]
            results.append(
                HitlCandidateProposal(
                    candidate_id=str(r["candidate_id"]),
                    action_kind=CandidateActionKind(str(r["action_kind"])),
                    source_entries=entries,
                    proposed_content=str(r["proposed_content"]),
                    reason=str(r["reason"]),
                    confidence=float(r["confidence"]),
                    status=HitlCandidateStatus(str(r["status"])),
                    created_at=float(r["created_at"]),
                    resolved_at=float(r["resolved_at"]) if r["resolved_at"] else None,
                    reviewer_note=str(r["reviewer_note"]) if r["reviewer_note"] else None,
                )
            )
        return results

    def resolve_candidate(
        self,
        candidate_id: str,
        decision: HitlCandidateStatus,
        reviewer_note: str = "",
        current_entry_hashes: dict[str, str] | None = None,
    ) -> tuple[bool, str, HitlCandidateProposal | None]:
        """Resolve a candidate with CAS concurrency check against original entry hashes."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM capacity_hitl_proposals WHERE candidate_id = ?",
                (candidate_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return False, f"Proposal '{candidate_id}' not found", None

            # CAS check
            source_raw: list[dict[str, str | int | float | list[str]]] = json.loads(
                str(row["source_entries"])
            )
            if current_entry_hashes is not None:
                for entry_dict in source_raw:
                    eid = str(entry_dict["id"])
                    recorded_hash = str(entry_dict["content_hash"])
                    latest_hash = current_entry_hashes.get(eid)
                    if latest_hash and latest_hash != recorded_hash:
                        # Stale proposal detected
                        now = time.time()
                        self._conn.execute(
                            "UPDATE capacity_hitl_proposals SET status = ?, resolved_at = ?, reviewer_note = ? WHERE candidate_id = ?",
                            (
                                HitlCandidateStatus.EXPIRED.value,
                                now,
                                "CAS violation: source content modified concurrently.",
                                candidate_id,
                            ),
                        )
                        self._conn.commit()
                        return False, "源条目内容已被外部并发更新，该提案已失效标记为 EXPIRED", None

            now = time.time()
            self._conn.execute(
                "UPDATE capacity_hitl_proposals SET status = ?, resolved_at = ?, reviewer_note = ? WHERE candidate_id = ?",
                (decision.value, now, reviewer_note, candidate_id),
            )

            # If approved archive action, persist into soft archive table
            if decision == HitlCandidateStatus.APPROVED and str(row["action_kind"]) == CandidateActionKind.ARCHIVE.value:
                for entry_dict in source_raw:
                    self._conn.execute(
                        """
                        INSERT OR REPLACE INTO archived_memory_entries (
                            id, content, tags, archived_at, origin_candidate_id
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            str(entry_dict["id"]),
                            str(entry_dict["content"]),
                            json.dumps(entry_dict.get("tags", []), ensure_ascii=False),
                            now,
                            candidate_id,
                        ),
                    )

            self._conn.commit()

        # Reload updated proposal
        updated = [p for p in self.list_proposals() if p.candidate_id == candidate_id]
        return True, "决策已成功应用并安全持久化", (updated[0] if updated else None)

    def list_archived_entries(self) -> list[dict[str, str | float]]:
        """List entries archived safely in cold storage."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT id, content, tags, archived_at, origin_candidate_id FROM archived_memory_entries ORDER BY archived_at DESC"
            )
            rows = cursor.fetchall()
        return [
            {
                "id": str(r["id"]),
                "content": str(r["content"]),
                "tags": str(r["tags"]),
                "archived_at": float(r["archived_at"]),
                "origin_candidate_id": str(r["origin_candidate_id"]),
            }
            for r in rows
        ]

    def close(self) -> None:
        """Close sqlite connection."""
        with self._lock:
            self._conn.close()
