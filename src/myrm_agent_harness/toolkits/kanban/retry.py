"""Manual retry of a FAILED kanban task.

FAILED is terminal for the automatic pipeline (retry budget exhausted), so the
only way back is an explicit decision by an operator (REST/GUI) or the
orchestrator agent (LLM tool). Both go through ``retry_failed_task`` so the
reset set and the idempotency guard live in exactly one place.

[INPUT]
- .types::KanbanTask, TaskEventKind, TaskStatus (POS: Kanban domain types.)
- .protocols::KanbanStore (POS: Protocols for the kanban toolkit; TYPE_CHECKING only.)

[OUTPUT]
- RetrySource: Who requested the retry (audit trail).
- RetryOutcome: Result of a retry request (task + whether it was applied).
- retry_failed_task: Requeue a FAILED task exactly once and record the audit event.

[POS]
Single definition of "retry a FAILED task", shared by the dispatcher and the
orchestrator tool.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from weakref import WeakKeyDictionary

from myrm_agent_harness.toolkits.kanban.types import KanbanTask, TaskEventKind, TaskStatus

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.kanban.protocols import KanbanStore

RetrySource = Literal["human", "orchestrator"]

# One lock per store (the server owns a single store, so this is effectively
# process-wide) without binding a module-level lock to whichever event loop
# touches it first.
_RETRY_LOCKS: WeakKeyDictionary[KanbanStore, asyncio.Lock] = WeakKeyDictionary()


@dataclass(frozen=True, slots=True)
class RetryOutcome:
    """Result of a retry request.

    ``task`` is None when the task does not exist. ``applied`` is False when the
    task exists but was not FAILED (already retried, running, ...): the request is
    an idempotent no-op and ``task`` is its current state.
    """

    task: KanbanTask | None
    applied: bool


def _reset_for_retry(task: KanbanTask, description: str) -> None:
    """Give the task a fresh budget and no trace of the failed attempt on the row.

    The run history keeps the failure details. Status is left to the CAS.
    """
    task.error = ""
    task.retry_count = 0
    task.consecutive_failures = 0
    task.block_cycle_count = 0
    task.completed_at = None
    task.progress_note = None
    if description:
        task.description = description


async def retry_failed_task(
    store: KanbanStore,
    task_id: str,
    *,
    description: str = "",
    reason: str = "",
    source: RetrySource,
) -> RetryOutcome:
    """Move a FAILED task back to READY with a fresh retry budget.

    The reset is written while the task is still FAILED (no worker can claim it
    yet, so the full-row save cannot clobber a claim), then a compare-and-swap
    makes it READY. The per-store lock serialises concurrent double-submits so
    only the first one applies and records the event. A blank *description*
    keeps the original instructions.
    """
    lock = _RETRY_LOCKS.get(store)
    if lock is None:
        lock = _RETRY_LOCKS.setdefault(store, asyncio.Lock())

    async with lock:
        task = await store.get_task(task_id)
        if task is None or task.status != TaskStatus.FAILED:
            return RetryOutcome(task=task, applied=False)

        _reset_for_retry(task, description.strip())
        await store.save_task(task)
        requeued = await store.transition_task_status(task_id, TaskStatus.FAILED, TaskStatus.READY)
        if requeued is None:
            return RetryOutcome(task=await store.get_task(task_id), applied=False)

    payload: dict[str, object] = {
        "from": TaskStatus.FAILED.value,
        "to": TaskStatus.READY.value,
        "source": source,
    }
    if reason.strip():
        payload["reason"] = reason.strip()
    await store.append_event(task_id, TaskEventKind.RETRYING, payload=payload)
    return RetryOutcome(task=requeued, applied=True)
