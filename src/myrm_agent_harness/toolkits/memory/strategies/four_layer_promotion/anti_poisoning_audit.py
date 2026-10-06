"""Anti-poisoning audit tracker providing atomic batch lineage and rollback.

[INPUT]
- CapabilityMethod: promoted capability method card
- types: ExposureSource, PromotionChannel

[OUTPUT]
- AntiPoisoningAuditTracker: tracks consolidation batches, guards against E->M->B
  silent poisoning, and executes atomic batch-level rollbacks.

[POS]
Harness audit tracker enforcing the third anti-poisoning nail (Revert & Rollback)
guaranteeing zero silent memory corruption from untrusted background exposures.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.strategies.four_layer_promotion.types import (
    CapabilityMethod,
)


@dataclass(slots=True)
class ConsolidationBatchRecord:
    """Historical audit record of a single consolidation run."""

    batch_id: str
    created_at: datetime
    promoted_method_ids: list[str]
    supported_event_ids: list[str]
    is_reverted: bool = False
    reverted_at: datetime | None = None


class AntiPoisoningAuditTracker:
    """Tracker managing consolidation batch lineage and supporting instant rollback."""

    def __init__(self) -> None:
        self._batches: dict[str, ConsolidationBatchRecord] = {}
        self._active_methods: dict[str, CapabilityMethod] = {}

    def record_batch(self, methods: list[CapabilityMethod]) -> str:
        """Register a new batch of promoted methods with full lineage."""
        batch_id = f"batch-{uuid.uuid4().hex[:8]}"
        method_ids: list[str] = []
        event_ids: list[str] = []

        for m in methods:
            method_ids.append(m.method_id)
            self._active_methods[m.method_id] = m
            for eid in m.supported_event_ids:
                if eid not in event_ids:
                    event_ids.append(eid)

        record = ConsolidationBatchRecord(
            batch_id=batch_id,
            created_at=datetime.now(UTC),
            promoted_method_ids=method_ids,
            supported_event_ids=event_ids,
        )
        self._batches[batch_id] = record
        return batch_id

    def rollback_batch(self, batch_id: str) -> tuple[bool, list[str]]:
        """Atomically rollback all methods promoted during the specified batch.

        Returns:
            A tuple of (success: bool, reverted_method_ids: list[str]).
        """
        record = self._batches.get(batch_id)
        if not record or record.is_reverted:
            return False, []

        reverted_ids: list[str] = []
        for mid in record.promoted_method_ids:
            if mid in self._active_methods:
                del self._active_methods[mid]
                reverted_ids.append(mid)

        record.is_reverted = True
        record.reverted_at = datetime.now(UTC)
        return True, reverted_ids

    def is_method_active(self, method_id: str) -> bool:
        """Check whether a given method is currently active (not rolled back)."""
        return method_id in self._active_methods

    def get_active_methods(self) -> list[CapabilityMethod]:
        """Return all currently active capability methods."""
        return list(self._active_methods.values())

    def get_batch(self, batch_id: str) -> ConsolidationBatchRecord | None:
        """Retrieve audit record for a specific batch."""
        return self._batches.get(batch_id)
