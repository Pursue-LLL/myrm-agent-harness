"""Tests for DeliveryQueue with StorageProvider."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from myrm_agent_harness.infra.delivery.queue import DeliveryQueue
from myrm_agent_harness.toolkits.storage import LocalStorageBackend


@pytest.mark.asyncio
async def test_queue_with_storage_provider(tmp_path: Path):
    """Test DeliveryQueue using StorageProvider backend."""
    deliveries: list[tuple[str, str, dict]] = []

    async def deliver(channel: str, recipient: str, content: dict[str, Any]) -> None:
        deliveries.append((channel, recipient, content))

    # Create storage provider for queue state
    storage_provider = LocalStorageBackend(tmp_path / "storage")

    # DeliveryQueue still needs base_dir for file locking, but uses storage_provider for data
    queue = DeliveryQueue(
        base_dir=tmp_path / "locks",
        deliver_fn=deliver,
        storage_provider=storage_provider,
        max_workers=2,
    )
    await queue.start()

    try:
        queue._deduplicator.clear()

        # Enqueue messages
        await queue.enqueue("telegram", "user1", {"text": "Message 1"})
        await queue.enqueue("telegram", "user2", {"text": "Message 2"})

        # Wait for delivery
        await asyncio.sleep(0.3)

        # Verify deliveries
        assert len(deliveries) == 2
        assert ("telegram", "user1", {"text": "Message 1"}) in deliveries
        assert ("telegram", "user2", {"text": "Message 2"}) in deliveries

        # Verify storage: messages were stored and processed via storage_provider
        # Note: Successfully delivered messages are removed from storage
        # Check that storage path exists (queue directory was created)
        storage_path = tmp_path / "storage" / "delivery-queue"
        assert storage_path.exists(), "Queue should create storage path"

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_dlq_with_storage_provider(tmp_path: Path):
    """Test Dead Letter Queue using StorageProvider backend.

    Verifies that retry logic works with StorageProvider for failed messages.
    """
    attempts: list[int] = []

    async def failing_deliver(channel: str, recipient: str, content: dict[str, Any]) -> None:
        retry = content.get("retry_count", 0)
        attempts.append(retry)

        # Fail first 2 attempts
        if len(attempts) < 3:
            raise OSError("Temporary failure")

    # Create storage provider
    storage_provider = LocalStorageBackend(tmp_path / "storage")

    queue = DeliveryQueue(
        base_dir=tmp_path / "locks",
        deliver_fn=failing_deliver,
        storage_provider=storage_provider,
        enable_dlq=True,
        max_workers=2,
    )
    await queue.start()

    try:
        queue._deduplicator.clear()

        # Enqueue message that will fail and retry automatically
        await queue.enqueue("telegram", "user1", {"text": "Test", "retry_count": 0})

        # Wait for initial failure and automatic retries
        # Backoff uses exponential retry with jitter, typically ~5s for first retry
        await asyncio.sleep(6.0)

        # Verify multiple attempts (original + retries)
        assert len(attempts) >= 2, f"Expected at least 2 attempts, got {len(attempts)}: {attempts}"
        assert 0 in attempts  # Initial attempt with retry_count=0

    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_hybrid_mode_backwards_compatible(tmp_path: Path):
    """Test hybrid mode: base_dir + storage_provider can coexist."""
    deliveries: list[str] = []

    async def deliver(channel: str, recipient: str, content: dict[str, Any]) -> None:
        deliveries.append(content["text"])

    storage_provider = LocalStorageBackend(tmp_path / "storage")

    # Hybrid mode: both base_dir and storage_provider
    queue = DeliveryQueue(
        base_dir=tmp_path / "local",
        deliver_fn=deliver,
        storage_provider=storage_provider,
    )
    await queue.start()

    try:
        queue._deduplicator.clear()

        await queue.enqueue("telegram", "user1", {"text": "Hybrid test"})

        await asyncio.sleep(0.2)

        assert len(deliveries) == 1
        assert deliveries[0] == "Hybrid test"

    finally:
        await queue.stop()
