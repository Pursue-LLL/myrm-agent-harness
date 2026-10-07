"""[POS]: src/myrm_agent_harness/toolkits/memory/decisions/store.py
[INPUT]: DecisionDatabase, IngestionNoiseFilter, LineageEngine, and StructuredPriorityReranker.
[OUTPUT]: Unified high-level EngineeringDecisionStore providing lifecycle, confirmation gate, and recall APIs.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from .db import DecisionDatabase
from .lineage import DecisionLineageEngine
from .models import (
    CandidateStatus,
    DecisionRecallHit,
    DecisionRecord,
    DecisionStatus,
    PendingDecisionCandidate,
)
from .noise_filter import IngestionNoiseFilter
from .reranker import StructuredPriorityReranker


class EngineeringDecisionStore:
    """High-level facade orchestrating decisions as state, lineage, and priority recall."""

    def __init__(self, db_path: str | Path, auto_approve: bool = False) -> None:
        self.db = DecisionDatabase(db_path)
        self.auto_approve = auto_approve

    async def stage_candidate(
        self,
        session_id: str,
        title: str,
        text: str,
        rationale: str = "",
        supersedes_id: str | None = None,
        project_key: str = "default",
    ) -> PendingDecisionCandidate | DecisionRecord:
        """Stage a proposed decision in pending buffer or auto-approve if configured."""
        if IngestionNoiseFilter.is_noise(text):
            raise ValueError("Input decision statement is classified as system instruction noise.")

        clean_text = IngestionNoiseFilter.sanitize(text)
        candidate_id = f"cand_{uuid.uuid4().hex[:10]}"
        now_iso = datetime.now(UTC).isoformat()

        candidate = PendingDecisionCandidate(
            id=candidate_id,
            session_id=session_id,
            title=title.strip(),
            text=clean_text,
            rationale=rationale.strip(),
            supersedes_id=supersedes_id,
            status=CandidateStatus.PENDING,
            project_key=project_key,
            created_at=now_iso,
            updated_at=now_iso,
        )

        if self.auto_approve:
            return await self._commit_candidate_to_decision(candidate)

        await self.db.save_candidate(candidate)
        return candidate

    async def approve_candidate(self, candidate_id: str) -> DecisionRecord:
        """Approve a pending candidate, transitioning it to an active DecisionRecord."""
        candidate = await self.db.get_candidate(candidate_id)
        if not candidate:
            raise KeyError(f"Candidate '{candidate_id}' not found.")
        if candidate.status != CandidateStatus.PENDING:
            raise ValueError(f"Candidate '{candidate_id}' is already {candidate.status}.")

        return await self._commit_candidate_to_decision(candidate)

    async def reject_candidate(self, candidate_id: str) -> PendingDecisionCandidate:
        """Reject and invalidate a pending candidate."""
        candidate = await self.db.get_candidate(candidate_id)
        if not candidate:
            raise KeyError(f"Candidate '{candidate_id}' not found.")

        now_iso = datetime.now(UTC).isoformat()
        updated = candidate.model_copy(
            update={"status": CandidateStatus.REJECTED, "updated_at": now_iso}
        )
        await self.db.save_candidate(updated)
        return updated

    async def record_decision(
        self,
        title: str,
        text: str,
        rationale: str = "",
        supersedes_id: str | None = None,
        scope: str = "project",
        project_key: str = "default",
        source_event: str | None = None,
    ) -> DecisionRecord:
        """Directly record an active decision, verifying lineage DAG constraints."""
        if IngestionNoiseFilter.is_noise(text):
            raise ValueError("Decision text identified as system instruction noise.")

        clean_text = IngestionNoiseFilter.sanitize(text)
        decision_id = f"dec_{uuid.uuid4().hex[:10]}"
        now_iso = datetime.now(UTC).isoformat()

        # DAG cycle validation against existing stored records
        cache: dict[str, DecisionRecord | None] = {}

        def get_sync(rec_id: str) -> DecisionRecord | None:
            return cache.get(rec_id)

        # Pre-populate ancestor cache
        curr = supersedes_id
        while curr:
            rec = await self.db.get_decision(curr)
            cache[curr] = rec
            curr = rec.supersedes_id if rec else None

        DecisionLineageEngine.validate_transition(decision_id, supersedes_id, get_sync)

        new_record = DecisionRecord(
            id=decision_id,
            title=title.strip(),
            text=clean_text,
            rationale=rationale.strip(),
            status=DecisionStatus.ACTIVE,
            supersedes_id=supersedes_id,
            superseded_by=None,
            scope=scope,
            project_key=project_key,
            source_event=source_event,
            created_at=now_iso,
            updated_at=now_iso,
        )

        # If superseding an older decision, update old record status
        if supersedes_id:
            old_record = await self.db.get_decision(supersedes_id)
            if old_record:
                updated_old = DecisionLineageEngine.apply_supersession(
                    old_record, new_record, now_iso
                )
                await self.db.save_decision(updated_old)

        await self.db.save_decision(new_record)
        return new_record

    async def _commit_candidate_to_decision(
        self, candidate: PendingDecisionCandidate
    ) -> DecisionRecord:
        """Helper to convert candidate to decision record and update candidate status."""
        now_iso = datetime.now(UTC).isoformat()
        decision = await self.record_decision(
            title=candidate.title,
            text=candidate.text,
            rationale=candidate.rationale,
            supersedes_id=candidate.supersedes_id,
            project_key=candidate.project_key,
            source_event=f"#cand_{candidate.id}",
        )
        approved_cand = candidate.model_copy(
            update={"status": CandidateStatus.APPROVED, "updated_at": now_iso}
        )
        await self.db.save_candidate(approved_cand)
        return decision

    async def discard_decision(self, decision_id: str) -> DecisionRecord:
        """Mark an active or superseded decision as discarded."""
        record = await self.db.get_decision(decision_id)
        if not record:
            raise KeyError(f"Decision '{decision_id}' not found.")

        now_iso = datetime.now(UTC).isoformat()
        updated = record.model_copy(
            update={"status": DecisionStatus.DISCARDED, "updated_at": now_iso}
        )
        await self.db.save_decision(updated)
        return updated

    async def get_lineage(self, decision_id: str) -> list[DecisionRecord]:
        """Fetch the chronological evolution history leading to this decision."""
        cache: dict[str, DecisionRecord | None] = {}
        curr: str | None = decision_id
        while curr:
            rec = await self.db.get_decision(curr)
            cache[curr] = rec
            curr = rec.supersedes_id if rec else None

        return DecisionLineageEngine.trace_ancestry(
            decision_id, lambda r_id: cache.get(r_id)
        )

    async def search_priority(
        self, query: str, project_key: str = "default", limit: int = 5
    ) -> list[DecisionRecallHit]:
        """Retrieve top structured decisions with overlap matching, MMR, and ChronoRank."""
        records = await self.db.list_decisions(project_key=project_key, limit=200)
        return StructuredPriorityReranker.score_and_rank(query, records, limit=limit)

    async def format_priority_prompt(
        self, query: str, project_key: str = "default", limit: int = 5
    ) -> str:
        """Retrieve and format high-priority decisions into markdown prompt section."""
        hits = await self.search_priority(query, project_key, limit)
        return StructuredPriorityReranker.format_prompt_block(hits)
