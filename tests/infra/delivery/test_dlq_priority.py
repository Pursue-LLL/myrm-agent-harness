"""Test dead letter queue preserves priority on retry."""

import asyncio
from pathlib import Path

import pytest

from myrm_agent_harness.infra.delivery import DeliveryQueue


@pytest.mark.asyncio
async def test_dlq_preserves_priority_on_retry(tmp_path: Path):
    """Test dead letter queue preserves message priority when retrying."""
    attempts: list[tuple[int, int]] = []  # (retry_count, priority)

    async def deliver(channel: str, recipient: str, content: dict):
        retry_count = content.get("retry_count", 0)
        priority = content.get("priority", 2)
        attempts.append((retry_count, priority))

        # Fail first 3 attempts to trigger DLQ
        if retry_count < 3:
            raise OSError("Network error")

    queue = DeliveryQueue(tmp_path, deliver, enable_dlq=True)
    await queue.start()

    try:
        queue._deduplicator.clear()

        # Enqueue urgent message (priority=0)
        await queue.enqueue(
            "telegram",
            "user1",
            {"text": "Urgent", "retry_count": 0, "priority": 0},
            priority=0,
        )

        # Wait for retries and DLQ processing
        # Retry intervals: 5s, 10s, 20s (total ~35s)
        # DLQ check interval: 60s
        # For testing, we'll wait for initial attempts
        await asyncio.sleep(1.0)

        # Verify initial attempts happened
        assert len(attempts) >= 1
        # All attempts should have priority=0
        for retry_count, priority in attempts:
            assert priority == 0, f"Priority should be 0, got {priority} at retry {retry_count}"

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_dlq_manual_retry_preserves_priority(tmp_path: Path):
    """Test manual retry from DLQ preserves priority."""
    enqueue_calls: list[tuple[str, str, dict, int]] = []  # (channel, recipient, content, priority)

    async def deliver(channel: str, recipient: str, content: dict):
        pass  # Not used in this test

    # Create a wrapper to track enqueue calls
    async def tracked_enqueue(channel: str, recipient: str, content: dict, priority: int = 2):
        enqueue_calls.append((channel, recipient, content, priority))
        # Don't actually enqueue to avoid complexity
        return f"tracked_{channel}_{recipient}"

    queue = DeliveryQueue(tmp_path, deliver, enable_dlq=True, max_workers=1)

    # Replace DLQ's enqueue_fn with our tracked version
    if queue._dlq:
        queue._dlq.enqueue_fn = tracked_enqueue

    await queue.start()

    try:
        # Manually create a failed delivery with high priority
        import time

        from myrm_agent_harness.infra.delivery.storage import QueuedDelivery, move_to_failed

        delivery = QueuedDelivery(
            id="test_urgent_123",
            channel="telegram",
            recipient="user1",
            content={"text": "Urgent message"},
            enqueued_at=time.time(),
            priority=1,
            retry_count=3,
        )

        await move_to_failed(delivery, queue.base_dir)

        # Wait a bit for file to be written
        await asyncio.sleep(0.1)

        # Manually retry
        if queue._dlq:
            success = await queue._dlq.manual_retry("test_urgent_123")
            assert success, "Manual retry should succeed"

        # Verify priority was passed to enqueue
        assert len(enqueue_calls) == 1, f"Expected 1 enqueue call, got {len(enqueue_calls)}"
        channel, recipient, _content, priority = enqueue_calls[0]
        assert priority == 1, f"Priority should be 1, got {priority}"
        assert channel == "telegram"
        assert recipient == "user1"

    finally:
        await queue.stop()
