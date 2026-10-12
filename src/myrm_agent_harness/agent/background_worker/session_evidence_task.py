"""Idle task that mines finished turns' event log for skill-evolution evidence.

[INPUT]
- agent.middlewares._session_context::get_event_logger (POS: per-run EventLogger ContextVar; supplies the backend and the key the session is stored under)
- agent.event_log.trace_builder::build_trace (POS: aggregates the stored events into per-call ToolCallRecords with failure attribution)
- agent.event_log.types::EventFilter (POS: scopes event-log reads to the turns since the task was enqueued)
- agent.errors.fault_side::FaultSide (POS: failure attribution; environment and user-input faults are not skill material)
- agent.skills.evolution.core.engine::SkillEvolutionEngine (POS: CAPTURED evolution from a conversation trajectory)
- agent.skill_agent.context::get_memory_manager (POS: supplies the consolidation LLM used for skill extraction)

[OUTPUT]
- SkillStoreProvider: Zero-arg factory returning the host's shared SkillStore (the host owns its lifecycle).
- register_skill_store_provider: DI entry that binds the SkillStore used for CAPTURED evolution.
- run_session_evidence_extraction: Returns the completion payload; carries a CAPTURED skill proposal when the turns held tool failures worth learning from.

[POS]
Built-in handler of the ``session_evidence_extraction`` idle task. Delivers proposals to the business layer through the
idle completion event; it never writes skills itself. The skill database location is a host decision, so the store
arrives through ``register_skill_store_provider`` instead of being derived from the workspace.

The scope is every turn since the task's ``since`` timestamp: the idle timer restarts on each turn and the registry
keeps only the earliest pending task, so a burst of quick follow-up turns is covered by one run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.errors.fault_side import FaultSide
from myrm_agent_harness.agent.event_log.trace_builder import build_trace
from myrm_agent_harness.agent.event_log.types import EventFilter
from myrm_agent_harness.agent.skill_agent.context import get_memory_manager

if TYPE_CHECKING:
    from myrm_agent_harness.agent.background_worker.registry import IdleTaskRecord
    from myrm_agent_harness.agent.event_log.logger import EventLogger
    from myrm_agent_harness.agent.event_log.trace_types import ToolCallRecord
    from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore

    SkillStoreProvider = Callable[[], SkillStore]

logger = logging.getLogger(__name__)

_skill_store_provider: SkillStoreProvider | None = None

# Environment outages and user-input faults say nothing about how the agent should work.
_NON_SKILL_FAULT_SIDES = frozenset({FaultSide.ENV.value, FaultSide.OWNER.value})
_MAX_ERROR_CHARS = 400


def register_skill_store_provider(provider: SkillStoreProvider | None) -> None:
    """Bind the host's shared SkillStore factory; the harness never closes the returned store."""
    global _skill_store_provider
    _skill_store_provider = provider


async def run_session_evidence_extraction(task: IdleTaskRecord, session_id: str) -> dict[str, object]:
    """Find skill-relevant tool failures in the recent turns and, when any exist, draft a skill proposal."""
    from myrm_agent_harness.agent.middlewares._session_context import get_event_logger

    event_logger = get_event_logger()
    if event_logger is None:
        return {"skipped": True, "reason": "No EventLogger configured"}

    # The chat's log file holds every earlier turn; only the turns since this task was enqueued may feed a proposal.
    since = _scope_start(task, event_logger)
    trace = await build_trace(
        event_logger.backend, event_logger.storage_key, event_filter=EventFilter(start_time=since)
    )
    failures = [c for c in trace.tool_calls if _is_skill_relevant_failure(c)]

    proposal: dict[str, object] | None = None
    if failures:
        logger.info(
            "Found %d skill-relevant tool failures in session %s, triggering CAPTURED evolution",
            len(failures),
            session_id,
        )
        proposal = await _capture_skill_proposal(task, session_id, event_logger, _format_trajectory(trace.tool_calls))

    logger.info("Session evidence extraction completed for %s", session_id)
    return {"failed_tool_calls": len(failures), "proposal": proposal}


def _scope_start(task: IdleTaskRecord, event_logger: EventLogger) -> float:
    """Start of the turns to mine: the enqueue-time ``since``, else the running turn's own start."""
    since = task.payload.get("since")
    if isinstance(since, int | float) and not isinstance(since, bool):
        return float(since)
    return event_logger.started_at


def _is_skill_relevant_failure(call: ToolCallRecord) -> bool:
    return not call.success and call.fault_side not in _NON_SKILL_FAULT_SIDES


def _format_trajectory(calls: list[ToolCallRecord]) -> str:
    """Render the ordered tool calls, keeping each failure with its neighbours and collapsing long clean runs."""
    failed = [not c.success for c in calls]
    lines: list[str] = []
    collapsed = 0
    for i, call in enumerate(calls):
        near_failure = failed[i] or (i > 0 and failed[i - 1]) or (i + 1 < len(calls) and failed[i + 1])
        if not near_failure:
            collapsed += 1
            continue
        if collapsed:
            lines.append(f"... {collapsed} successful tool calls ...")
            collapsed = 0
        lines.append(f"{i + 1}. {_format_call(call)}")
    if collapsed:
        lines.append(f"... {collapsed} successful tool calls ...")
    return "Tool calls in order:\n" + "\n".join(lines)


def _format_call(call: ToolCallRecord) -> str:
    if call.success:
        return f"{call.tool_name} -> ok"
    error = " ".join((call.error or "no error message").split())[:_MAX_ERROR_CHARS]
    return f"{call.tool_name} -> FAILED ({call.fault_side or 'unattributed'}): {error}"


async def _capture_skill_proposal(
    task: IdleTaskRecord, session_id: str, event_logger: EventLogger, trajectory: str
) -> dict[str, object] | None:
    """Run CAPTURED evolution over the trajectory; failures are logged and yield no proposal."""
    try:
        from myrm_agent_harness.agent.skills.evolution.core.engine import SkillEvolutionEngine

        if _skill_store_provider is None:
            logger.warning("No SkillStore provider registered; skipping CAPTURED evolution for session %s", session_id)
            return None

        memory_manager = get_memory_manager()
        llm = memory_manager._consolidation_llm if memory_manager else None
        if llm is None:
            logger.warning("No LLM found for CAPTURED evolution in session %s", session_id)
            return None

        engine = SkillEvolutionEngine(store=_skill_store_provider(), llm=llm, event_log_backend=event_logger.backend)
        proposal = await engine.capture_skill_from_trajectory(trajectory=trajectory, session_id=session_id)

        if proposal is None:
            return None
        logger.info("Successfully extracted skill proposal '%s' from session %s", proposal.skill_id, session_id)
        return {
            "skill_id": proposal.skill_id,
            "reasoning": proposal.reasoning,
            "proposed_content": proposal.proposed_content,
            "score": float(proposal.score),
            "agent_id": task.payload.get("agent_id", "default"),
            "chat_id": task.payload.get("chat_id"),
        }
    except Exception as e:
        logger.error("Failed to trigger CAPTURED evolution for session %s: %s", session_id, e, exc_info=True)
        return None
