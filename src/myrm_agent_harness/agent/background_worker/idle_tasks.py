"""Default callbacks and tasks for the idle worker.

[INPUT]
- agent.streaming.types::AgentEventType (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- runtime.events.idle_events::IdleTaskProgressEvent (POS: Events related to idle background tasks.)
- runtime.events.bus::EventBus (POS: In-process publish/subscribe event bus.)
- runtime.maintenance.protocols::CapacityDenial, (POS: Maintenance scheduling protocols and data types.)
- toolkits.memory.cognitive.consolidator::CognitiveConsolidator (POS: @input: MemoryManager)
- agent.event_log.evidence_extractor::SessionEvidenceExtractor (POS: Data mining engine for Task-Adaptive Context. Runs periodically in idle_tasks to analyze failed tool calls and user interruptions, generating evidence.)
- agent.event_log.types::EventPayload, StructuredEvent (POS: Single source of truth for event log data structures.)
- agent.context_management.preheat::preheat_prefix_cache (POS: Prefix cache preheat utility for idle compression pipeline.)
- agent.background_worker.registry::IdleTaskRecord (POS: Idle Task Registry for crash-resilient persistence and concurrency control.)

[OUTPUT]
- register_idle_task_handler: Register a custom handler for a specific idle task type.
- default_idle_callback: Default idle task to run when the session is inactive.

[POS]
Default callbacks and tasks for the idle worker.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.agent._skill_agent_context import get_memory_manager
from myrm_agent_harness.agent.background_worker.registry import IdleTaskRegistry
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.runtime.events.bus import get_event_bus
from myrm_agent_harness.runtime.events.idle_events import IdleTaskProgressEvent
from myrm_agent_harness.runtime.maintenance.protocols import CapacityDenial, MaintenanceTaskType
from myrm_agent_harness.runtime.maintenance.scheduler import get_maintenance_scheduler
from myrm_agent_harness.toolkits.memory.cognitive.consolidator import CognitiveConsolidator

if TYPE_CHECKING:
    from myrm_agent_harness.agent.background_worker.registry import IdleTaskRecord
    from myrm_agent_harness.runtime.events.bus import EventBus

logger = logging.getLogger(__name__)

# Production-grade Dependency Injection for Idle Tasks
# Keyed by task.task_type (e.g., "cognitive_consolidation", "wiki_maintenance")
_idle_task_handlers = {}


def register_idle_task_handler(task_type: str, handler) -> None:
    """Register a custom handler for a specific idle task type.

    Handler signature: async def handler(task, session_id: str) -> dict
    """
    _idle_task_handlers[task_type] = handler


async def default_idle_callback(session_id: str, registry: IdleTaskRegistry) -> None:
    """Default idle task to run when the session is inactive.

    Checks the IdleTaskRegistry for pending tasks using atomic lock.
    If a task is acquired, requests CapacityTicket from GlobalAdaptiveScheduler.
    If successful, runs memory consolidation or pending background tasks,
    and emits progress events to the Harness EventBus.
    """
    task = await registry.acquire_next(session_id)
    if not task:
        logger.debug("No pending idle tasks for session %s.", session_id)
        return

    scheduler = get_maintenance_scheduler()
    if not scheduler:
        logger.debug("No MaintenanceScheduler initialized. Skipping idle tasks for session %s.", session_id)
        await registry.mark_error(task.id)
        return

    # 1. Request capacity
    ticket_or_denial = await scheduler.request_capacity(task_type=MaintenanceTaskType.CONTEXT_COMPACTION)

    if isinstance(ticket_or_denial, CapacityDenial):
        logger.info("Idle task denied for session %s (will retry later): %s", session_id, ticket_or_denial.reason)
        # Revert task status so it can be picked up later
        await _revert_task_to_pending(registry, task.id)
        return

    ticket = ticket_or_denial
    event_bus = get_event_bus()

    try:
        logger.info(" Starting background idle tasks for session %s (Ticket: %s)", session_id, ticket.ticket_id)

        # 2. Emit UI "Started" event
        event_bus.publish(
            IdleTaskProgressEvent(
                session_id=session_id,
                status="working",
                task_name=task.task_type,
                message=" 正在为您归纳记忆碎片...",
                progress_pct=10,
            )
        )

        # 3. Run the actual logic using registered handlers or fallbacks
        cost = 0.0
        try:
            if task.task_type in _idle_task_handlers:
                handler = _idle_task_handlers[task.task_type]
                event_data = await handler(task, session_id)
                cost = event_data.get("cost", 0.0) if isinstance(event_data, dict) else 0.0
            elif task.task_type == "cognitive_consolidation":
                memory_manager = get_memory_manager()
                if memory_manager:
                    consolidator = CognitiveConsolidator(memory_manager)
                    event_bus.publish(
                        IdleTaskProgressEvent(
                            session_id=session_id,
                            status="working",
                            task_name=task.task_type,
                            message=" 正在合并相关记忆网络...",
                            progress_pct=50,
                        )
                    )

                    result = await consolidator.run_consolidation()

                    if result.errors and not result.skipped:
                        raise RuntimeError(f"Consolidation errors: {result.errors}")

                    event_data = result.to_dict()
                else:
                    logger.warning("MemoryManager not available. Simulating idle task.")
                    await asyncio.sleep(5)
                    event_data = {"simulated": True}
            elif task.task_type == "cognitive_derivation":
                memory_manager = get_memory_manager()
                chat_id = task.payload.get("chat_id", "")
                messages = task.payload.get("messages", [])
                if memory_manager and chat_id and messages:
                    from myrm_agent_harness.toolkits.memory.cognitive.deriver import CognitiveDeriver

                    deriver = CognitiveDeriver(memory_manager)
                    event_bus.publish(
                        IdleTaskProgressEvent(
                            session_id=session_id,
                            status="working",
                            task_name=task.task_type,
                            message=" 正在深度盘点您的隐性沟通偏好...",
                            progress_pct=40,
                        )
                    )

                    result = await deriver.run_derivation(session_id, chat_id, messages)
                    event_data = result

                    extracted_count = result.get("extracted_count", 0)
                    has_disruptive_change = result.get("has_disruptive_change", False)
                    if extracted_count > 0:
                        urgency = "notify" if has_disruptive_change else "silent"
                        ui_message = " 认知已更新：已牢记您最新指示的沟通偏好。" if has_disruptive_change else ""

                        event_bus.publish(
                            IdleTaskProgressEvent(
                                session_id=session_id,
                                status="notification" if has_disruptive_change else "completed",
                                task_name=task.task_type,
                                message=ui_message,
                                progress_pct=100,
                                data={
                                    "type": "cognitive_derivation",
                                    "extracted_count": extracted_count,
                                    "urgency": urgency,
                                },
                            )
                        )
                else:
                    event_data = {"skipped": True, "reason": "Missing MemoryManager, chat_id, or messages"}
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
                        event_data = {"skipped": True, "reason": "No consolidation_llm configured"}
                    else:
                        event_bus.publish(
                            IdleTaskProgressEvent(
                                session_id=session_id,
                                status="working",
                                task_name=task.task_type,
                                message=" 正在为新技能擦除冗余认知包袱...",
                                progress_pct=30,
                            )
                        )

                        subsumed_ids = await find_subsumed_memories(
                            manager=memory_manager, new_knowledge=new_knowledge, llm_func=llm_func, max_candidates=5
                        )

                        deleted_count = 0
                        if subsumed_ids:
                            deleted_count = await apply_subsumption(memory_manager, subsumed_ids)

                        event_data = {"subsumed_count": deleted_count, "subsumed_ids": subsumed_ids}

                        if deleted_count > 0:
                            # Emitting special SSE event to Frontend
                            event_bus.publish(
                                IdleTaskProgressEvent(
                                    session_id=session_id,
                                    status="notification",
                                    task_name=task.task_type,
                                    message=f" 认知升维完成：已提炼技能，并在后台静默擦除了 {deleted_count} 条冗余历史记忆。",
                                    progress_pct=100,
                                    data={
                                        "type": AgentEventType.COGNITIVE_CONSOLIDATION.value,
                                        "count": deleted_count,
                                        "subsumed_ids": subsumed_ids,
                                    },
                                )
                            )
                else:
                    event_data = {"skipped": True, "reason": "No MemoryManager or empty new_knowledge"}
            elif task.task_type == "session_evidence_extraction":
                from myrm_agent_harness.agent.middlewares.approval import get_event_logger

                event_logger = get_event_logger()
                if event_logger and event_logger._backend:
                    from myrm_agent_harness.agent.event_log.evidence_extractor import SessionEvidenceExtractor

                    extractor = SessionEvidenceExtractor(event_logger._backend)
                    digest = await extractor.extract_digest(session_id)
                    if digest:
                        import time

                        from myrm_agent_harness.agent.event_log.types import EventPayload, StructuredEvent

                        await event_logger._backend.append(
                            [
                                StructuredEvent(
                                    sequence=999999,
                                    timestamp=time.time(),
                                    event_type="trace_run_digest",
                                    session_id=session_id,
                                    data=EventPayload(**digest.to_dict()),
                                )
                            ]
                        )

                        # Trigger CAPTURED evolution if there are anti-patterns (failures/corrections)
                        if digest.anti_patterns:
                            logger.info("Found %d anti-patterns in session %s, triggering CAPTURED evolution", len(digest.anti_patterns), session_id)
                            try:
                                from myrm_agent_harness.agent.skills.evolution.core.engine import SkillEvolutionEngine
                                from myrm_agent_harness.agent.skills.evolution.db.store import get_skill_store
                                from myrm_agent_harness.agent.middlewares._session_context import get_workspace_root

                                # Get trajectory text
                                events = await event_logger._backend.get_events(session_id)
                                trajectory = "\n".join([f"[{e.event_type}] {e.data}" for e in events])

                                # Need LLM for extraction
                                memory_manager = get_memory_manager()
                                llm = memory_manager._consolidation_llm.keywords.get('llm') if memory_manager and hasattr(memory_manager, '_consolidation_llm') else None
                                
                                # Default to something if no LLM found in memory_manager
                                if llm is None:
                                    logger.warning("No LLM found for CAPTURED evolution in session %s", session_id)
                                else:
                                    store = get_skill_store(get_workspace_root())
                                    engine = SkillEvolutionEngine(store=store, llm=llm, event_log_backend=event_logger._backend)
                                    
                                    # Extract proposal
                                    proposal = await engine.capture_skill_from_trajectory(trajectory=trajectory, session_id=session_id)
                                    
                                    if proposal:
                                        logger.info("Successfully extracted skill proposal '%s' from session %s", proposal.skill_id, session_id)
                                        # Save proposal as DRAFT skill
                                        from myrm_agent_harness.agent.skills.evolution.core.types import SkillRecord
                                        import json
                                        
                                        # Use custom tags to store draft status and proposal reasoning
                                        env = proposal.environment or EnvironmentFingerprint(custom_tags={})
                                        env.custom_tags["is_draft"] = "true"
                                        env.custom_tags["proposal_reasoning"] = proposal.reasoning
                                        env.custom_tags["proposal_score"] = str(proposal.score)
                                        
                                        draft_record = SkillRecord(
                                            skill_id=proposal.skill_id,
                                            name=proposal.skill_id,
                                            description=proposal.reasoning[:200],  # Use reasoning as initial description
                                            content=proposal.proposed_content,
                                            path="",  # No path yet, it's a draft in DB
                                            environment=env,
                                            lineage=None, # type: ignore
                                        )
                                        
                                        # Save to DB
                                        store.save_skill(draft_record)
                                        logger.info("Saved draft skill '%s' to DB", proposal.skill_id)
                                        
                            except Exception as e:
                                logger.error("Failed to trigger CAPTURED evolution for session %s: %s", session_id, e, exc_info=True)

                    event_data = {
                        "extracted": bool(digest),
                        "anti_patterns_count": len(digest.anti_patterns) if digest else 0,
                    }
                    logger.info("Session evidence extraction completed for %s", session_id)
                else:
                    event_data = {"skipped": True, "reason": "No EventLogger configured"}
            elif task.task_type == "context_compaction":
                event_data = await _run_context_compaction(session_id, task, event_bus)
                cost = event_data.get("preheat_cost", 0.0)
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
                message=" 记忆碎片整理完毕" if task.task_type == "cognitive_consolidation" else " 任务已完成",
                progress_pct=100,
                data=event_data,
            )
        )
        logger.info(" Idle task %s completed successfully for session %s", task.id, session_id)

    except Exception as e:
        logger.error("Error in idle task %s for session %s: %s", task.id, session_id, e, exc_info=True)
        await registry.mark_error(task.id)
        event_bus.publish(IdleTaskProgressEvent(session_id=session_id, status="error", message=" 后台任务执行出错"))
    finally:
        # 5. Must release capacity and reset UI to purely idle
        await scheduler.release_capacity(ticket)
        # Small delay before resetting to idle to let the "completed" message linger briefly
        await asyncio.sleep(2)
        event_bus.publish(IdleTaskProgressEvent(session_id=session_id, status="idle", message=" 闲置中"))


async def _run_context_compaction(
    session_id: str,
    task: IdleTaskRecord,
    event_bus: EventBus,
) -> dict[str, object]:
    """Compress idle session context and optionally preheat the provider's prefix cache."""
    chat_id = task.payload.get("chat_id", "")
    if not chat_id:
        logger.info("context_compaction skipped: no chat_id in payload (session %s)", session_id)
        return {"skipped": True, "reason": "no chat_id"}

    event_bus.publish(
        IdleTaskProgressEvent(
            session_id=session_id,
            status="working",
            task_name=task.task_type,
            message=" Optimizing conversation context...",
            progress_pct=20,
        )
    )

    compacted = False
    preheated = False

    try:
        from myrm_agent_harness.agent.context_management.preheat import preheat_prefix_cache

        compact_handler = _idle_task_handlers.get("_context_compact_impl")
        if compact_handler:
            compact_result = await compact_handler(chat_id, session_id)
            compacted = compact_result.get("compacted", False) if isinstance(compact_result, dict) else False

            if compacted:
                llm = compact_result.get("llm")
                messages = compact_result.get("messages")
                model_name = compact_result.get("model_name", "")
                if llm and messages:
                    event_bus.publish(
                        IdleTaskProgressEvent(
                            session_id=session_id,
                            status="working",
                            task_name=task.task_type,
                            message=" Warming up cache...",
                            progress_pct=70,
                        )
                    )
                    preheated = await preheat_prefix_cache(llm, messages, model_name)
        else:
            logger.info(
                "context_compaction: no _context_compact_impl handler registered. "
                "Business layer should register via register_idle_task_handler('_context_compact_impl', handler)."
            )
    except Exception as e:
        logger.error("context_compaction error for chat %s: %s", chat_id, e, exc_info=True)

    return {"compacted": compacted, "preheated": preheated, "chat_id": chat_id, "preheat_cost": 0.0}


async def _revert_task_to_pending(registry: IdleTaskRegistry, task_id: int) -> None:
    try:
        from myrm_agent_harness.utils.db.sqlite import connect_async

        async with connect_async(registry.db_path) as db:
            await db.execute("UPDATE idle_tasks SET status='pending' WHERE id=?", (task_id,))
            await db.commit()
    except Exception as e:
        logger.error("Failed to revert task %s to pending: %s", task_id, e)
