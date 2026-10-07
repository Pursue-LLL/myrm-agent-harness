# [POS]: myrm_agent_harness.toolkits.memory.tiered_consensus.manager
# [INPUT]: ConsensusScopeTier, ProposalStatus, TieredMemoryRecord, ConsensusAuditLog, compute_content_fingerprint
# [OUTPUT]: TieredConsensusManager

"""Manager engine governing tiered memory hierarchy and proposal consensus lifecycle.

Provides scoping enforcement, idempotent proposal deduplication, anti-self-approval gates,
and immutable lifecycle transition audit trails.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.tiered_consensus.models import (
    ConsensusAuditLog,
    ConsensusScopeTier,
    ProposalStatus,
    TieredMemoryRecord,
    compute_content_fingerprint,
)

logger = logging.getLogger(__name__)


class TieredConsensusManager:
    """In-memory coordinator for tiered memory boundaries and consensus approval workflows."""

    def __init__(self) -> None:
        self._records: dict[str, TieredMemoryRecord] = {}
        self._fingerprint_index: dict[tuple[ConsensusScopeTier, str], str] = {}
        self._audits: list[ConsensusAuditLog] = []

    def propose_record(
        self,
        scope_tier: ConsensusScopeTier | str,
        content: str,
        owner_peer_id: str,
        project_id: str | None = None,
        rationale: str = "",
        auto_approve_personal_project: bool = True,
    ) -> TieredMemoryRecord:
        """Create a new tiered memory record with tier-specific governance rules."""
        tier = ConsensusScopeTier(scope_tier) if isinstance(scope_tier, str) else scope_tier
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("Memory content cannot be empty.")

        # Enforce project boundary integrity
        if tier == ConsensusScopeTier.PROJECT and not project_id:
            raise ValueError("project_id is strictly required for project tier records.")

        fingerprint = compute_content_fingerprint(clean_content)
        index_key = (tier, fingerprint)

        # Idempotent deduplication against existing proposed or active records
        existing_id = self._fingerprint_index.get(index_key)
        if existing_id and existing_id in self._records:
            existing_record = self._records[existing_id]
            if existing_record.status in (ProposalStatus.PROPOSED, ProposalStatus.APPROVED):
                logger.info(
                    "Idempotent proposal deduplicated for tier '%s', returning existing record '%s'",
                    tier.value,
                    existing_id,
                )
                return existing_record

        # Determine initial lifecycle status
        if tier in (ConsensusScopeTier.PERSONAL, ConsensusScopeTier.PROJECT) and auto_approve_personal_project:
            initial_status = ProposalStatus.APPROVED
        else:
            initial_status = ProposalStatus.PROPOSED

        record_id = f"mem_tier_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(UTC).isoformat()
        record = TieredMemoryRecord(
            record_id=record_id,
            scope_tier=tier,
            content=clean_content,
            content_fingerprint=fingerprint,
            owner_peer_id=owner_peer_id.strip(),
            project_id=project_id.strip() if project_id else None,
            status=initial_status,
            version=1,
            rationale=rationale.strip(),
            created_at=now_iso,
            updated_at=now_iso,
        )

        self._records[record_id] = record
        self._fingerprint_index[index_key] = record_id

        # Record immutable audit
        audit = ConsensusAuditLog(
            audit_id=f"audit_{uuid.uuid4().hex[:10]}",
            record_id=record_id,
            action="propose",
            operator_peer_id=owner_peer_id.strip(),
            reason=rationale or f"Initial proposal created in {tier.value} tier",
            timestamp=now_iso,
        )
        self._audits.append(audit)
        return record

    def approve_proposal(
        self,
        record_id: str,
        approver_peer_id: str,
        reason: str = "",
    ) -> TieredMemoryRecord:
        """Promote a proposed draft to approved status with anti-self-approval enforcement."""
        record = self.get_record(record_id)
        if not record:
            raise KeyError(f"Memory record '{record_id}' not found.")

        if record.status != ProposalStatus.PROPOSED:
            raise ValueError(f"Cannot approve record in status '{record.status.value}', expected 'proposed'.")

        # Anti-self-approval gate: Prevent agent from self-approving their own team consensus proposal
        approver = approver_peer_id.strip()
        if (
            record.scope_tier == ConsensusScopeTier.TEAM_CONSENSUS
            and record.owner_peer_id.startswith("agent_")
            and approver == record.owner_peer_id
        ):
            raise PermissionError(
                f"Agent '{record.owner_peer_id}' cannot self-approve its own team consensus proposal. "
                "Human or administrator authorization required."
            )

        now_iso = datetime.now(UTC).isoformat()
        record.status = ProposalStatus.APPROVED
        record.updated_at = now_iso

        self._audits.append(
            ConsensusAuditLog(
                audit_id=f"audit_{uuid.uuid4().hex[:10]}",
                record_id=record_id,
                action="approve",
                operator_peer_id=approver,
                reason=reason or "Explicit owner approval granted",
                timestamp=now_iso,
            )
        )
        return record

    def reject_proposal(
        self,
        record_id: str,
        approver_peer_id: str,
        reason: str = "",
    ) -> TieredMemoryRecord:
        """Reject and retire an unverified proposal."""
        record = self.get_record(record_id)
        if not record:
            raise KeyError(f"Memory record '{record_id}' not found.")

        now_iso = datetime.now(UTC).isoformat()
        record.status = ProposalStatus.REJECTED
        record.updated_at = now_iso

        self._audits.append(
            ConsensusAuditLog(
                audit_id=f"audit_{uuid.uuid4().hex[:10]}",
                record_id=record_id,
                action="reject",
                operator_peer_id=approver_peer_id.strip(),
                reason=reason or "Proposal rejected by reviewer",
                timestamp=now_iso,
            )
        )
        return record

    def revoke_consensus(
        self,
        record_id: str,
        operator_peer_id: str,
        reason: str = "",
        superseded_by: str | None = None,
    ) -> TieredMemoryRecord:
        """Revoke a previously approved consensus record with optional supersession linking."""
        record = self.get_record(record_id)
        if not record:
            raise KeyError(f"Memory record '{record_id}' not found.")

        now_iso = datetime.now(UTC).isoformat()
        record.status = ProposalStatus.REVOKED
        if superseded_by:
            record.superseded_by = superseded_by.strip()
        record.updated_at = now_iso

        self._audits.append(
            ConsensusAuditLog(
                audit_id=f"audit_{uuid.uuid4().hex[:10]}",
                record_id=record_id,
                action="revoke",
                operator_peer_id=operator_peer_id.strip(),
                reason=reason or "Consensus revoked by operator",
                timestamp=now_iso,
            )
        )
        return record

    def get_record(self, record_id: str) -> TieredMemoryRecord | None:
        """Retrieve memory record by identifier."""
        return self._records.get(record_id)

    def query_records(
        self,
        scope_tier: ConsensusScopeTier | str | None = None,
        status: ProposalStatus | str | None = None,
        project_id: str | None = None,
        owner_peer_id: str | None = None,
        include_proposed: bool = False,
    ) -> list[TieredMemoryRecord]:
        """Query memory records with tier scoping and default safety filtering."""
        target_tier = ConsensusScopeTier(scope_tier) if isinstance(scope_tier, str) else scope_tier
        target_status = ProposalStatus(status) if isinstance(status, str) else status

        results: list[TieredMemoryRecord] = []
        for r in self._records.values():
            if target_tier and r.scope_tier != target_tier:
                continue
            if project_id and r.project_id != project_id:
                continue
            if owner_peer_id and r.owner_peer_id != owner_peer_id:
                continue

            if target_status:
                if r.status != target_status:
                    continue
            else:
                # Default safety gate: Do not leak unapproved proposed records in team consensus
                if (
                    r.scope_tier == ConsensusScopeTier.TEAM_CONSENSUS
                    and not include_proposed
                    and r.status != ProposalStatus.APPROVED
                ):
                    continue

            results.append(r)

        return results

    def get_audit_trail(self, record_id: str | None = None) -> list[ConsensusAuditLog]:
        """Retrieve audit history filtered optionally by target record."""
        if not record_id:
            return list(self._audits)
        return [a for a in self._audits if a.record_id == record_id]
