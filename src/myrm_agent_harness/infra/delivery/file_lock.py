"""File-based locking for delivery processing.

Provides file-based locks to prevent duplicate processing of deliveries
by multiple asyncio workers within the same sandbox.

**Use Case**: Prevents race conditions when multiple asyncio workers (default: 10)
in the same sandbox process the same message concurrently.

**Important**: This is NOT for cross-sandbox locking (sandboxes are isolated).
This is for intra-sandbox worker coordination.

[INPUT]
- infra.locks.file_lock (POS: Unified file locking)

[OUTPUT]
- acquire_delivery_lock: Delivery-specific lock wrapper

[POS]
Delivery module file lock wrapper. Prevents duplicate processing during concurrent multi-worker execution within the same sandbox.

"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from ..locks.file_lock import acquire_file_lock


@asynccontextmanager
async def acquire_delivery_lock(
    delivery_id: str,
    base_dir: Path,
) -> AsyncIterator[bool]:
    """Acquire exclusive lock for delivery processing.

    Prevents duplicate processing by multiple asyncio workers within the same sandbox.

    **Scenario**: DeliveryQueue has 10 asyncio workers running concurrently.
    Without this lock, multiple workers might process the same message.

    **Note**: This is NOT for cross-sandbox locking. Each sandbox has its
    own isolated filesystem. This lock only coordinates workers within
    the same sandbox process.

    Lock is automatically released on process crash (OS guarantee).

    Args:
        delivery_id: Delivery ID to lock
        base_dir: Base state directory

    Yields:
        True if lock acquired, False if already locked

    Example:
        async with acquire_delivery_lock(delivery_id, base_dir) as locked:
            if locked:
                await deliver(...)
            else:
                pass  # Already being processed
    """
    lock_dir = base_dir / "locks"
    async with acquire_file_lock(
        delivery_id,
        lock_dir,
        mode="exclusive",
        blocking=False,
    ) as acquired:
        yield acquired
