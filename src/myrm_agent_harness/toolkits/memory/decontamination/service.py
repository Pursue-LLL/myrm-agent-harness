"""[POS]: src/myrm_agent_harness/toolkits/memory/decontamination/service.py
[INPUT]: Database paths and unified provenance attestation and decontamination requests.
[OUTPUT]: MemoryProvenanceDecontaminationService unifying attestation, active quarantine, and snapshot rollbacks.
"""

from pathlib import Path

from .attestation import ProvenanceAttestationManager
from .detector import DecontaminationGuard
from .models import (
    DecontaminationReport,
    DecontaminationStatus,
    MemoryProvenanceAttestation,
    MemorySnapshotRecord,
    ProvenanceSourceKind,
    RollbackReport,
)
from .rollback import MemorySnapshotRollbackEngine


class MemoryProvenanceDecontaminationService:
    """Unified service coordinating memory provenance certification, quarantine, and rollbacks."""

    def __init__(self, db_path: Path | str = ":memory:") -> None:
        self.attestation_mgr = ProvenanceAttestationManager(db_path=db_path)
        self.guard = DecontaminationGuard(db_path=db_path)
        self.rollback_engine = MemorySnapshotRollbackEngine(db_path=db_path)

    def issue_attestation(
        self,
        memory_id: str,
        source_kind: ProvenanceSourceKind,
        session_id: str,
        turn_index: int = 0,
        evidence_snippet: str = "",
        author_identity: str = "user",
    ) -> MemoryProvenanceAttestation:
        """Issue tamper-evident cryptographic provenance attestation for a memory entry."""
        return self.attestation_mgr.issue_attestation(
            memory_id=memory_id,
            source_kind=source_kind,
            session_id=session_id,
            turn_index=turn_index,
            evidence_snippet=evidence_snippet,
            author_identity=author_identity,
        )

    def verify_attestation(self, attestation: MemoryProvenanceAttestation) -> bool:
        """Verify signature integrity of provenance attestation."""
        return self.attestation_mgr.verify_attestation(attestation)

    def get_attestation(self, memory_id: str) -> MemoryProvenanceAttestation | None:
        """Retrieve provenance attestation by memory ID."""
        return self.attestation_mgr.get_attestation(memory_id)

    def evaluate_and_guard(
        self,
        memory_id: str,
        content: str,
        source_kind: str = "",
    ) -> DecontaminationReport:
        """Scan candidate memory content, quarantining if poison patterns are identified."""
        return self.guard.evaluate_content(
            memory_id=memory_id,
            content=content,
            source_kind=source_kind,
        )

    def quarantine_memory(self, memory_id: str, reason: str) -> None:
        """Explicitly isolate memory under quarantine barrier."""
        self.guard.quarantine_memory(memory_id=memory_id, reason=reason)

    def pardon_memory(self, memory_id: str) -> None:
        """Lift quarantine on memory entry."""
        self.guard.pardon_memory(memory_id=memory_id)

    def is_quarantined(self, memory_id: str) -> bool:
        """Check if memory entry is currently blocked by quarantine."""
        return self.guard.is_quarantined(memory_id=memory_id)

    def get_status(self, memory_id: str) -> DecontaminationStatus:
        """Retrieve current sanitation status for a memory ID."""
        return self.guard.get_status(memory_id=memory_id)

    def filter_clean_memories(self, memory_ids: list[str]) -> list[str]:
        """Screen out all quarantined memories during retrieval assembly."""
        return self.guard.filter_clean_memories(memory_ids=memory_ids)

    def list_quarantined(self, limit: int = 50) -> list[dict[str, str | float]]:
        """List currently quarantined memories."""
        return self.guard.list_quarantined(limit=limit)

    def create_snapshot(
        self,
        label: str,
        active_memory_ids: list[str],
    ) -> MemorySnapshotRecord:
        """Capture point-in-time snapshot baseline of active memories."""
        return self.rollback_engine.create_snapshot(
            label=label,
            active_memory_ids=active_memory_ids,
        )

    def get_snapshot(self, snapshot_id: str) -> MemorySnapshotRecord | None:
        """Retrieve snapshot baseline by ID."""
        return self.rollback_engine.get_snapshot(snapshot_id)

    def list_snapshots(self, limit: int = 50) -> list[MemorySnapshotRecord]:
        """List recently captured memory snapshots."""
        return self.rollback_engine.list_snapshots(limit=limit)

    def rollback_to_snapshot(
        self,
        snapshot_id: str,
        current_memory_ids: list[str],
    ) -> RollbackReport:
        """Revert memory state back to snapshot baseline by quarantining subsequent additions."""
        return self.rollback_engine.rollback_to_snapshot(
            snapshot_id=snapshot_id,
            current_memory_ids=current_memory_ids,
            guard=self.guard,
        )

    def decontaminate_session(self, session_id: str) -> int:
        """Purge and quarantine all memories associated with a corrupted session."""
        return self.rollback_engine.quarantine_by_session(
            session_id=session_id,
            attestation_mgr=self.attestation_mgr,
            guard=self.guard,
        )

    def close(self) -> None:
        """Close underlying SQLite database connections."""
        for mgr in (self.attestation_mgr, self.guard, self.rollback_engine):
            if mgr._conn is not None:
                mgr._conn.close()
                mgr._conn = None
