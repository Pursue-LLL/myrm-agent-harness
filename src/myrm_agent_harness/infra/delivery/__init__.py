"""Message delivery queue with persistence and auto-recovery.

Provides reliable message delivery with disk persistence, automatic retry,
and startup recovery.

[INPUT]
(No external dependencies, pure asyncio + json)

[OUTPUT]
- QueuedDelivery: Queued delivery dataclass
- DeliveryQueue: Main queue class with persistence and retry

[POS]
Message delivery queue. Disk-persistent with automatic retry on failure and pending delivery recovery on startup.

"""

from .dead_letter import DeadLetterQueue
from .file_lock import acquire_delivery_lock
from .queue import DeliveryQueue
from .recovery import compute_backoff_ms, is_permanent_error, recover_pending_deliveries
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
    "DeliveryQueue",
    "QueuedDelivery",
    "ack_delivery",
    "acquire_delivery_lock",
    "compute_backoff_ms",
    "is_permanent_error",
    "load_failed_deliveries",
    "load_pending_deliveries",
    "move_to_failed",
    "move_to_pending",
    "recover_pending_deliveries",
    "save_delivery",
]
