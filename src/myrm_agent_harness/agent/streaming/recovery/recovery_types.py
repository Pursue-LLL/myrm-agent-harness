"""Domain types for event replay buffer and resilient disconnection recovery.

Provides strong-typed abstractions for monotonic sequence-based streaming,
replay batch status negotiation, connection lifecycle states, and staged
actions during offline network dropouts.

[OUTPUT]
- ReplayStatus: Outcome category of a replay window query.
- ConnectionState: Lifecycle state of a client streaming connection.
- StructuredStreamEvent: Monotonically numbered stream event record.
- ReplayBatch: Consolidated response for sequence-based catch-up requests.
- StagedAction: Stored user interaction payload enqueued during disconnection.
- event_to_dict: Serialise StructuredStreamEvent to dict.
- dict_to_event: Deserialise dict to StructuredStreamEvent.

[INPUT]
- __future__
- time
- dataclasses
- typing

[OUTPUT]
- ReplayStatus
- ConnectionState
- VALID_REPLAY_STATUSES
- VALID_CONNECTION_STATES
- StructuredStreamEvent
- ReplayBatch
- StagedAction
- event_to_dict
- dict_to_event

[POS]
Domain types for event replay buffer and resilient disconnection recovery.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

ReplayStatus = Literal[
    "CONTINUOUS",
    "GAP_DETECTED",
    "EMPTY",
    "UP_TO_DATE",
]

ConnectionState = Literal[
    "CONNECTED",
    "DISCONNECTED",
    "RECONNECTING",
    "RESYNC_REQUIRED",
    "CLOSED",
]

VALID_REPLAY_STATUSES: tuple[ReplayStatus, ...] = (
    "CONTINUOUS",
    "GAP_DETECTED",
    "EMPTY",
    "UP_TO_DATE",
)

VALID_CONNECTION_STATES: tuple[ConnectionState, ...] = (
    "CONNECTED",
    "DISCONNECTED",
    "RECONNECTING",
    "RESYNC_REQUIRED",
    "CLOSED",
)


@dataclass(frozen=True, slots=True)
class StructuredStreamEvent:
    """A strictly ordered streaming event with a monotonic sequence identifier."""

    sequence_id: int
    event_type: str
    stream_id: str
    payload: dict[str, object] | str
    timestamp: float = field(default_factory=time.time)
    estimated_bytes: int = 0


@dataclass(frozen=True, slots=True)
class ReplayBatch:
    """Result of querying the circular replay buffer for events since a sequence ID."""

    status: ReplayStatus
    events: tuple[StructuredStreamEvent, ...]
    requested_seq: int
    oldest_retained_seq: int
    latest_retained_seq: int


@dataclass(frozen=True, slots=True)
class StagedAction:
    """Action enqueued while network is offline, to be flushed upon reconnect."""

    action_id: str
    action_type: str
    stream_id: str
    payload: dict[str, object]
    staged_at: float = field(default_factory=time.time)


def event_to_dict(evt: StructuredStreamEvent) -> dict[str, object]:
    """Convert StructuredStreamEvent to a JSON-compatible dictionary."""
    return {
        "sequence_id": evt.sequence_id,
        "event_type": evt.event_type,
        "stream_id": evt.stream_id,
        "payload": evt.payload,
        "timestamp": evt.timestamp,
        "estimated_bytes": evt.estimated_bytes,
    }


def dict_to_event(d: dict[str, object]) -> StructuredStreamEvent:
    """Construct StructuredStreamEvent from a serialized dictionary."""
    seq = int(d.get("sequence_id", 0))  # type: ignore[arg-type]
    event_type = str(d.get("event_type", "unknown"))
    stream_id = str(d.get("stream_id", ""))
    payload_raw = d.get("payload", "")
    payload: dict[str, object] | str = (
        payload_raw if isinstance(payload_raw, (dict, str)) else str(payload_raw)  # type: ignore[assignment]
    )
    timestamp = float(d.get("timestamp", 0.0))  # type: ignore[arg-type]
    estimated_bytes = int(d.get("estimated_bytes", 0))  # type: ignore[arg-type]

    return StructuredStreamEvent(
        sequence_id=seq,
        event_type=event_type,
        stream_id=stream_id,
        payload=payload,
        timestamp=timestamp,
        estimated_bytes=estimated_bytes,
    )
