"""Gate evaluating factual contradictions and routing low-confidence candidates into quarantine.

[INPUT]
- toolkits.memory.fact_supersession.models::ContradictionQuarantineItem, TemporalFactRecord,
  TemporalFactStatus (POS: Types and models for fact supersession.)
- toolkits.memory.fact_supersession.supersession_chain::FactSupersessionChainEngine (POS: Engine managing fact
  lifecycle, explicit supersession chains, and valid-time interval queries.)

[OUTPUT]
- ContradictionQuarantineGate: Gate evaluating factual contradictions and routing low-confidence candidates
  into quarantine.

[POS]
Gate evaluating factual contradictions and routing low-confidence candidates into quarantine.
"""

from __future__ import annotations

import uuid

from myrm_agent_harness.toolkits.memory.fact_supersession.models import (
    ContradictionQuarantineItem,
    TemporalFactRecord,
    TemporalFactStatus,
)
from myrm_agent_harness.toolkits.memory.fact_supersession.supersession_chain import (
    FactSupersessionChainEngine,
)


class ContradictionQuarantineGate:
    """Gate evaluating factual contradictions and routing low-confidence candidates into quarantine."""

    def __init__(self, conflict_threshold: float = 0.85) -> None:
        self._conflict_threshold = conflict_threshold
        self._quarantine: dict[str, ContradictionQuarantineItem] = {}

    def ingest_fact(
        self,
        new_fact: TemporalFactRecord,
        chain_engine: FactSupersessionChainEngine,
    ) -> tuple[str, TemporalFactRecord | ContradictionQuarantineItem]:
        """Ingest a fact, detecting contradictions against active facts and routing appropriately."""
        # Check active facts with matching subject and predicate
        existing_active = chain_engine.query_active(
            subject=new_fact.subject,
            predicate=new_fact.predicate,
        )

        conflicting_fact: TemporalFactRecord | None = None
        for cand in existing_active:
            if cand.object_value.strip().lower() != new_fact.object_value.strip().lower():
                conflicting_fact = cand
                break

        if not conflicting_fact:
            # No contradiction found, record normally
            recorded = chain_engine.record_fact(new_fact)
            return "RECORDED", recorded

        # Contradiction detected
        if new_fact.confidence >= self._conflict_threshold:
            # High confidence: automatically supersede conflicting fact
            _, superseded_new = chain_engine.supersede(
                old_fact_id=conflicting_fact.fact_id,
                new_fact=new_fact,
            )
            return "SUPERSEDED", superseded_new

        # Low confidence: route to quarantine ledger
        new_fact.status = TemporalFactStatus.QUARANTINED
        quarantine_id = f"quar-{uuid.uuid4().hex[:8]}"
        q_item = ContradictionQuarantineItem(
            quarantine_id=quarantine_id,
            new_fact=new_fact,
            conflicting_fact_id=conflicting_fact.fact_id,
            conflict_score=round(abs(conflicting_fact.confidence - new_fact.confidence), 3),
        )
        self._quarantine[quarantine_id] = q_item
        return "QUARANTINED", q_item

    def resolve_quarantine(
        self,
        quarantine_id: str,
        approve_override: bool,
        chain_engine: FactSupersessionChainEngine,
    ) -> tuple[bool, TemporalFactRecord | None]:
        """Human review action: approve override to supersede, or reject candidate."""
        item = self._quarantine.get(quarantine_id)
        if not item:
            raise KeyError(f"Quarantine item '{quarantine_id}' not found.")

        if approve_override:
            item.status = "approved"
            item.new_fact.status = TemporalFactStatus.ACTIVE
            _, active_new = chain_engine.supersede(
                old_fact_id=item.conflicting_fact_id,
                new_fact=item.new_fact,
            )
            return True, active_new
        else:
            item.status = "rejected"
            item.new_fact.status = TemporalFactStatus.ARCHIVED
            return False, None

    def list_quarantined(self, status: str | None = "quarantined") -> list[ContradictionQuarantineItem]:
        """List quarantine items matching status filter."""
        items: list[ContradictionQuarantineItem] = []
        for q in self._quarantine.values():
            if status is None or q.status == status:
                items.append(q)
        return sorted(items, key=lambda q: q.detected_at, reverse=True)
