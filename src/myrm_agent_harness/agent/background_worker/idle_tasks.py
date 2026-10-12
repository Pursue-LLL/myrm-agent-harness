"""Default callbacks and tasks for the idle worker.

[INPUT]
- agent.background_worker.registry::IdleTaskRegistry (POS: Idle Task Registry for crash-resilient persistence and concurrency control.)
- agent.background_worker.shadow_context (POS: Execution-layer bulkhead isolation for background shadow workloads.)
- agent.background_worker.session_evidence_task::run_session_evidence_extraction (POS: Built-in handler that mines the session event log for skill-evolution evidence.)
- agent.skill_agent.context::get_memory_manager (POS: Module-level ContextVar management and background task utilities.)
- runtime.maintenance.scheduler::get_maintenance_scheduler (POS: Global adaptive maintenance scheduler.)
- toolkits.memory.cognitive.consolidator::CognitiveConsolidator (POS: Memory toolkit's cognitive consolidation adapter. Forwards consolidation, forgetting, and health checks to the single maintenance core so the system keeps exactly one maintenance path.)
- runtime.events.bus::get_event_bus (POS: Event Bus Implementation)

[OUTPUT]
- IdleTaskHandler: idle task 处理器协议（task, session_id → 结果字典）
- ContextCompactionHandler: 上下文压缩处理器协议（chat_id, session_id → 结果字典）
- register_idle_task_handler: 注册自定义 idle task 处理器（按 task_type 键控的 DI 入口）
- register_context_compaction_handler: 注册业务层的上下文压缩实现（单槽 DI 入口）
- default_idle_callback: 执行至多一个待处理 idle 任务（会话自身队列或全局队列），返回是否处理了任务
- run_pending_idle_tasks: 会话空闲窗口的调度入口，持续执行直到队列清空

[POS]
空闲维护内置任务层。承载认知巩固、会话证据提炼与上下文压缩等无用户交互期的后台任务，被 idle_worker 调度执行。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol

from myrm_agent_harness.agent.background_worker.registry import IdleTaskRegistry
from myrm_agent_harness.agent.background_worker.session_evidence_task import run_session_evidence_extraction
from myrm_agent_harness.agent.background_worker.shadow_context import (
    restricted_shadow_context,
)
from myrm_agent_harness.agent.skill_agent.context import get_memory_manager
from myrm_agent_harness.runtime.cognitive_clock.signals import (
    get_global_pause_signal,
)
from myrm_agent_harness.runtime.events.bus import get_event_bus
from myrm_agent_harness.runtime.events.idle_events import IdleTaskProgressEvent
from myrm_agent_harness.runtime.maintenance.protocols import (
    CapacityDenial,
    MaintenanceTaskType,
)
from myrm_agent_harness.runtime.maintenance.scheduler import get_maintenance_scheduler
from myrm_agent_harness.toolkits.memory.cognitive.consolidator import (
    CognitiveConsolidator,
)

if TYPE_CHECKING:
    from myrm_agent_harness.agent.background_worker.registry import IdleTaskRecord
    from myrm_agent_harness.runtime.events.bus import EventBus

logger = logging.getLogger(__name__)


class IdleTaskHandler(Protocol):
    """Handler for one idle task type; returns the result payload published with the completion event."""

    async def __call__(self, task: IdleTaskRecord, session_id: str) -> dict[str, object]: ...


class ContextCompactionHandler(Protocol):
    """Business-layer implementation of idle context compaction for one chat."""

    async def __call__(self, chat_id: str, session_id: str) -> dict[str, object]: ...


# Keyed by task.task_type (e.g., "skill_sync")
_idle_task_handlers: dict[str, IdleTaskHandler] = {}
_context_compaction_handler: ContextCompactionHandler | None = None


def register_idle_task_handler(task_type: str, handler: IdleTaskHandler) -> None:
    """Register a custom handler for a specific idle task type."""
    _idle_task_handlers[task_type] = handler


def register_context_compaction_handler(handler: ContextCompactionHandler) -> None:
    """Register the business-layer implementation used by the built-in ``context_compaction`` task."""
    global _context_compaction_handler
    _context_compaction_handler = handler


# Bounds one idle window so a deep queue cannot monopolise the maintenance scheduler.
_MAX_TASKS_PER_IDLE_WINDOW = 8


async def run_pending_idle_tasks(session_id: str, registry: IdleTaskRegistry) -> None:
    """Drain the session's pending idle tasks, stopping on the first deferral or an empty queue."""
    for _ in range(_MAX_TASKS_PER_IDLE_WINDOW):
        if not await default_idle_callback(session_id, registry):
            return


async def default_idle_callback(session_id: str, registry: IdleTaskRegistry) -> bool:
    """Run at most one pending idle task for the session (or the global queue).

    Acquires a task from the IdleTaskRegistry under its atomic lock, requests a CapacityTicket from the
    GlobalAdaptiveScheduler, runs the handler and emits progress events to the Harness EventBus.

    Returns:
        True when a task was executed (successfully or not), False when nothing ran: paused, queue empty,
        or capacity unavailable (the task is returned to ``pending`` for a later window).
    """
    pause_signal = get_global_pause_signal()
    if pause_signal.is_pause_requested:
        logger.info(
            "Idle task execution deferred for session %s due to active cooperative pause (%s).",
            session_id,
            pause_signal.pause_reason,
        )
        return False

    task = await registry.acquire_next(session_id)
    if not task:
        logger.debug("No pending idle tasks for session %s.", session_id)
        return False

    scheduler = get_maintenance_scheduler()
    if not scheduler:
        logger.debug(
            "No MaintenanceScheduler initialized. Skipping idle tasks for session %s.",
            session_id,
        )
        await _revert_task_to_pending(registry, task.id)
        return False

    # 1. Request capacity
    ticket_or_denial = await scheduler.request_capacity(task_type=MaintenanceTaskType.CONTEXT_COMPACTION)

    if isinstance(ticket_or_denial, CapacityDenial):
        logger.info(
            "Idle task denied for session %s (will retry later): %s",
            session_id,
            ticket_or_denial.reason,
        )
        # Revert task status so it can be picked up later
        await _revert_task_to_pending(registry, task.id)
        return False

    ticket = ticket_or_denial
    event_bus = get_event_bus()

    try:
        logger.info(
            " Starting background idle tasks for session %s (Ticket: %s)",
            session_id,
            ticket.ticket_id,
        )

        # 2. Emit the initial "working" progress event
        event_bus.publish(
            IdleTaskProgressEvent(
                session_id=session_id,
                status="working",
                task_name=task.task_type,
                progress_pct=10,
            )
        )

        # 3. Run the actual logic using registered handlers or fallbacks
        cost = 0.0
        event_data: dict[str, object]
        try:
            async with restricted_shadow_context():
                if task.task_type in _idle_task_handlers:
                    handler = _idle_task_handlers[task.task_type]
                    event_data = await handler(task, session_id)
                    raw_cost = event_data.get("cost", 0.0)
                    cost = float(raw_cost) if isinstance(raw_cost, int | float) else 0.0
                elif task.task_type == "cognitive_consolidation":
                    pause_signal = get_global_pause_signal()
                    memory_manager = get_memory_manager()
                    if memory_manager:
                        consolidator = CognitiveConsolidator(memory_manager)
                        event_bus.publish(
                            IdleTaskProgressEvent(
                                session_id=session_id,
                                status="working",
                                task_name=task.task_type,
                                progress_pct=50,
                            )
                        )

                        result = await consolidator.run_consolidation(pause_signal=pause_signal)

                        if result.errors and not result.skipped:
                            raise RuntimeError(f"Consolidation errors: {result.errors}")

                        event_data = result.to_dict()
                    else:
                        logger.warning("MemoryManager not available. Simulating idle task.")
                        await asyncio.sleep(5)
                        event_data = {"simulated": True}
                elif task.task_type == "cognitive_subsumption":
                    # Knowledge subsumption (erasing redundant text memories when a Skill is learned)
                    memory_manager = get_memory_manager()
                    new_knowledge = task.payload.get("new_knowledge", "")
                    if memory_manager and new_knowledge:
                        from myrm_agent_harness.toolkits.memory.strategies.subsumption import (
                            apply_subsumption,
                            find_subsumed_memories,
                        )

                        llm_func = memory_manager._consolidation_llm
                        if not llm_func:
                            logger.warning("No consolidation_llm configured in MemoryManager. Subsumption skipped.")
                            event_data = {
                                "skipped": True,
                                "reason": "No consolidation_llm configured",
                            }
                        else:
                            event_bus.publish(
                                IdleTaskProgressEvent(
                                    session_id=session_id,
                                    status="working",
                                    task_name=task.task_type,
                                    progress_pct=30,
                                )
                            )

                            subsumed_ids = await find_subsumed_memories(
                                manager=memory_manager,
                                new_knowledge=new_knowledge,
                                llm=llm_func,
                                max_candidates=5,
                            )

                            deleted_count = 0
                            if subsumed_ids:
                                deleted_count = await apply_subsumption(memory_manager, subsumed_ids)

                            event_data = {
                                "subsumed_count": deleted_count,
                                "subsumed_ids": subsumed_ids,
                            }

                            if deleted_count > 0:
                                event_bus.publish(
                                    IdleTaskProgressEvent(
                                        session_id=session_id,
                                        status="notification",
                                        task_name=task.task_type,
                                        progress_pct=100,
                                        data={"count": deleted_count, "subsumed_ids": subsumed_ids},
                                    )
                                )
                    else:
                        event_data = {
                            "skipped": True,
                            "reason": "No MemoryManager or empty new_knowledge",
                        }
                elif task.task_type == "session_evidence_extraction":
                    event_data = await run_session_evidence_extraction(task, session_id)
                elif task.task_type == "context_compaction":
                    event_data = await _run_context_compaction(session_id, task, event_bus)
                else:
                    logger.warning(f"Unknown task type or no handler registered for: {task.task_type}")
                    await asyncio.sleep(1)
                    event_data = {"unhandled": True}

            # 3.1 Report Success to Circuit Breaker
            scheduler.report_outcome(ticket.task_type, success=True, cost=cost)

        except Exception as handler_err:
            # 3.2 Report Failure to Circuit Breaker (Exponential Backoff)
            scheduler.report_outcome(ticket.task_type, success=False, cost=cost)
            raise handler_err

        # 4. Mark as complete and emit event
        await registry.mark_completed(task.id)

        event_bus.publish(
            IdleTaskProgressEvent(
                session_id=session_id,
                status="completed",
                task_name=task.task_type,
                progress_pct=100,
                data=event_data,
            )
        )
        logger.info("Idle task %s completed successfully for session %s", task.id, session_id)

    except asyncio.CancelledError:
        # A newer turn replaced this idle window; keep the unfinished task for the next one.
        await _revert_task_to_pending(registry, task.id)
        raise
    except Exception as e:
        logger.error(
            "Error in idle task %s for session %s: %s",
            task.id,
            session_id,
            e,
            exc_info=True,
        )
        await registry.mark_error(task.id)
        event_bus.publish(IdleTaskProgressEvent(session_id=session_id, status="error", task_name=task.task_type))
    finally:
        # 5. Must release capacity and reset UI to purely idle
        await scheduler.release_capacity(ticket)
        # Small delay before resetting to idle to let the terminal status linger briefly
        await asyncio.sleep(2)
        event_bus.publish(IdleTaskProgressEvent(session_id=session_id, status="idle"))
    return True


async def _run_context_compaction(
    session_id: str,
    task: IdleTaskRecord,
    event_bus: EventBus,
) -> dict[str, object]:
    """Compress idle session context through the business-layer handler.

    The handler returns only a result summary (no ``llm``/``messages`` are exposed to this
    runner), so no prefix-cache preheat is performed here.
    """
    chat_id = task.payload.get("chat_id", "")
    if not chat_id:
        logger.info("context_compaction skipped: no chat_id in payload (session %s)", session_id)
        return {"skipped": True, "reason": "no chat_id"}

    event_bus.publish(
        IdleTaskProgressEvent(
            session_id=session_id,
            status="working",
            task_name=task.task_type,
            progress_pct=20,
        )
    )

    compacted = False
    try:
        if _context_compaction_handler:
            compact_result = await _context_compaction_handler(chat_id, session_id)
            compacted = bool(compact_result.get("compacted", False))
        else:
            logger.info(
                "context_compaction: no handler registered. "
                "Business layer should register via register_context_compaction_handler()."
            )
    except Exception as e:
        logger.error("context_compaction error for chat %s: %s", chat_id, e, exc_info=True)

    return {"compacted": compacted, "chat_id": chat_id}


async def _revert_task_to_pending(registry: IdleTaskRegistry, task_id: int) -> None:
    try:
        from myrm_agent_harness.utils.db.sqlite import connect_async

        async with connect_async(registry.db_path) as db:
            await db.execute("UPDATE idle_tasks SET status='pending' WHERE id=?", (task_id,))
            await db.commit()
    except Exception as e:
        logger.error("Failed to revert task %s to pending: %s", task_id, e)
