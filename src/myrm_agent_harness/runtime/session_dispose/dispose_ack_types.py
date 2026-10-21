"""Strongly typed data contracts for session dispose hard-purge and delivery acknowledgement.

Benchmarked against Paseo commit 92442e74 and Omnigent commit a9e76345:
- Physical hard reject for in-flight requests upon session disposal to prevent infinite UI loading loops.
- Delivery acknowledgement (ACK) protocol for multi-agent and cross-process messaging.
- Resilient turn tracking to prevent black-hole lost deliveries.

[OUTPUT]
- SessionLifecycleState: Execution state of the managed session (ACTIVE, DISPOSING, DISPOSED).
- SessionDisposedError: Explicit rejection exception delivered to all pending futures upon teardown.
- DeliveryAckStatus: Delivery progress status of dispatched inter-agent messages.
- DeliveryAckReceipt: Audit receipt recording delivery confirmation and round-trip latency.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- SessionLifecycleState
- DeliveryAckStatus
- SessionDisposedError
- DeliveryAckReceipt

[POS]
Strongly typed data contracts for session dispose hard-purge and delivery acknowledgement.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class SessionLifecycleState(StrEnum):
    """Lifecycle states of an agent session or workspace worker."""

    ACTIVE = "active"
    DISPOSING = "disposing"
    DISPOSED = "disposed"


class DeliveryAckStatus(StrEnum):
    """Status classification for multi-agent message delivery acknowledgement."""

    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"


class SessionDisposedError(Exception):
    """Raised when an in-flight request is rejected due to session disposal.

    Eliminates the infinite-loading spinner bug where unclosed backend promises
    leave frontend components (e.g. model selector or workspace snapshot) permanently frozen.
    """

    def __init__(
        self,
        session_id: str,
        reason: str = "Session explicitly closed by user or system",
        purged_request_count: int = 1,
    ) -> None:
        super().__init__(
            f"Session '{session_id}' disposed: {reason} ({purged_request_count} pending request(s) purged)"
        )
        self.session_id = session_id
        self.reason = reason
        self.purged_request_count = purged_request_count


@dataclass(frozen=True)
class DeliveryAckReceipt:
    """Record verifying receipt confirmation from remote recipient agent or process."""

    message_id: str
    recipient_id: str
    status: DeliveryAckStatus
    rtt_ms: float = 0.0
    reason: str = ""
    timestamp: float = field(default_factory=time.time)
