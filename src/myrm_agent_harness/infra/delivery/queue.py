"""Delivery queue with persistence and auto-recovery.

Main queue class that orchestrates storage and recovery.
Supports both local file system and cloud storage via StorageProvider.

[INPUT]
- storage (POS: 持久化层，支持本地和云存储)
- recovery (POS: 恢复逻辑)
- infra.tracing (POS: 分布式追踪)
- myrm_agent_harness.toolkits.storage.base::StorageProvider (POS: 云存储抽象)

[OUTPUT]
- DeliveryQueue: 主队列类

[POS]
Delivery queue main class. Coordinates storage and recovery, providing enqueue, deliver, and failure handling interfaces.

"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

import contextlib

from myrm_agent_harness.infra.tracing import DynamicLabelManager, get_meter, get_tracer

from .dead_letter import DeadLetterQueue
from .deduplication import MessageDeduplicator
from .file_lock import acquire_delivery_lock
from .recovery import (
    MAX_RETRIES,
    compute_backoff_ms,
    is_permanent_error,
    recover_pending_deliveries,
)
from .storage import (
    QueuedDelivery,
    ack_delivery,
    generate_delivery_id,
    load_pending_deliveries,
    move_to_failed,
    save_delivery,
)

logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)
meter = get_meter(__name__)

# Type alias for delivery function
DeliveryFn = Callable[[str, str, dict[str, Any]], Awaitable[None]]


class DeliveryQueue:
    """Delivery queue with disk persistence and automatic retry.

    Features:
    - Disk persistence: Survives process crashes
    - Automatic retry: Exponential backoff with jitter
    - Startup recovery: Resumes pending deliveries on restart
    - Failure isolation: Permanent errors moved to failed directory
    - Concurrent workers: Multiple asyncio workers for high throughput
    - Adaptive batching: Dynamic batch processing based on queue depth
    - Dead letter queue: Automatic retry of failed messages

    **Concurrency Model**:
    - Type: asyncio coroutine tasks (asyncio.Task), NOT multiprocessing/threading
    - Count: Default 10 concurrent tasks
    - Execution: Single process, single thread, event loop switches between tasks
    - File Lock: Required to prevent duplicate processing by multiple concurrent tasks
    - Isolation: Each sandbox has independent filesystem (no cross-sandbox conflicts)

    Note: "Worker" typically refers to multiprocessing.Process or threading.Thread.
    This module uses asyncio.Task for concurrent I/O operations (concurrent, not parallel).

    Attributes:
        base_dir: Base state directory for queue storage (local mode, required)
        deliver_fn: Async function to deliver messages (channel, recipient, content) -> None
        storage_provider: Storage provider for cloud storage (cloud mode, optional)
        max_workers: Maximum number of concurrent asyncio workers (default: 10)
        batch_threshold: Queue depth threshold for batch processing (default: 5)
        batch_size: Maximum batch size (default: 10)
        batch_timeout_ms: Batch collection timeout in milliseconds (default: 100)
        max_queue_size: Maximum queue size for backpressure (default: 1000)
        enable_dlq: Enable dead letter queue (default: True)

    Note:
        base_dir is required for file locking and local storage.
        storage_provider is optional - if provided, enables cloud storage support.
        Both can be used together for hybrid deployment.
    """

    def __init__(
        self,
        base_dir: Path,
        deliver_fn: DeliveryFn,
        storage_provider: StorageProvider | None = None,
        max_workers: int = 10,
        batch_threshold: int = 5,
        batch_size: int = 10,
        batch_timeout_ms: int = 100,
        recovery_rate_per_sec: int = 100,
        max_queue_size: int = 1000,
        enable_dlq: bool = True,
        on_permanent_failure: Callable[[QueuedDelivery, str], Awaitable[None]] | None = None,
    ) -> None:
        # base_dir is required for file locking
        # storage_provider is optional for cloud storage support

        self.base_dir = base_dir
        self.storage_provider = storage_provider
        self.deliver_fn = deliver_fn
        self.max_workers = max_workers
        self.batch_threshold = batch_threshold
        self.batch_size = batch_size
        self.batch_timeout_ms = batch_timeout_ms
        self.recovery_rate_per_sec = recovery_rate_per_sec
        self.max_queue_size = max_queue_size
        self.enable_dlq = enable_dlq
        self.on_permanent_failure = on_permanent_failure
        self._running = False
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._pending: asyncio.PriorityQueue[tuple[int, float, str, QueuedDelivery]] = asyncio.PriorityQueue()
        self._semaphore = asyncio.Semaphore(max_workers)
        self._recovery_task: asyncio.Task[None] | None = None
        self._deduplicator = MessageDeduplicator()
        self._in_flight: set[str] = set()
        self._retry_tasks: set[asyncio.Task[None]] = set()
        self._channel_label_manager = DynamicLabelManager(max_tracked=10)

        # Initialize dead letter queue if enabled
        self._dlq: DeadLetterQueue | None = None
        if enable_dlq:
            self._dlq = DeadLetterQueue(
                base_dir=base_dir,
                storage_provider=storage_provider,
                enqueue_fn=self.enqueue,
            )

        # Metrics
        self._enqueued_counter = meter.create_counter(
            name="delivery_queue_enqueued_total",
            description="Total number of messages enqueued",
            unit="1",
        )
        self._delivered_counter = meter.create_counter(
            name="delivery_queue_delivered_total",
            description="Total number of messages delivered successfully",
            unit="1",
        )
        self._failed_counter = meter.create_counter(
            name="delivery_queue_failed_total",
            description="Total number of messages failed permanently",
            unit="1",
        )
        self._retry_counter = meter.create_counter(
            name="delivery_queue_retry_total",
            description="Total number of retry attempts",
            unit="1",
        )
        self._delivery_duration = meter.create_histogram(
            name="delivery_queue_duration_ms",
            description="Delivery duration in milliseconds",
            unit="ms",
        )
        self._queue_size = meter.create_up_down_counter(
            name="delivery_queue_size",
            description="Current number of pending deliveries",
            unit="1",
        )
        self._batch_size_histogram = meter.create_histogram(
            name="delivery_queue_batch_size",
            description="Batch size distribution for batch processing",
            unit="1",
        )

    async def start(self) -> None:
        """Start queue workers and recover pending deliveries in background."""
        if self._running:
            return

        self._running = True

        # Start dead letter queue if enabled
        if self._dlq:
            await self._dlq.start()
            logger.info("Dead letter queue started")

        # Start background recovery (non-blocking)
        self._recovery_task = asyncio.create_task(self._background_recovery())

        # Start multiple workers
        for worker_id in range(self.max_workers):
            task = asyncio.create_task(self._worker_loop(worker_id))
            self._worker_tasks.append(task)

        logger.info(f"DeliveryQueue started with {self.max_workers} workers")

    async def stop(self) -> None:
        """Stop all queue workers and recovery task."""
        self._running = False

        # Stop dead letter queue if enabled
        if self._dlq:
            await self._dlq.stop()
            logger.info("Dead letter queue stopped")

        # Cancel recovery task
        if self._recovery_task:
            self._recovery_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._recovery_task

        # Cancel all workers
        for task in self._worker_tasks:
            task.cancel()

        # Wait for all workers to finish
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
            self._worker_tasks.clear()

        logger.info("DeliveryQueue stopped")

    async def enqueue(
        self,
        channel: str,
        recipient: str,
        content: dict[str, Any],
        priority: int = 2,
    ) -> str:
        """Enqueue a message for delivery with priority support and backpressure.

        Backpressure strategy:
        - Queue size < max: Async enqueue (high throughput)
        - Queue size >= max: Sync delivery (graceful degradation)

        Args:
            channel: Channel name
            recipient: Recipient ID
            content: Message content dict
            priority: Priority level (0=highest, 1=high, 2=normal, 3=low, default: 2)

        Returns:
            Delivery ID
        """
        with tracer.start_as_current_span("delivery_enqueue") as span:
            span.set_attribute("channel", channel)
            span.set_attribute("recipient", recipient)

            # Check for duplicate
            if self._deduplicator.is_duplicate(channel, recipient, content):
                logger.debug(f"Duplicate message detected, skipping: {channel}/{recipient}")
                span.set_attribute("duplicate", True)
                # Return a pseudo delivery ID for duplicate
                return f"dup_{generate_delivery_id(channel, recipient)}"

            span.set_attribute("duplicate", False)

            delivery_id = generate_delivery_id(channel, recipient)
            span.set_attribute("delivery_id", delivery_id)

            delivery = QueuedDelivery(
                id=delivery_id,
                channel=channel,
                recipient=recipient,
                content=content,
                enqueued_at=time.time(),
                priority=priority,
                retry_count=0,
            )

            # Check for backpressure
            queue_size = self._pending.qsize()

            if queue_size >= self.max_queue_size:
                # Backpressure: Deliver synchronously (bypass queue)
                logger.warning(
                    f"Queue full ({queue_size}/{self.max_queue_size}), delivering synchronously: {delivery_id}"
                )
                span.set_attribute("backpressure", True)

                try:
                    await self.deliver_fn(channel, recipient, content)
                    span.set_attribute("delivery_status", "sync_success")
                    logger.debug(f"Sync delivery successful: {delivery_id}")
                except Exception as e:
                    # Sync delivery failed - persist and enqueue anyway
                    logger.error(f"Sync delivery failed, falling back to queue: {e}")
                    span.set_attribute("delivery_status", "sync_failed_fallback")
                    await save_delivery(delivery, base_dir=self.base_dir, storage_provider=self.storage_provider)
                    await self._pending.put((delivery.priority, delivery.enqueued_at, delivery))
                    self._enqueued_counter.add(1, {"channel": channel})
                    self._queue_size.add(1)

                return delivery_id

            # Normal path: Async enqueue
            span.set_attribute("backpressure", False)

            # Persist to storage
            await save_delivery(delivery, base_dir=self.base_dir, storage_provider=self.storage_provider)

            # Track as in-flight to prevent duplicate recovery
            self._in_flight.add(delivery_id)

            # Add to priority queue (priority, enqueued_at, delivery_id, delivery)
            # Lower priority number = higher priority
            # Use enqueued_at as tiebreaker for FIFO within same priority
            # Use delivery_id as final tiebreaker to avoid comparing frozen dataclass
            await self._pending.put((delivery.priority, delivery.enqueued_at, delivery.id, delivery))

            # Update metrics with cardinality control
            channel_label = self._channel_label_manager.get_label_value(channel)
            priority_label = str(priority)
            self._enqueued_counter.add(1, {"channel": channel_label, "priority": priority_label})
            self._queue_size.add(1)

            logger.debug(f"Enqueued delivery: {delivery_id}")

            return delivery_id

    async def _background_recovery(self) -> None:
        """Recover pending deliveries in background with rate control.

        Fast startup: Scans deliveries quickly without blocking.
        Rate-controlled recovery: Enqueues deliveries at controlled rate.
        """
        try:
            # Brief delay to let initial enqueues and worker startup complete
            await asyncio.sleep(0.1)

            # Fast scan: Load all pending deliveries
            all_deliveries = await load_pending_deliveries(
                base_dir=self.base_dir, storage_provider=self.storage_provider
            )

            # Filter out deliveries already in-flight (enqueued but not yet processed)
            deliveries = [d for d in all_deliveries if d.id not in self._in_flight]

            if not deliveries:
                logger.info("No pending deliveries to recover")
                return

            total_count = len(deliveries)
            logger.info(f"Found {total_count} pending deliveries, starting background recovery")

            now_ms = time.time() * 1000
            eligible, deferred, skipped = await recover_pending_deliveries(deliveries, now_ms)

            # Move skipped deliveries to failed
            for delivery in skipped:
                await move_to_failed(delivery, base_dir=self.base_dir, storage_provider=self.storage_provider)
                logger.warning(f"Delivery {delivery.id} exceeded max retries ({MAX_RETRIES}), moved to failed")

            # Rate-controlled recovery: Enqueue eligible deliveries
            interval_s = 1.0 / self.recovery_rate_per_sec
            recovered_count = 0

            for delivery in eligible:
                if not self._running:
                    break

                await self._pending.put((delivery.priority, delivery.enqueued_at, delivery.id, delivery))
                recovered_count += 1

                # Rate control: Sleep between enqueues
                if recovered_count < len(eligible):
                    await asyncio.sleep(interval_s)

            logger.info(
                f"Background recovery completed: {recovered_count} recovered, "
                f"{len(deferred)} deferred, {len(skipped)} skipped"
            )

        except asyncio.CancelledError:
            logger.info("Background recovery cancelled")
            raise
        except Exception as e:
            logger.error(f"Background recovery failed: {e}")

    async def _worker_loop(self, worker_id: int) -> None:
        """Worker loop that processes deliveries with adaptive batching.

        Adaptive batching strategy:
        - Queue depth < threshold: Immediate delivery (low latency)
        - Queue depth >= threshold: Batch delivery (high throughput)

        Args:
            worker_id: Worker identifier for logging
        """
        logger.debug(f"Worker {worker_id} started")

        while self._running:
            try:
                # Wait for first delivery with timeout (unpack from priority queue)
                _, _, _, delivery = await asyncio.wait_for(self._pending.get(), timeout=1.0)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # Urgent messages (priority=0) bypass batching for lowest latency
            if delivery.priority == 0:
                async with self._semaphore:
                    await self._try_deliver(delivery)
                continue

            # Check queue depth for adaptive batching
            queue_depth = self._pending.qsize()

            if queue_depth < self.batch_threshold:
                # Low load: immediate delivery (latency priority)
                async with self._semaphore:
                    await self._try_deliver(delivery)
            else:
                # High load: batch delivery (throughput priority)
                batch = [delivery]

                # Collect more deliveries up to batch_size or timeout
                batch_timeout_s = self.batch_timeout_ms / 1000.0
                deadline = asyncio.get_event_loop().time() + batch_timeout_s

                while len(batch) < self.batch_size:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        break

                    try:
                        # Get from priority queue
                        _, _, _, next_delivery = await asyncio.wait_for(self._pending.get(), timeout=remaining)
                        batch.append(next_delivery)
                    except TimeoutError:
                        break

                # Process batch with concurrency control (concurrent execution within batch)
                async with self._semaphore:
                    await asyncio.gather(*[self._try_deliver(d) for d in batch], return_exceptions=True)

                # Record batch size for observability
                self._batch_size_histogram.record(len(batch))
                logger.debug(f"Worker {worker_id} processed batch of {len(batch)} deliveries")

        logger.debug(f"Worker {worker_id} stopped")

    async def _try_deliver(self, delivery: QueuedDelivery) -> None:
        """Try to deliver a message with file-based locking.

        Uses file lock to prevent duplicate processing across workers.

        Args:
            delivery: Queued delivery
        """
        # Use file lock to prevent duplicate processing
        async with acquire_delivery_lock(delivery.id, self.base_dir) as locked:
            if not locked:
                # Already being processed by another worker
                logger.debug(f"Delivery {delivery.id} already locked, skipping")
                return
            await self._deliver_impl(delivery)

    async def _deliver_impl(self, delivery: QueuedDelivery) -> None:
        """Actual delivery implementation (without locking logic).

        Args:
            delivery: Queued delivery
        """
        start_time = time.time()

        with tracer.start_as_current_span("delivery_attempt") as span:
            span.set_attribute("delivery_id", delivery.id)
            span.set_attribute("channel", delivery.channel)
            span.set_attribute("recipient", delivery.recipient)
            span.set_attribute("retry_count", delivery.retry_count)

            try:
                # Call delivery function
                await self.deliver_fn(
                    delivery.channel,
                    delivery.recipient,
                    delivery.content,
                )

                # Success - acknowledge
                await ack_delivery(delivery.id, base_dir=self.base_dir, storage_provider=self.storage_provider)
                span.set_attribute("delivery_status", "success")

                # Remove from in-flight tracking
                self._in_flight.discard(delivery.id)

                # Update metrics with cardinality control
                channel_label = self._channel_label_manager.get_label_value(delivery.channel)
                duration_ms = (time.time() - start_time) * 1000
                self._delivered_counter.add(1, {"channel": channel_label})
                self._delivery_duration.record(duration_ms, {"channel": channel_label, "status": "success"})
                self._queue_size.add(-1)

                logger.debug(f"Delivered successfully: {delivery.id}")

            except Exception as e:
                # Failure - handle retry
                span.set_attribute("delivery_status", "failed")
                span.set_attribute("error_type", type(e).__name__)
                span.record_exception(e)

                # Update metrics with cardinality control
                channel_label = self._channel_label_manager.get_label_value(delivery.channel)
                duration_ms = (time.time() - start_time) * 1000
                self._delivery_duration.record(duration_ms, {"channel": channel_label, "status": "failed"})

                await self._handle_failure(delivery, e)

    async def _handle_failure(
        self,
        delivery: QueuedDelivery,
        error: Exception,
    ) -> None:
        """Handle delivery failure.

        Args:
            delivery: Failed delivery
            error: Exception that occurred
        """
        # Get channel label for metrics
        channel_label = self._channel_label_manager.get_label_value(delivery.channel)

        # Check if permanent error
        if is_permanent_error(error):
            logger.warning(f"Delivery {delivery.id} failed with permanent error: {error}, moving to failed")
            await move_to_failed(delivery, base_dir=self.base_dir, storage_provider=self.storage_provider)
            self._in_flight.discard(delivery.id)
            self._failed_counter.add(1, {"channel": channel_label, "reason": "permanent_error"})
            self._queue_size.add(-1)
            if self.on_permanent_failure:
                try:
                    await self.on_permanent_failure(delivery, str(error))
                except Exception as e:
                    logger.error(f"Error in on_permanent_failure callback: {e}")
            return

        # Check if max retries exceeded
        if delivery.retry_count >= MAX_RETRIES:
            logger.warning(f"Delivery {delivery.id} exceeded max retries ({MAX_RETRIES}), moving to failed")
            await move_to_failed(delivery, base_dir=self.base_dir, storage_provider=self.storage_provider)
            self._in_flight.discard(delivery.id)
            self._failed_counter.add(1, {"channel": channel_label, "reason": "max_retries"})
            self._queue_size.add(-1)
            if self.on_permanent_failure:
                try:
                    await self.on_permanent_failure(delivery, str(error))
                except Exception as e:
                    logger.error(f"Error in on_permanent_failure callback: {e}")
            return

        # Update retry count and last attempt
        updated = replace(
            delivery,
            retry_count=delivery.retry_count + 1,
            last_attempt_at=time.time(),
            last_error=str(error),
        )

        # Save updated state
        await save_delivery(updated, base_dir=self.base_dir, storage_provider=self.storage_provider)

        # Calculate backoff
        backoff_ms = compute_backoff_ms(updated.retry_count)
        backoff_s = backoff_ms / 1000.0

        logger.info(
            f"Delivery {delivery.id} failed (retry {updated.retry_count}/{MAX_RETRIES}), "
            f"will retry in {backoff_s:.1f}s: {error}"
        )

        # Update metrics with cardinality control
        channel_label = self._channel_label_manager.get_label_value(delivery.channel)
        self._retry_counter.add(1, {"channel": channel_label})

        # Schedule retry after backoff
        retry_task = asyncio.create_task(self._schedule_retry(updated, backoff_s))
        self._retry_tasks.add(retry_task)
        retry_task.add_done_callback(self._retry_tasks.discard)

    async def _schedule_retry(self, delivery: QueuedDelivery, delay_s: float) -> None:
        """Schedule a retry after delay.

        Args:
            delivery: Delivery to retry
            delay_s: Delay in seconds
        """
        await asyncio.sleep(delay_s)

        if self._running:
            await self._pending.put((delivery.priority, delivery.enqueued_at, delivery.id, delivery))
            logger.debug(f"Retry scheduled: {delivery.id}")
