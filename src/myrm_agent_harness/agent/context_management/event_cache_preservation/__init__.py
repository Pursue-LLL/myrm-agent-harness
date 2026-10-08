# [INPUT]: None
# [OUTPUT]: CachePartitionedContextBundle, CachePreservingEventEnvelopeAndColdStartHydrationSuite, CachePreservingEventEnvelopeProtocol, CachePreservingEventSuite, DormantSnapshot, EventAuditRecord, EventAuditTrailManager, EventEnvelopePayload, EventSourceTier, HydrationState, SandboxedSleepWakeLifecycleEngine
# [POS]: agent/context_management/event_cache_preservation/__init__.py

"""Cache-preserving event envelope and cold-start hydration package.

[INPUT]
- None (Package root exports).

[OUTPUT]
- CachePartitionedContextBundle: 2-tier context separating static prefix from ephemeral event frame.
- CachePreservingEventEnvelopeAndColdStartHydrationSuite: Main unified facade for Item 316.
- CachePreservingEventEnvelopeProtocol: Enforces static prefix boundary and appends events strictly to tail.
- CachePreservingEventSuite: Convenient alias.
- DormantSnapshot: Serialized hibernation state (<10MB) for frozen sandboxes.
- EventAuditRecord: Separate audit trail preventing high-volume events from polluting chat windows.
- EventAuditTrailManager: Records event trails and selectively promotes critical alerts to human UI.
- EventEnvelopePayload: Structured payload encapsulated into an ephemeral event frame.
- EventSourceTier: Origin tier of asynchronous push events (MCP push, webhook, manual, cron).
- HydrationState: Lifecycle states (ACTIVE_RUNNING, DORMANT_SLEEP, HYDRATING).
- SandboxedSleepWakeLifecycleEngine: Freezes inactive sandboxes and hydrates context in sub-500ms.

[POS]
Package entry point for Item 316 CachePreservingEventEnvelopeAndColdStartHydrationSuite.
"""

from .cache_preserving_event_envelope_protocol import CachePreservingEventEnvelopeProtocol
from .cache_preserving_event_suite import (
    CachePreservingEventEnvelopeAndColdStartHydrationSuite,
    CachePreservingEventSuite,
)
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

__all__ = [
    "CachePartitionedContextBundle",
    "CachePreservingEventEnvelopeAndColdStartHydrationSuite",
    "CachePreservingEventEnvelopeProtocol",
    "CachePreservingEventSuite",
    "DormantSnapshot",
    "EventAuditRecord",
    "EventAuditTrailManager",
    "EventEnvelopePayload",
    "EventSourceTier",
    "HydrationState",
    "SandboxedSleepWakeLifecycleEngine",
]
