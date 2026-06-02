"""Dead letter queue for failed message recovery.

Provides retry mechanism for failed messages with exponential backoff.
Supports both local file system and cloud storage via StorageProvider.

[INPUT]
- storage (POS: 持久化层，支持本地和云存储)
- myrm_agent_harness.toolkits.storage.base::StorageProvider (POS: 云存储抽象)

[OUTPUT]
- DeadLetterQueue: 死信队列类

[POS]
Dead letter queue. Failed messages are retryable with manual re-queue support.

"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

import contextlib

from .storage import QueuedDelivery, delete_failed_delivery, load_failed_deliveries

logger = logging.getLogger(__name__)

# Type alias for enqueue function
EnqueueFn = Callable[[str, str, dict[str, Any]], Awaitable[str]]


class DeadLetterQueue:
    """Dead letter queue for failed message recovery.

    Features:
    - Automatic retry with exponential backoff
    - Manual retry support
    - Configurable retry intervals
    - Maximum retry limit
    - Direct integration with DeliveryQueue via enqueue callback

    Attributes:
        base_dir: Base state directory (local mode, optional)
        storage_provider: Storage provider (cloud mode, optional)
        enqueue_fn: Callback to enqueue messages back to main queue
        max_retries: Maximum number of retry attempts (default: 3)
        retry_intervals_ms: Retry intervals in milliseconds (default: [5min, 1h, 6h, 24h])
        ttl_days: Time-to-live for failed messages in days, after which they are deleted (default: 30)
    """

    def __init__(
        self,
        enqueue_fn: EnqueueFn,
        base_dir: Path | None = None,
        storage_provider: StorageProvider | None = None,
        max_retries: int = 3,
        retry_intervals_ms: list[int] | None = None,
        ttl_days: int = 30,
        on_permanent_failure: Callable[[QueuedDelivery, str], Awaitable[None]] | None = None,
    ) -> None:
        if base_dir is None and storage_provider is None:
            raise ValueError("Either base_dir or storage_provider must be provided")

        self.base_dir = base_dir
        self.storage_provider = storage_provider
        self.enqueue_fn = enqueue_fn
        self.max_retries = max_retries
        self.ttl_days = ttl_days
        self.on_permanent_failure = on_permanent_failure
        self.retry_intervals_ms = retry_intervals_ms or [
            5 * 60 * 1000,  # 5 minutes (for transient failures)
            60 * 60 * 1000,  # 1 hour
            6 * 60 * 60 * 1000,  # 6 hours
            24 * 60 * 60 * 1000,  # 24 hours
        ]
        self._running = False
        self._retry_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start dead letter queue retry loop."""
        self._running = True
        self._retry_task = asyncio.create_task(self._retry_loop())
        logger.info("Dead letter queue started")

    async def stop(self) -> None:
        """Stop dead letter queue retry loop."""
        self._running = False
        if self._retry_task:
            self._retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._retry_task
        logger.info("Dead letter queue stopped")

    async def _retry_loop(self) -> None:
        """Background loop to retry failed messages."""
        while self._running:
            try:
                await self._process_failed_messages()
            except Exception as e:
                logger.error(f"Error in dead letter retry loop: {e}")

            # Check every 5 minutes
            await asyncio.sleep(300)

    async def _process_failed_messages(self) -> None:
        """Process failed messages and retry eligible ones."""
        failed_deliveries = await load_failed_deliveries(base_dir=self.base_dir, storage_provider=self.storage_provider)

        if not failed_deliveries:
            return

        now_ms = time.time() * 1000
        now_sec = time.time()
        retried_count = 0
        deleted_count = 0

        for delivery in failed_deliveries:
            base_time = delivery.failed_at or delivery.last_attempt_at or delivery.enqueued_at

            # 1. TTL Auto-Cleanup Check
            if self.ttl_days > 0:
                age_days = (now_sec - base_time) / (24 * 3600)
                if age_days > self.ttl_days:
                    logger.info(
                        f"Delivery {delivery.id} exceeded TTL ({self.ttl_days} days), deleting from dead letter queue"
                    )
                    try:
                        await delete_failed_delivery(
                            delivery.id, base_dir=self.base_dir, storage_provider=self.storage_provider
                        )
                        deleted_count += 1
                    except Exception as e:
                        logger.error(f"Failed to delete expired delivery {delivery.id}: {e}")
                    continue

            # 2. Retry Eligibility Check
            if delivery.retry_count >= self.max_retries:
                logger.debug(f"Delivery {delivery.id} exceeded max retries ({self.max_retries}), skipping")
                continue

            # Calculate next retry time based on when it failed
            retry_index = min(delivery.retry_count, len(self.retry_intervals_ms) - 1)
            retry_interval_ms = self.retry_intervals_ms[retry_index]
            next_retry_ms = base_time * 1000 + retry_interval_ms

            if now_ms >= next_retry_ms:
                # Eligible for retry - re-enqueue to main queue with original priority
                try:
                    await self.enqueue_fn(
                        delivery.channel,
                        delivery.recipient,
                        delivery.content,
                        priority=delivery.priority,
                    )
                    # Delete from failed directory after successful re-enqueue
                    await delete_failed_delivery(
                        delivery.id, base_dir=self.base_dir, storage_provider=self.storage_provider
                    )
                    retried_count += 1
                    logger.info(
                        f"Retrying delivery {delivery.id} (attempt {delivery.retry_count + 1}/{self.max_retries})"
                    )
                except Exception as e:
                    logger.error(f"Failed to retry delivery {delivery.id}: {e}")

        if retried_count > 0:
            logger.info(f"Retried {retried_count} failed deliveries")
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} expired failed deliveries")

    async def manual_retry(self, delivery_id: str) -> bool:
        """Manually retry a failed delivery.

        Args:
            delivery_id: Delivery ID to retry

        Returns:
            True if retry was successful, False otherwise
        """
        failed_deliveries = await load_failed_deliveries(base_dir=self.base_dir, storage_provider=self.storage_provider)

        for delivery in failed_deliveries:
            if delivery.id == delivery_id:
                try:
                    await self.enqueue_fn(
                        delivery.channel,
                        delivery.recipient,
                        delivery.content,
                        priority=delivery.priority,
                    )
                    # Delete from failed directory after successful re-enqueue
                    await delete_failed_delivery(
                        delivery_id, base_dir=self.base_dir, storage_provider=self.storage_provider
                    )
                    logger.info(f"Manually retried delivery {delivery_id}")
                    return True
                except Exception as e:
                    logger.error(f"Failed to manually retry delivery {delivery_id}: {e}")
                    return False

        logger.warning(f"Delivery {delivery_id} not found in failed queue")
        return False

    async def manual_retry_all(self) -> int:
        """Manually retry all failed deliveries.

        Returns:
            Number of deliveries retried
        """
        failed_deliveries = await load_failed_deliveries(base_dir=self.base_dir, storage_provider=self.storage_provider)
        retried_count = 0

        for delivery in failed_deliveries:
            try:
                await self.enqueue_fn(
                    delivery.channel,
                    delivery.recipient,
                    delivery.content,
                    priority=delivery.priority,
                )
                # Delete from failed directory after successful re-enqueue
                await delete_failed_delivery(
                    delivery.id, base_dir=self.base_dir, storage_provider=self.storage_provider
                )
                retried_count += 1
            except Exception as e:
                logger.error(f"Failed to retry delivery {delivery.id}: {e}")

        logger.info(f"Manually retried {retried_count} failed deliveries")
        return retried_count

    async def get_failed_count(self) -> int:
        """Get number of failed deliveries (supports both storage modes).

        Returns:
            Number of failed deliveries
        """
        failed_deliveries = await load_failed_deliveries(base_dir=self.base_dir, storage_provider=self.storage_provider)
        return len(failed_deliveries)

    async def get_failed_deliveries(self) -> list[QueuedDelivery]:
        """Get all failed deliveries (supports both storage modes).

        Returns:
            List of failed deliveries
        """
        return await load_failed_deliveries(base_dir=self.base_dir, storage_provider=self.storage_provider)
