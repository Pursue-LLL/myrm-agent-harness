"""Durable delivery storage, dead-letter retry and permanent-failure ledger.

Provides disk persistence for pending and failed deliveries and a dead-letter queue
with exponential-backoff retry. The delivery queue itself is owned by the host.

[INPUT]
(No external dependencies, pure asyncio + json)

[OUTPUT]
- QueuedDelivery: Queued delivery dataclass
- DeadLetterQueue: Dead letter queue with retry and permanent-failure callback
- save_delivery, ack_delivery, load_pending_deliveries, load_failed_deliveries, move_to_failed, move_to_pending: storage helpers

[POS]
Durable delivery persistence and dead-letter recovery.

"""

from .dead_letter import DeadLetterQueue
from .storage import (
    QueuedDelivery,
    ack_delivery,
    load_failed_deliveries,
    load_pending_deliveries,
    move_to_failed,
    move_to_pending,
    save_delivery,
)

__all__ = [
    "DeadLetterQueue",
    "QueuedDelivery",
    "ack_delivery",
    "load_failed_deliveries",
    "load_pending_deliveries",
    "move_to_failed",
    "move_to_pending",
    "save_delivery",
]
