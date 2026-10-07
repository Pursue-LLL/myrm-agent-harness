# [POS]: myrm_agent_harness.toolkits.memory.authoritative_conclusions.store
# [INPUT]: models.py
# [OUTPUT]: AuthoritativeConclusionStore

"""In-memory and indexed repository for authoritative conclusions and audit trails.

P0 delivery for Item 111 in topic_01 memory roadmap.
Provides CRUD, lifecycle state transitions (proposed -> confirmed -> deprecated),
physical deletion for PII compliance, and full immutable audit logging.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.authoritative_conclusions.models import (
    AuthoritativeConclusion,
    ConclusionAuditRecord,
    ConclusionStatus,
    ConclusionToolAction,
)

logger = logging.getLogger(__name__)


class AuthoritativeConclusionStore:
    """Store managing authoritative conclusions and associated audit ledgers."""

    def __init__(self) -> None:
        self._conclusions: dict[str, AuthoritativeConclusion] = {}
        self._audits: list[ConclusionAuditRecord] = []

    def write_conclusion(
        self,
        content: str,
        peer_id: str,
        scope_tag: str = "general",
        conclusion_id: str | None = None,
        operator_peer_id: str | None = None,
        auto_confirm: bool = True,
        rationale: str = "",
    ) -> AuthoritativeConclusion:
        """Declare a new authoritative conclusion and record audit event."""
        cid = conclusion_id or f"conc_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(UTC).isoformat()
        status = ConclusionStatus.CONFIRMED if auto_confirm else ConclusionStatus.PROPOSED
        confirmed_at = now_iso if auto_confirm else None

        conclusion = AuthoritativeConclusion(
            conclusion_id=cid,
            peer_id=peer_id,
            content=content.strip(),
            status=status,
            scope_tag=scope_tag.strip().lower(),
            created_at=now_iso,
            confirmed_at=confirmed_at,
        )
        self._conclusions[cid] = conclusion

        # Record audit log
        audit = ConclusionAuditRecord(
            audit_id=f"audit_{uuid.uuid4().hex[:12]}",
            conclusion_id=cid,
            action=ConclusionToolAction.WRITE,
            operator_peer_id=operator_peer_id or peer_id,
            previous_status=None,
            new_status=status,
            rationale=rationale or "Explicit authoritative conclusion declared",
            timestamp=now_iso,
        )
        self._audits.append(audit)
        logger.info(
            "Declared authoritative conclusion %s by peer %s [status=%s, scope=%s]",
            cid,
            peer_id,
            status,
            scope_tag,
        )
        return conclusion

    def get_conclusion(self, conclusion_id: str) -> AuthoritativeConclusion | None:
        """Look up a conclusion by identifier."""
        return self._conclusions.get(conclusion_id)

    def list_conclusions(
        self,
        peer_id: str | None = None,
        status: ConclusionStatus | None = None,
        scope_tag: str | None = None,
        keyword: str | None = None,
    ) -> list[AuthoritativeConclusion]:
        """List conclusions with multi-dimensional filtering and keyword search."""
        results: list[AuthoritativeConclusion] = []
        kw = keyword.lower().strip() if keyword else None

        for conc in self._conclusions.values():
            if peer_id is not None and conc.peer_id != peer_id:
                continue
            if status is not None and conc.status != status:
                continue
            if scope_tag is not None and conc.scope_tag != scope_tag.lower():
                continue
            if kw and kw not in conc.content.lower() and kw not in conc.scope_tag:
                continue
            results.append(conc)

        return results

    def deprecate_conclusion(
        self,
        conclusion_id: str,
        operator_peer_id: str,
        rationale: str = "",
    ) -> AuthoritativeConclusion | None:
        """Mark an active conclusion as deprecated with audit trail."""
        conc = self._conclusions.get(conclusion_id)
        if not conc:
            return None

        prev_status = conc.status
        now_iso = datetime.now(UTC).isoformat()
        conc.status = ConclusionStatus.DEPRECATED
        conc.deprecated_at = now_iso

        audit = ConclusionAuditRecord(
            audit_id=f"audit_{uuid.uuid4().hex[:12]}",
            conclusion_id=conclusion_id,
            action=ConclusionToolAction.DEPRECATE,
            operator_peer_id=operator_peer_id,
            previous_status=prev_status,
            new_status=ConclusionStatus.DEPRECATED,
            rationale=rationale or "Conclusion deprecated by authority",
            timestamp=now_iso,
        )
        self._audits.append(audit)
        logger.info("Deprecated conclusion %s by operator %s", conclusion_id, operator_peer_id)
        return conc

    def delete_conclusion(
        self,
        conclusion_id: str,
        operator_peer_id: str,
        rationale: str = "",
    ) -> bool:
        """Physically erase a conclusion for PII removal while logging deletion event."""
        conc = self._conclusions.pop(conclusion_id, None)
        if not conc:
            return False

        now_iso = datetime.now(UTC).isoformat()
        audit = ConclusionAuditRecord(
            audit_id=f"audit_{uuid.uuid4().hex[:12]}",
            conclusion_id=conclusion_id,
            action=ConclusionToolAction.DELETE,
            operator_peer_id=operator_peer_id,
            previous_status=conc.status,
            new_status=None,
            rationale=rationale or "Physical conclusion erasure for policy/PII compliance",
            timestamp=now_iso,
        )
        self._audits.append(audit)
        logger.warning(
            "Physically deleted conclusion %s by operator %s [reason: %s]",
            conclusion_id,
            operator_peer_id,
            rationale,
        )
        return True

    def list_audits(self, conclusion_id: str | None = None) -> list[ConclusionAuditRecord]:
        """Query audit ledger records, optionally filtered by conclusion ID."""
        if conclusion_id is None:
            return list(self._audits)
        return [a for a in self._audits if a.conclusion_id == conclusion_id]
