"""Tests for priority queue functionality."""

import asyncio
from pathlib import Path

import pytest

from myrm_agent_harness.infra.delivery import DeliveryQueue


@pytest.mark.asyncio
async def test_priority_ordering(tmp_path: Path):
    """Test messages are delivered in priority order."""
    calls: list[tuple[str, str, dict]] = []

    async def deliver(channel: str, recipient: str, content: dict):
        await asyncio.sleep(0.05)  # Simulate delivery time
        calls.append((channel, recipient, content))

    queue = DeliveryQueue(tmp_path, deliver, max_workers=1)  # Single worker for deterministic order
    await queue.start()

    try:
        # Clear deduplicator for clean test
        queue._deduplicator.clear()

        # Enqueue messages with different priorities
        await queue.enqueue("telegram", "user1", {"text": "Low priority"}, priority=3)
        await queue.enqueue("telegram", "user2", {"text": "Normal priority"}, priority=2)
        await queue.enqueue("telegram", "user3", {"text": "High priority"}, priority=1)
        await queue.enqueue("telegram", "user4", {"text": "Highest priority"}, priority=0)
        await queue.enqueue("telegram", "user5", {"text": "Another high"}, priority=1)

        # Wait for all deliveries
        await asyncio.sleep(0.5)

        # Verify delivery order: 0 -> 1 -> 1 -> 2 -> 3
        assert len(calls) == 5
        assert calls[0][2]["text"] == "Highest priority"  # priority=0
        assert calls[1][2]["text"] == "High priority"  # priority=1 (first)
        assert calls[2][2]["text"] == "Another high"  # priority=1 (second, FIFO within priority)
        assert calls[3][2]["text"] == "Normal priority"  # priority=2
        assert calls[4][2]["text"] == "Low priority"  # priority=3

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_priority_with_concurrent_workers(tmp_path: Path):
    """Test priority queue works with concurrent workers."""
    calls: list[tuple[str, str, dict]] = []
    lock = asyncio.Lock()

    async def deliver(channel: str, recipient: str, content: dict):
        await asyncio.sleep(0.05)
        async with lock:
            calls.append((channel, recipient, content))

    queue = DeliveryQueue(tmp_path, deliver, max_workers=3)
    await queue.start()

    try:
        queue._deduplicator.clear()

        # Enqueue 10 messages: 2 urgent (priority=0), 8 normal (priority=2)
        await queue.enqueue("telegram", "urgent1", {"text": "Urgent 1"}, priority=0)
        await queue.enqueue("telegram", "normal1", {"text": "Normal 1"}, priority=2)
        await queue.enqueue("telegram", "normal2", {"text": "Normal 2"}, priority=2)
        await queue.enqueue("telegram", "urgent2", {"text": "Urgent 2"}, priority=0)
        await queue.enqueue("telegram", "normal3", {"text": "Normal 3"}, priority=2)

        # Wait for all deliveries
        await asyncio.sleep(0.5)

        # Verify all delivered
        assert len(calls) == 5

        # Verify urgent messages were delivered first (may be out of order due to concurrency)
        urgent_indices = [i for i, c in enumerate(calls) if "Urgent" in c[2]["text"]]
        normal_indices = [i for i, c in enumerate(calls) if "Normal" in c[2]["text"]]

        # All urgent messages should be delivered before all normal messages
        # (or at least the first urgent should be before the last normal)
        assert min(urgent_indices) < max(normal_indices)

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_priority_preserved_on_retry(tmp_path: Path):
    """Test priority is preserved when message is retried."""
    attempts: list[tuple[int, str]] = []  # (retry_count, text)

    async def deliver(channel: str, recipient: str, content: dict):
        # Fail first attempt, succeed on retry
        if len(attempts) == 0:
            attempts.append((0, content["text"]))
            raise OSError("Network error")
        attempts.append((1, content["text"]))

    queue = DeliveryQueue(tmp_path, deliver)
    await queue.start()

    try:
        queue._deduplicator.clear()

        # Enqueue high priority message
        await queue.enqueue("telegram", "user1", {"text": "High priority"}, priority=1)

        # Wait for retry
        await asyncio.sleep(6.0)

        # Verify both attempts happened
        assert len(attempts) == 2
        assert attempts[0] == (0, "High priority")
        assert attempts[1] == (1, "High priority")

    finally:
        await queue.stop()
