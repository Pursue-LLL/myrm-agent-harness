"""Idle task that mines a finished turn's event log for skill-evolution evidence.

[INPUT]
- agent.middlewares._session_context::get_event_logger (POS: per-run EventLogger ContextVar; supplies the backend and the key the session is stored under)
- agent.event_log.evidence_extractor::SessionEvidenceExtractor (POS: derives hotspots and anti-patterns from the stored event log)
- agent.event_log.types::EventFilter (POS: scopes event-log reads to the current turn)
- agent.skills.evolution.core.engine::SkillEvolutionEngine (POS: CAPTURED evolution from a conversation trajectory)
- agent.skill_agent.context::get_memory_manager (POS: supplies the consolidation LLM used for skill extraction)

[OUTPUT]
- SkillStoreProvider: Zero-arg factory returning the host's shared SkillStore (the host owns its lifecycle).
- register_skill_store_provider: DI entry that binds the SkillStore used for CAPTURED evolution.
- run_session_evidence_extraction: Returns the completion payload; carries a CAPTURED skill proposal when failures or corrections were found.

[POS]
Built-in handler of the ``session_evidence_extraction`` idle task. Delivers proposals to the business layer through the
idle completion event; it never writes skills itself. The skill database location is a host decision, so the store
arrives through ``register_skill_store_provider`` instead of being derived from the workspace.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.event_log.types import EventFilter
from myrm_agent_harness.agent.skill_agent.context import get_memory_manager

if TYPE_CHECKING:
    from myrm_agent_harness.agent.background_worker.registry import IdleTaskRecord
    from myrm_agent_harness.agent.event_log.logger import EventLogger
    from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore

    SkillStoreProvider = Callable[[], SkillStore]

logger = logging.getLogger(__name__)

_skill_store_provider: SkillStoreProvider | None = None


def register_skill_store_provider(provider: SkillStoreProvider | None) -> None:
    """Bind the host's shared SkillStore factory; the harness never closes the returned store."""
    global _skill_store_provider
    _skill_store_provider = provider


async def run_session_evidence_extraction(task: IdleTaskRecord, session_id: str) -> dict[str, object]:
    """Extract anti-patterns from the session event log and, when any exist, draft a skill proposal."""
    from myrm_agent_harness.agent.middlewares._session_context import get_event_logger

    event_logger = get_event_logger()
    if event_logger is None:
        return {"skipped": True, "reason": "No EventLogger configured"}

    from myrm_agent_harness.agent.event_log.evidence_extractor import SessionEvidenceExtractor

    # The chat's log file holds every earlier turn; only this turn's events may feed a proposal.
    this_turn = EventFilter(start_time=event_logger.started_at)
    extractor = SessionEvidenceExtractor(event_logger.backend)
    digest = await extractor.extract_digest(event_logger.storage_key, this_turn)

    proposal: dict[str, object] | None = None
    if digest and digest.anti_patterns:
        logger.info(
            "Found %d anti-patterns in session %s, triggering CAPTURED evolution",
            len(digest.anti_patterns),
            session_id,
        )
        proposal = await _capture_skill_proposal(task, session_id, event_logger, this_turn)

    logger.info("Session evidence extraction completed for %s", session_id)
    return {
        "extracted": bool(digest),
        "anti_patterns_count": len(digest.anti_patterns) if digest else 0,
        "proposal": proposal,
    }


async def _capture_skill_proposal(
    task: IdleTaskRecord, session_id: str, event_logger: EventLogger, this_turn: EventFilter
) -> dict[str, object] | None:
    """Run CAPTURED evolution over the session trajectory; failures are logged and yield no proposal."""
    try:
        from myrm_agent_harness.agent.skills.evolution.core.engine import SkillEvolutionEngine

        if _skill_store_provider is None:
            logger.warning("No SkillStore provider registered; skipping CAPTURED evolution for session %s", session_id)
            return None

        events = await event_logger.backend.get_events(event_logger.storage_key, this_turn)
        trajectory = "\n".join(f"[{e.event_type}] {e.data}" for e in events)

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
