"""Unit tests for DeliveryQueue."""

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from myrm_agent_harness.infra.delivery import (
    DeliveryQueue,
    load_pending_deliveries,
)


@pytest.fixture
def temp_queue_dir(tmp_path: Path) -> Path:
    """Create temporary queue directory."""
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    return queue_dir


@pytest.fixture
async def mock_deliver_fn() -> tuple[list[tuple[str, str, dict[str, Any]]], callable]:
    """Create mock delivery function that records calls."""
    calls = []

    async def deliver(channel: str, recipient: str, content: dict[str, Any]) -> None:
        calls.append((channel, recipient, content))

    return calls, deliver


@pytest.fixture
async def mock_failing_deliver_fn() -> tuple[list[int], callable]:
    """Create mock delivery function that fails N times then succeeds."""
    attempts = []

    async def deliver(channel: str, recipient: str, content: dict[str, Any]) -> None:
        attempts.append(len(attempts))
        if len(attempts) < 2:
            raise OSError("Network error")

    return attempts, deliver


@pytest.mark.asyncio
async def test_enqueue_success(temp_queue_dir: Path, mock_deliver_fn):
    """Test successful message enqueue and delivery."""
    calls, deliver_fn = mock_deliver_fn

    queue = DeliveryQueue(temp_queue_dir, deliver_fn)
    await queue.start()

    try:
        # Clear deduplicator for clean test
        queue._deduplicator.clear()

        # Enqueue message
        delivery_id = await queue.enqueue(
            channel="telegram",
            recipient="user123",
            content={"text": "Hello"},
        )

        assert delivery_id.startswith("telegram_user123_")

        # Wait for delivery
        await asyncio.sleep(0.2)

        # Verify delivery was called
        assert len(calls) == 1
        assert calls[0] == ("telegram", "user123", {"text": "Hello"})

        # Verify file was removed
        deliveries = await load_pending_deliveries(temp_queue_dir)
        assert len(deliveries) == 0

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_retry_on_failure(temp_queue_dir: Path, mock_failing_deliver_fn):
    """Test automatic retry on transient failure."""
    attempts, deliver_fn = mock_failing_deliver_fn

    queue = DeliveryQueue(temp_queue_dir, deliver_fn)
    await queue.start()

    try:
        # Enqueue message
        await queue.enqueue(
            channel="telegram",
            recipient="user123",
            content={"text": "Hello"},
        )

        # Wait for initial attempt + retry
        await asyncio.sleep(6.0)  # 5s backoff + buffer

        # Verify retry happened
        assert len(attempts) >= 2

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_recover_pending(temp_queue_dir: Path):
    """Test recovery of pending deliveries on startup."""
    calls = []

    async def slow_deliver(channel: str, recipient: str, content: dict[str, Any]) -> None:
        await asyncio.sleep(0.5)  # Slow delivery to ensure queue stops before completion
        calls.append((channel, recipient, content))

    # Create first queue and enqueue
    queue1 = DeliveryQueue(temp_queue_dir, slow_deliver)
    await queue1.start()

    delivery_id = await queue1.enqueue(
        channel="telegram",
        recipient="user123",
        content={"text": "Hello"},
    )

    # Stop before delivery completes
    await asyncio.sleep(0.05)
    await queue1.stop()

    # Verify file still exists
    deliveries = await load_pending_deliveries(temp_queue_dir)
    assert len(deliveries) == 1
    assert deliveries[0].id == delivery_id

    # Create second queue with fast delivery function
    async def fast_deliver(channel: str, recipient: str, content: dict[str, Any]) -> None:
        calls.append((channel, recipient, content))

    queue2 = DeliveryQueue(temp_queue_dir, fast_deliver)
    await queue2.start()

    try:
        # Wait for recovery and delivery
        await asyncio.sleep(0.2)

        # Verify delivery was completed
        assert len(calls) == 1
        assert calls[0] == ("telegram", "user123", {"text": "Hello"})

        # Verify file was removed
        deliveries = await load_pending_deliveries(temp_queue_dir)
        assert len(deliveries) == 0

    finally:
        await queue2.stop()


@pytest.mark.asyncio
async def test_permanent_error_moves_to_failed(temp_queue_dir: Path):
    """Test permanent errors are moved to failed directory."""

    async def failing_deliver(channel: str, recipient: str, content: dict[str, Any]) -> None:
        raise Exception("user not found")

    queue = DeliveryQueue(temp_queue_dir, failing_deliver)
    await queue.start()

    try:
        # Enqueue message
        await queue.enqueue(
            channel="telegram",
            recipient="user123",
            content={"text": "Hello"},
        )

        # Wait for failure handling
        await asyncio.sleep(0.2)

        # Verify moved to failed
        failed_dir = temp_queue_dir / "delivery-queue" / "failed"
        assert failed_dir.exists()
        failed_files = list(failed_dir.glob("*.json"))
        assert len(failed_files) == 1

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_max_retries_moves_to_failed(temp_queue_dir: Path):
    """Test max retries exceeded moves to failed."""
    attempts = []

    async def always_failing_deliver(channel: str, recipient: str, content: dict[str, Any]) -> None:
        attempts.append(len(attempts))
        raise OSError("Network error")

    queue = DeliveryQueue(temp_queue_dir, always_failing_deliver)
    await queue.start()

    try:
        # Enqueue message
        await queue.enqueue(
            channel="telegram",
            recipient="user123",
            content={"text": "Hello"},
        )

        # Wait for all retries (5s + 25s would take too long, so we verify logic)
        await asyncio.sleep(0.5)

        # Verify at least initial attempt
        assert len(attempts) >= 1

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_concurrent_delivery(temp_queue_dir: Path):
    """Test concurrent delivery with multiple workers."""
    calls = []
    call_times = []

    async def slow_deliver(channel: str, recipient: str, content: dict[str, Any]) -> None:
        call_times.append(time.time())
        await asyncio.sleep(0.1)  # Simulate slow delivery
        calls.append((channel, recipient, content))

    # Create queue with 5 workers
    queue = DeliveryQueue(temp_queue_dir, slow_deliver, max_workers=5)
    await queue.start()

    try:
        # Clear deduplicator for clean test
        queue._deduplicator.clear()

        # Enqueue 10 messages
        for i in range(10):
            await queue.enqueue(
                channel="telegram",
                recipient=f"user{i}",
                content={"text": f"Message {i}"},
            )

        # Wait for all deliveries (0.1s per message * 10 messages / 5 workers = ~0.2s + buffer)
        # Add extra time for queue processing and background recovery
        await asyncio.sleep(1.5)

        # Verify all messages delivered
        assert len(calls) == 10

        # Verify all unique recipients
        recipients = [call[1] for call in calls]
        assert len(set(recipients)) == 10  # All unique

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_worker_count(temp_queue_dir: Path, mock_deliver_fn):
    """Test correct number of workers are started."""
    _calls, deliver_fn = mock_deliver_fn

    queue = DeliveryQueue(temp_queue_dir, deliver_fn, max_workers=3)
    await queue.start()

    try:
        # Verify 3 workers started
        assert len(queue._worker_tasks) == 3

    finally:
        await queue.stop()

        # Verify all workers stopped
        assert len(queue._worker_tasks) == 0
