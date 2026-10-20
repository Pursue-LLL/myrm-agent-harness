"""[INPUT] SubagentReportItem, SettlementNoticeItem, and OrderedFifoQueueEnvelope.
[OUTPUT] OrderedSettlementFifoQueue enforcing Report-before-Settlement FIFO ordering.
[POS] Queue data structure eliminating race conditions where settlement notices arrive before reports.
"""

from __future__ import annotations

import logging
import threading
from collections import deque

from .types import (
    FifoItemType,
    OrderedFifoQueueEnvelope,
    SettlementNoticeItem,
    SubagentReportItem,
)

logger = logging.getLogger(__name__)


class OrderedSettlementFifoQueue:
    """Strict FIFO queue ensuring subagent reports strictly precede settlement notices.

    Addresses Issue #2600 where automated settlement notices were delivered before
    the subagent's active report was received by the parent model, causing lost work.
    Equipped with thread-safe RLock and bounded capacity protection against memory exhaustion.
    """

    def __init__(self, max_capacity: int = 1000) -> None:
        self.max_capacity = max_capacity
        self._seq_counter: int = 0
        self._queue: deque[OrderedFifoQueueEnvelope] = deque()
        self._lock = threading.RLock()

    def _next_sequence_id(self) -> int:
        self._seq_counter += 1
        return self._seq_counter

    def enqueue_report(
        self,
        report: SubagentReportItem,
        wakes_parent: bool = True,
    ) -> OrderedFifoQueueEnvelope:
        """Enqueue an active subagent progress report with priority over pending settlement."""
        with self._lock:
            if len(self._queue) >= self.max_capacity:
                logger.warning(
                    "FIFO queue capacity exceeded (%d >= %d), shedding oldest quiet envelope",
                    len(self._queue),
                    self.max_capacity,
                )
                self._shed_oldest_non_critical()

            seq = self._next_sequence_id()
            is_critical = (report.severity == "critical")
            effective_wakes = wakes_parent or is_critical

            envelope = OrderedFifoQueueEnvelope(
                sequence_id=seq,
                item_type=FifoItemType.REPORT,
                task_id=report.task_id,
                subagent_id=report.subagent_id,
                wakes_parent=effective_wakes,
                urgent_interrupt=is_critical,
                report_payload=report,
                timestamp=report.timestamp,
            )

            # If critical, immediately prepend to front of queue for urgent parent interruption
            if is_critical:
                self._queue.appendleft(envelope)
                logger.warning(
                    "CRITICAL report enqueued with urgent interrupt for task %s (seq=%d)",
                    report.task_id,
                    seq,
                )
                return envelope

            # Enforce Report-before-Settlement: if there is an unconsumed settlement for the same task,
            # insert this report ahead of that settlement in the queue.
            inserted = False
            new_queue: deque[OrderedFifoQueueEnvelope] = deque()
            while self._queue:
                item = self._queue.popleft()
                if (
                    not inserted
                    and item.task_id == report.task_id
                    and item.item_type == FifoItemType.SETTLEMENT
                ):
                    new_queue.append(envelope)
                    inserted = True
                new_queue.append(item)

            if not inserted:
                new_queue.append(envelope)

            self._queue = new_queue
            logger.debug(
                "Enqueued report for task %s (seq=%d, wakes_parent=%s)",
                report.task_id,
                seq,
                effective_wakes,
            )
            return envelope

    def enqueue_settlement(
        self,
        settlement: SettlementNoticeItem,
    ) -> OrderedFifoQueueEnvelope:
        """Enqueue a terminal settlement notice at the end of the queue."""
        with self._lock:
            if len(self._queue) >= self.max_capacity:
                self._shed_oldest_non_critical()

            seq = self._next_sequence_id()
            envelope = OrderedFifoQueueEnvelope(
                sequence_id=seq,
                item_type=FifoItemType.SETTLEMENT,
                task_id=settlement.task_id,
                subagent_id=settlement.subagent_id,
                wakes_parent=True,
                settlement_payload=settlement,
                timestamp=settlement.timestamp,
            )
            self._queue.append(envelope)
            logger.debug(
                "Enqueued settlement for task %s (seq=%d, status=%s)",
                settlement.task_id,
                seq,
                settlement.status,
            )
            return envelope

    def _shed_oldest_non_critical(self) -> None:
        """Shed oldest quiet non-critical item when max_capacity is reached."""
        for i, item in enumerate(self._queue):
            if not item.wakes_parent:
                del self._queue[i]
                return
        # If all are critical, pop head
        if self._queue:
            self._queue.popleft()

    def drain_batch(self, max_items: int = 100) -> list[OrderedFifoQueueEnvelope]:
        """Drain up to max_items in strictly preserved FIFO order."""
        with self._lock:
            batch: list[OrderedFifoQueueEnvelope] = []
            while self._queue and len(batch) < max_items:
                batch.append(self._queue.popleft())
            return batch

    def pending_count(self) -> int:
        """Return number of pending envelopes in queue."""
        with self._lock:
            return len(self._queue)

    def __len__(self) -> int:
        """Return number of pending envelopes in queue."""
        with self._lock:
            return len(self._queue)

    def peek_all(self) -> list[OrderedFifoQueueEnvelope]:
        """Inspect all queued items without dequeuing."""
        with self._lock:
            return list(self._queue)

    def clear(self) -> None:
        """Clear queue contents."""
        with self._lock:
            self._queue.clear()

    @staticmethod
    def generate_summary_rollup(items: list[OrderedFifoQueueEnvelope]) -> str:
        """Generate structured natural-language rollup summary for drained batch."""
        if not items:
            return "No subagent activity in this step."

        agent_summaries: dict[str, list[str]] = {}
        for item in items:
            subagent = item.subagent_id
            if subagent not in agent_summaries:
                agent_summaries[subagent] = []

            if item.item_type == FifoItemType.REPORT and item.report_payload:
                crit_tag = "[CRITICAL] " if item.urgent_interrupt else ""
                agent_summaries[subagent].append(f"{crit_tag}Report: {item.report_payload.summary}")
            elif item.item_type == FifoItemType.SETTLEMENT and item.settlement_payload:
                agent_summaries[subagent].append(
                    f"Settlement: {item.settlement_payload.status} (exit {item.settlement_payload.exit_code})"
                )

        chunks: list[str] = []
        for agent_id, logs in agent_summaries.items():
            chunks.append(f"[{agent_id}] " + "; ".join(logs))

        return " | ".join(chunks)
