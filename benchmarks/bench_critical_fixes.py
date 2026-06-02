"""Benchmark critical bug fixes.

Verifies:
1. DLQ retry preserves message priority
2. load_failed_deliveries correctly loads from failed directory
"""

import asyncio
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from myrm_agent_harness.infra.delivery import DeliveryQueue
from myrm_agent_harness.infra.delivery.storage import (
    QueuedDelivery,
    load_failed_deliveries,
    move_to_failed,
)


async def bench_dlq_priority_preservation():
    """Verify DLQ retry preserves priority."""
    print("\n=== Benchmark: DLQ Priority Preservation ===")

    with TemporaryDirectory() as tmpdir:
        enqueue_calls: list[tuple[str, int]] = []  # (delivery_id, priority)

        async def deliver(channel: str, recipient: str, content: dict):
            pass

        async def tracked_enqueue(channel: str, recipient: str, content: dict, priority: int = 2):
            enqueue_calls.append((content.get("id", "unknown"), priority))

        queue = DeliveryQueue(Path(tmpdir), deliver, enable_dlq=True)
        if queue._dlq:
            queue._dlq.enqueue_fn = tracked_enqueue

        await queue.start()

        try:
            # Create failed deliveries with different priorities
            priorities = [0, 1, 2, 3]
            for i, prio in enumerate(priorities):
                delivery = QueuedDelivery(
                    id=f"test_{i}",
                    channel="telegram",
                    recipient="user1",
                    content={"id": f"test_{i}", "text": f"Message {i}"},
                    enqueued_at=time.time(),
                    priority=prio,
                    retry_count=2,
                )
                await move_to_failed(delivery, queue.base_dir)

            # Wait for files to be written
            await asyncio.sleep(0.1)

            # Manually retry all
            if queue._dlq:
                count = await queue._dlq.manual_retry_all()
                print(f"Retried {count} deliveries")

            # Verify priorities preserved
            print(f"Enqueue calls: {len(enqueue_calls)}")
            for delivery_id, priority in enqueue_calls:
                expected_priority = int(delivery_id.split("_")[1])
                if priority == expected_priority:
                    print(f"✓ {delivery_id}: priority={priority} (preserved)")
                else:
                    print(f"✗ {delivery_id}: priority={priority} (expected {expected_priority})")

        finally:
            await queue.stop()


async def bench_load_failed_deliveries():
    """Verify load_failed_deliveries works correctly."""
    print("\n=== Benchmark: Load Failed Deliveries ===")

    with TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)

        # Create multiple failed deliveries
        priorities = [0, 1, 2, 3]
        start_time = time.time()

        for i, prio in enumerate(priorities):
            delivery = QueuedDelivery(
                id=f"failed_{i}",
                channel="telegram",
                recipient=f"user{i}",
                content={"text": f"Message {i}"},
                enqueued_at=time.time(),
                priority=prio,
                retry_count=3,
            )
            await move_to_failed(delivery, base_dir)

        write_time = time.time() - start_time

        # Load failed deliveries
        start_time = time.time()
        failed_deliveries = await load_failed_deliveries(base_dir)
        load_time = time.time() - start_time

        print(f"Created {len(priorities)} failed deliveries in {write_time * 1000:.2f}ms")
        print(f"Loaded {len(failed_deliveries)} failed deliveries in {load_time * 1000:.2f}ms")

        # Verify all deliveries loaded correctly
        loaded_ids = {d.id for d in failed_deliveries}
        expected_ids = {f"failed_{i}" for i in range(len(priorities))}

        if loaded_ids == expected_ids:
            print("✓ All deliveries loaded correctly")
        else:
            print(f"✗ Missing deliveries: {expected_ids - loaded_ids}")
            print(f"✗ Extra deliveries: {loaded_ids - expected_ids}")

        # Verify priorities preserved
        for delivery in failed_deliveries:
            idx = int(delivery.id.split("_")[1])
            expected_priority = priorities[idx]
            if delivery.priority == expected_priority:
                print(f"✓ {delivery.id}: priority={delivery.priority} (preserved)")
            else:
                print(f"✗ {delivery.id}: priority={delivery.priority} (expected {expected_priority})")


async def main():
    """Run all benchmarks."""
    await bench_dlq_priority_preservation()
    await bench_load_failed_deliveries()


if __name__ == "__main__":
    asyncio.run(main())
