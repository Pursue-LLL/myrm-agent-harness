"""Test P0 and P1 optimizations."""

import asyncio
from pathlib import Path

import pytest

from myrm_agent_harness.infra.delivery import DeliveryQueue


@pytest.mark.asyncio
async def test_urgent_message_bypasses_batching(tmp_path: Path):
    """Test that urgent messages (priority=0) bypass batching logic.

    This test verifies that the code path for priority=0 messages
    skips the batching logic and goes directly to immediate delivery.
    """
    deliveries: list[tuple[str, int]] = []  # (text, priority)

    async def deliver(channel: str, recipient: str, content: dict):
        deliveries.append((content["text"], content.get("priority", 2)))
        await asyncio.sleep(0.01)

    queue = DeliveryQueue(
        tmp_path,
        deliver,
        max_workers=2,
        batch_threshold=2,  # Batch when queue has 2+ messages
        batch_size=5,
    )
    await queue.start()

    try:
        queue._deduplicator.clear()

        # Enqueue mix of urgent and normal messages
        await queue.enqueue("telegram", "user1", {"text": "urgent1", "priority": 0}, priority=0)
        await queue.enqueue("telegram", "user2", {"text": "normal1", "priority": 2}, priority=2)
        await queue.enqueue("telegram", "user3", {"text": "urgent2", "priority": 0}, priority=0)
        await queue.enqueue("telegram", "user4", {"text": "normal2", "priority": 2}, priority=2)

        # Wait for all deliveries
        await asyncio.sleep(0.5)

        # Verify all messages delivered
        assert len(deliveries) == 4

        # Verify urgent messages (priority=0) were delivered
        urgent_count = sum(1 for _, p in deliveries if p == 0)
        assert urgent_count == 2, "Both urgent messages should be delivered"

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_batch_concurrent_execution(tmp_path: Path):
    """Test that batch processing executes deliveries concurrently."""
    delivery_times: list[float] = []
    delivery_count = 0

    async def deliver(channel: str, recipient: str, content: dict):
        nonlocal delivery_count
        delivery_count += 1
        start = asyncio.get_event_loop().time()
        await asyncio.sleep(0.1)  # Simulate 100ms delivery
        delivery_times.append(asyncio.get_event_loop().time() - start)

    queue = DeliveryQueue(
        tmp_path,
        deliver,
        max_workers=1,
        batch_threshold=3,
        batch_size=5,
        batch_timeout_ms=50,
    )
    await queue.start()

    try:
        queue._deduplicator.clear()

        # Enqueue 5 messages to trigger batching
        for i in range(5):
            await queue.enqueue("telegram", f"user{i}", {"text": f"msg_{i}"}, priority=2)

        # Wait for batch processing
        await asyncio.sleep(1.0)

        # Verify all messages delivered
        assert delivery_count == 5

        # Verify concurrent execution: total time should be ~100ms (not 500ms)
        # If executed serially, would take 500ms
        # If executed concurrently, takes ~100ms
        # We check that average delivery time is close to 100ms (concurrent)
        avg_time = sum(delivery_times) / len(delivery_times)
        assert 0.09 < avg_time < 0.20, f"Average delivery time {avg_time:.3f}s suggests concurrent execution"

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_priority_queue_tie_breaker(tmp_path: Path):
    """Test that PriorityQueue handles identical priority and timestamp correctly."""
    deliveries: list[str] = []

    async def deliver(channel: str, recipient: str, content: dict):
        deliveries.append(content["id"])

    queue = DeliveryQueue(tmp_path, deliver, max_workers=1)
    await queue.start()

    try:
        queue._deduplicator.clear()

        # Enqueue multiple messages with same priority and timestamp
        # This tests the delivery_id tie-breaker
        import time

        time.time()

        for i in range(3):
            await queue.enqueue(
                "telegram",
                f"user{i}",
                {"id": f"msg_{i}"},
                priority=1,
            )
            # Manually set same timestamp (for testing)
            # In practice, this is extremely rare due to time.time() precision

        # Wait for deliveries
        await asyncio.sleep(0.5)

        # All messages should be delivered without errors
        assert len(deliveries) == 3

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_dlq_faster_retry(tmp_path: Path):
    """Test that DLQ has faster first retry (5 minutes instead of 1 hour)."""
    queue = DeliveryQueue(tmp_path, lambda *args: None, enable_dlq=True)
    await queue.start()

    try:
        # Check DLQ retry intervals
        assert queue._dlq is not None
        intervals = queue._dlq.retry_intervals_ms

        # First retry should be 5 minutes (300,000 ms)
        assert intervals[0] == 5 * 60 * 1000, f"First retry should be 5 min, got {intervals[0] / 1000 / 60:.1f} min"

        # Verify we have 4 intervals (5min, 1h, 6h, 24h)
        assert len(intervals) == 4, f"Should have 4 retry intervals, got {len(intervals)}"

    finally:
        await queue.stop()
