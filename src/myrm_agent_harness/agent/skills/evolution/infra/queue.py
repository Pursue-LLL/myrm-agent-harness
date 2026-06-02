"""Background async evolution queue (收益6/10).

Defers non-critical evolutions to background queue to avoid blocking main flow.
Inspired by OpenSpace's async processor but simplified using asyncio.Queue.

[INPUT]
- agent.skills.evolution.core.types::EvolutionRequest, (POS: Data types for skill evolution system.)

[OUTPUT]
- QueuePriority: Evolution queue priority levels.
- QueuedEvolution: Evolution task in the queue.
- EvolutionQueue: Background async evolution queue with priority levels.
- get_evolution_queue: Get or create global evolution queue instance.

[POS]
Defers non-critical evolutions to background queue to avoid blocking main flow.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from myrm_agent_harness.agent.skills.evolution.core.types import EvolutionProposal, EvolutionRequest

logger = logging.getLogger(__name__)


class QueuePriority(StrEnum):
    """Evolution queue priority levels."""

    CRITICAL = "critical"  # Consecutive failures, needs immediate fix
    HIGH = "high"  # Low success rate
    NORMAL = "normal"  # Regular optimization
    LOW = "low"  # Background learning


@dataclass
class QueuedEvolution:
    """Evolution task in the queue."""

    request: EvolutionRequest
    priority: QueuePriority
    retry_count: int = 0
    max_retries: int = 2


class EvolutionQueue:
    """Background async evolution queue with priority levels.

    Processes evolution requests asynchronously to avoid blocking main flow.
    """

    def __init__(self, worker_count: int = 2, max_queue_size: int = 100):
        """Initialize evolution queue.

        Args:
            worker_count: Number of concurrent workers
            max_queue_size: Maximum queue size (oldest dropped if full)
        """
        self.worker_count = worker_count
        self.max_queue_size = max_queue_size

        # Priority queues (CRITICAL > HIGH > NORMAL > LOW)
        self._queues: dict[QueuePriority, asyncio.Queue[QueuedEvolution]] = {
            QueuePriority.CRITICAL: asyncio.Queue(),
            QueuePriority.HIGH: asyncio.Queue(),
            QueuePriority.NORMAL: asyncio.Queue(),
            QueuePriority.LOW: asyncio.Queue(),
        }

        # Worker tasks
        self._workers: list[asyncio.Task[None]] = []
        self._running = False

        # Evolution handler (set by business layer)
        self._evolution_handler: Callable[[EvolutionRequest], Awaitable[EvolutionProposal | None]] | None = None

        # Stats
        self._processed_count = 0
        self._failed_count = 0

    def set_evolution_handler(
        self,
        handler: Callable[[EvolutionRequest], Awaitable[EvolutionProposal | None]],
    ) -> None:
        """Set the evolution handler function.

        Args:
            handler: Async function that processes evolution requests
        """
        self._evolution_handler = handler

    async def enqueue(self, request: EvolutionRequest, priority: QueuePriority = QueuePriority.NORMAL) -> bool:
        """Add evolution request to queue.

        Args:
            request: Evolution request
            priority: Queue priority level

        Returns:
            True if enqueued successfully
        """
        queue = self._queues[priority]

        # Drop oldest if queue full
        if queue.qsize() >= self.max_queue_size // 4:
            try:
                _ = queue.get_nowait()
                logger.warning("Queue full, dropped oldest %s task", priority)
            except asyncio.QueueEmpty:
                pass

        queued = QueuedEvolution(request=request, priority=priority)
        await queue.put(queued)

        logger.debug(
            "Enqueued %s evolution for skill: %s (priority=%s)", request.evolution_type, request.skill_id, priority
        )
        return True

    async def start(self) -> None:
        """Start background workers."""
        if self._running:
            logger.warning("Evolution queue already running")
            return

        self._running = True

        # Start worker tasks
        for i in range(self.worker_count):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)

        logger.info("Evolution queue started with %d workers", self.worker_count)

    async def stop(self) -> None:
        """Stop background workers and wait for completion."""
        if not self._running:
            return

        self._running = False

        # Cancel all workers
        for worker in self._workers:
            worker.cancel()

        # Wait for all workers to finish
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

        logger.info("Evolution queue stopped")

    async def _worker(self, worker_id: int) -> None:
        """Background worker that processes evolution queue."""
        logger.debug("Worker %d started", worker_id)

        while self._running:
            try:
                # Get next task (priority: CRITICAL > HIGH > NORMAL > LOW)
                task = await self._get_next_task()

                if not task:
                    await asyncio.sleep(0.5)  # Wait for new tasks
                    continue

                # Process evolution
                await self._process_evolution(task)

            except asyncio.CancelledError:
                logger.debug("Worker %d cancelled", worker_id)
                break
            except Exception as e:
                logger.error("Worker %d error: %s", worker_id, e, exc_info=True)
                await asyncio.sleep(1)  # Back off on error

        logger.debug("Worker %d stopped", worker_id)

    async def _get_next_task(self) -> QueuedEvolution | None:
        """Get next task from priority queues."""
        # Check queues in priority order
        for priority in QueuePriority:
            queue = self._queues[priority]
            try:
                return queue.get_nowait()
            except asyncio.QueueEmpty:
                continue

        return None

    async def _process_evolution(self, task: QueuedEvolution) -> None:
        """Process single evolution task."""
        if not self._evolution_handler:
            logger.error("No evolution handler set, dropping task")
            return

        try:
            logger.info(
                "Processing %s evolution: %s (priority=%s, retry=%d)",
                task.request.evolution_type,
                task.request.skill_id,
                task.priority,
                task.retry_count,
            )

            result = await self._evolution_handler(task.request)

            if result:
                self._processed_count += 1
                logger.info("Evolution completed: %s", result.skill_id)
            else:
                # Evolution failed, retry if allowed
                if task.retry_count < task.max_retries:
                    task.retry_count += 1
                    await self._queues[task.priority].put(task)
                    logger.warning("Evolution failed, retry %d/%d", task.retry_count, task.max_retries)
                else:
                    self._failed_count += 1
                    logger.error("Evolution failed after %d retries", task.max_retries)

        except Exception as e:
            logger.error("Evolution processing error: %s", e, exc_info=True)
            self._failed_count += 1

    def get_stats(self) -> dict[str, int]:
        """Get queue statistics."""
        return {
            "processed": self._processed_count,
            "failed": self._failed_count,
            "queued_critical": self._queues[QueuePriority.CRITICAL].qsize(),
            "queued_high": self._queues[QueuePriority.HIGH].qsize(),
            "queued_normal": self._queues[QueuePriority.NORMAL].qsize(),
            "queued_low": self._queues[QueuePriority.LOW].qsize(),
            "workers": len(self._workers),
        }


# Global queue instance (business layer can configure)
_global_queue: EvolutionQueue | None = None


def get_evolution_queue(worker_count: int = 2) -> EvolutionQueue:
    """Get or create global evolution queue instance."""
    global _global_queue

    if _global_queue is None:
        _global_queue = EvolutionQueue(worker_count=worker_count)

    return _global_queue
