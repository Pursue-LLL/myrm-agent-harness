"""Append-only session event sourcing and deterministic context replayer package.

[INPUT]
- agent.context_management.event_sourcing_replayer.append_only_event_log::AppendOnlyEventLog (POS: Append-only
  immutable event log maintaining monotonic sequence numbers and hash chains.)
-
  agent.context_management.event_sourcing_replayer.deterministic_context_projector::DeterministicContextProjector
  (POS: Pure functional projector deriving exact model-visible context from event stream slices.)
-
  agent.context_management.event_sourcing_replayer.event_sourcing_replayer_suite::AppendOnlySessionEventSourcingAndContextReplayerSuite
  (POS: Suite managing append-only session event sourcing, step replaying, and audit certificates.)
- agent.context_management.event_sourcing_replayer.event_sourcing_types::ContextReplayCertificate,
  ProjectedMessageItem, ProjectedModelVisibleContext, SessionEventKind, SessionLedgerEvent (POS: Types and
  models for append-only session event sourcing and deterministic context replaying.)

[OUTPUT]
- Re-exports: AppendOnlyEventLog, AppendOnlySessionEventSourcingAndContextReplayerSuite,
  ContextReplayCertificate, DeterministicContextProjector, ProjectedMessageItem, ProjectedModelVisibleContext,
  SessionEventKind, SessionLedgerEvent

[POS]
Append-only session event sourcing and deterministic context replayer package.
"""

from __future__ import annotations

from .append_only_event_log import AppendOnlyEventLog
from .deterministic_context_projector import (
    DeterministicContextProjector,
)
from .event_sourcing_replayer_suite import (
    AppendOnlySessionEventSourcingAndContextReplayerSuite,
)
from .event_sourcing_types import (
    ContextReplayCertificate,
    ProjectedMessageItem,
    ProjectedModelVisibleContext,
    SessionEventKind,
    SessionLedgerEvent,
)

__all__ = [
    "AppendOnlyEventLog",
    "AppendOnlySessionEventSourcingAndContextReplayerSuite",
    "ContextReplayCertificate",
    "DeterministicContextProjector",
    "ProjectedMessageItem",
    "ProjectedModelVisibleContext",
    "SessionEventKind",
    "SessionLedgerEvent",
]
