# [INPUT]: CachePartitionedContextBundle, CachePreservingEventEnvelopeProtocol, DormantSnapshot, EventAuditRecord, EventAuditTrailManager, EventEnvelopePayload, EventSourceTier, SandboxedSleepWakeLifecycleEngine, Sequence
# [OUTPUT]: CachePreservingEventEnvelopeAndColdStartHydrationSuite, CachePreservingEventSuite
# [POS]: agent/context_management/event_cache_preservation/cache_preserving_event_suite.py

"""Unified facade suite for cache-preserving event envelopes, sandboxed sleep-wake, and cold-start hydration.

[INPUT]
- CachePartitionedContextBundle, DormantSnapshot, EventAuditRecord, EventEnvelopePayload, EventSourceTier: Models.
- CachePreservingEventEnvelopeProtocol, EventAuditTrailManager, SandboxedSleepWakeLifecycleEngine: Core engines.
- Sequence: Standard typing.

[OUTPUT]
- CachePreservingEventEnvelopeAndColdStartHydrationSuite: Main facade for Item 316.
- CachePreservingEventSuite: Convenient alias.

[POS]
Main entry facade coordinating prefix cache protection, sub-500ms hydration, and audit trail decoupling.
"""

from __future__ import annotations

import datetime
from typing import Sequence
import uuid

from .cache_preserving_event_envelope_protocol import CachePreservingEventEnvelopeProtocol
from .event_audit_trail_manager import EventAuditTrailManager
from .event_envelope_types import (
    CachePartitionedContextBundle,
    DormantSnapshot,
    EventAuditRecord,
    EventEnvelopePayload,
    EventSourceTier,
    HydrationState,
)
from .sandboxed_sleep_wake_lifecycle_engine import SandboxedSleepWakeLifecycleEngine


class CachePreservingEventEnvelopeAndColdStartHydrationSuite:
    """Unified facade managing event-driven prompt caching economics and sandbox lifecycle."""

    def __init__(self) -> None:
        self._protocol = CachePreservingEventEnvelopeProtocol()
        self._lifecycle_engine = SandboxedSleepWakeLifecycleEngine(self._protocol)
        self._audit_manager = EventAuditTrailManager()

    def create_event_envelope(
        self,
        payload_text: str,
        source: EventSourceTier = EventSourceTier.MCP_PUSH_EVENT,
        priority: str = "normal",
        event_id: str = "",
    ) -> EventEnvelopePayload:
        """Create a standardized isolated event payload envelope."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        eid = event_id or f"evt-{uuid.uuid4().hex[:8]}"
        return EventEnvelopePayload(
            event_id=eid,
            source=source,
            timestamp_iso=now_iso,
            priority=priority,
            payload_text=payload_text,
        )

    def partition_context(
        self,
        static_prefix: str,
        conversation_history: Sequence[str],
        event_envelope: EventEnvelopePayload | None = None,
    ) -> CachePartitionedContextBundle:
        """Assemble a 2-tier context guaranteeing static prefix cache preservation with tail event frame."""
        return self._protocol.partition_context(
            static_prefix=static_prefix,
            conversation_history=conversation_history,
            event_payload=event_envelope,
        )

    def freeze_dormant_sandbox(
        self,
        session_id: str,
        static_prefix: str,
        conversation_history: Sequence[str],
    ) -> DormantSnapshot:
        """Hibernate sandbox into a compact snapshot (<10MB) during idle periods."""
        return self._lifecycle_engine.create_dormant_snapshot(
            session_id=session_id,
            static_prefix=static_prefix,
            conversation_history=conversation_history,
        )

    def wake_and_hydrate(
        self,
        snapshot: DormantSnapshot,
        conversation_history: Sequence[str],
        incoming_event: EventEnvelopePayload | None = None,
    ) -> tuple[CachePartitionedContextBundle, float]:
        """Wake up dormant sandbox and hydrate context within 500ms budget."""
        return self._lifecycle_engine.hydrate_and_wake(
            snapshot=snapshot,
            conversation_history=conversation_history,
            incoming_event=incoming_event,
        )

    def record_and_evaluate_audit(
        self,
        event: EventEnvelopePayload,
        summary: str = "",
        force_promote_to_user: bool = False,
    ) -> EventAuditRecord:
        """Log event in audit trail without cluttering user conversation window."""
        return self._audit_manager.record_event(
            event=event,
            summary=summary,
            force_promote_to_user=force_promote_to_user,
        )

    def list_audit_records(
        self,
        only_promoted: bool = False,
        limit: int = 50,
    ) -> Sequence[EventAuditRecord]:
        """Retrieve recent event audit trail items."""
        return self._audit_manager.list_audit_trail(
            only_promoted=only_promoted,
            limit=limit,
        )


CachePreservingEventSuite = CachePreservingEventEnvelopeAndColdStartHydrationSuite
