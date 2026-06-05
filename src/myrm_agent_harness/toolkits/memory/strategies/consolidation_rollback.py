"""Consolidation rollback — reverse the most recent auto-consolidation cycle.

[INPUT]
- memory.manager::MemoryManager (POS: unified memory manager facade)
- memory.types::{EpisodicMemory, SemanticMemory, MemoryType} (POS: memory data models)

[OUTPUT]
- get_last_consolidation_summary: Fetch summary of last consolidation for UI display
- rollback_last_consolidation: Execute reversal of last consolidation operations
- ConsolidationRollbackResult: Result statistics

[POS]
Consolidation rollback. Leverages existing soft-deletion and metadata['previous_content']
mechanisms to reverse consolidation operations without requiring separate snapshot storage.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


class ConsolidationRollbackResult(BaseModel):
    """Result of a consolidation rollback operation."""

    rolled_back: int = 0
    skipped_conflict: int = 0
    errors: int = 0
    conflict_ids: list[str] = Field(default_factory=list)


def _parse_affected_ids(content: str) -> list[str]:
    """Extract affected_ids from consolidation event content."""
    match = re.search(r"\[affected_ids:([^\]]+)\]", content)
    if not match:
        return []
    return [aid.strip() for aid in match.group(1).split(",") if aid.strip()]


async def get_last_consolidation_summary(manager: MemoryManager) -> dict[str, object] | None:
    """Get the last consolidation event summary for UI display.

    Returns None if no consolidation has ever run, otherwise returns
    a dict with event_id, timestamp, stats summary, affected_ids, and rollback_available flag.
    """
    from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, MemoryType

    events = await manager.list_memories(MemoryType.EPISODIC, limit=50)
    consolidation_events = [e for e in events if isinstance(e, EpisodicMemory) and e.event_type == "consolidation"]
    if not consolidation_events:
        return None

    consolidation_events.sort(key=lambda e: e.created_at, reverse=True)
    latest = consolidation_events[0]
    affected_ids = _parse_affected_ids(latest.content)

    rollback_available = True
    conflict_ids: list[str] = []
    for aid in affected_ids:
        mem = await manager.get_memory(aid)
        if mem and mem.updated_at > latest.created_at:
            rollback_available = False
            conflict_ids.append(aid)

    return {
        "event_id": latest.id,
        "timestamp": latest.created_at.isoformat(),
        "summary": latest.content.split("\n")[0],
        "affected_ids": affected_ids,
        "affected_count": len(affected_ids),
        "rollback_available": rollback_available,
        "conflict_ids": conflict_ids,
    }


async def rollback_last_consolidation(manager: MemoryManager) -> ConsolidationRollbackResult:
    """Rollback the most recent consolidation cycle by reversing its operations.

    Uses existing metadata preserved by update_memory (previous_content),
    correct_memory (demote+new), and MERGE (soft deletion) to reverse changes.
    Refuses to rollback individual memories that were manually modified after consolidation.
    """
    from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, MemoryType, SemanticMemory

    result = ConsolidationRollbackResult()

    events = await manager.list_memories(MemoryType.EPISODIC, limit=50)
    consolidation_events = [e for e in events if isinstance(e, EpisodicMemory) and e.event_type == "consolidation"]
    if not consolidation_events:
        return result

    consolidation_events.sort(key=lambda e: e.created_at, reverse=True)
    latest = consolidation_events[0]
    affected_ids = _parse_affected_ids(latest.content)
    if not affected_ids:
        return result

    for aid in affected_ids:
        try:
            mem = await manager.get_memory(aid)
            if mem is None:
                continue

            if mem.updated_at > latest.created_at:
                result.skipped_conflict += 1
                result.conflict_ids.append(aid)
                continue

            if isinstance(mem, SemanticMemory):
                if mem.metadata.get("consolidation_source") or mem.correction_of:
                    await manager.delete_memory(manager.config.semantic_collection, [aid])
                    result.rolled_back += 1

                elif mem.metadata.get("consolidated") is True:
                    original_importance = 0.7
                    await manager.update_memory(
                        aid,
                        importance=original_importance,
                        metadata={k: v for k, v in mem.metadata.items() if k != "consolidated"},
                    )
                    result.rolled_back += 1

                elif mem.metadata.get("corrected") is True:
                    await manager.update_memory(
                        aid,
                        importance=0.7,
                        metadata={k: v for k, v in mem.metadata.items() if k != "corrected"},
                    )
                    result.rolled_back += 1

                elif "previous_content" in mem.metadata:
                    old_content = str(mem.metadata["previous_content"])
                    clean_metadata = {k: v for k, v in mem.metadata.items() if k != "previous_content"}
                    await manager.update_memory(aid, content=old_content, metadata=clean_metadata)
                    result.rolled_back += 1
                else:
                    result.errors += 1
            else:
                if "previous_content" in mem.metadata:
                    old_content = str(mem.metadata["previous_content"])
                    clean_metadata = {k: v for k, v in mem.metadata.items() if k != "previous_content"}
                    await manager.update_memory(aid, content=old_content, metadata=clean_metadata)
                    result.rolled_back += 1
                else:
                    result.errors += 1

        except Exception as e:
            logger.warning("Consolidation rollback failed for %s: %s", aid, e)
            result.errors += 1

    logger.info(
        "Consolidation rollback complete: rolled_back=%d, skipped_conflict=%d, errors=%d",
        result.rolled_back,
        result.skipped_conflict,
        result.errors,
    )
    return result
