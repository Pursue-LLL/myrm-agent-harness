"""[POS]: src/myrm_agent_harness/toolkits/memory/tombstone/tools.py
[INPUT]: Dict-serialized memory structures from LLM agents.
[OUTPUT]: MemoryTombstoneMetaTools enabling agentic contradiction curation, tombstone masking, and eviction.
"""

from myrm_agent_harness.toolkits.memory.tombstone.models import (
    TombstoneCandidateItem,
)
from myrm_agent_harness.toolkits.memory.tombstone.service import (
    MemoryTombstoneCurationService,
)


class MemoryTombstoneMetaTools:
    """Agent meta-tools for proactive directive curation, tombstone masking, and memory revival."""

    def __init__(self, service: MemoryTombstoneCurationService) -> None:
        self._service = service

    def scan_contradictions_and_curate(
        self,
        memories: list[dict[str, str | float | list[str]]],
        auto_tombstone: bool = True,
    ) -> dict[str, int | float | list[dict[str, str | float]]]:
        """Examine memories for logical contradictions, applying tombstone isolation to superseded directives."""
        candidates = [
            TombstoneCandidateItem(
                memory_id=str(m.get("memory_id", f"mem_{idx}")),
                content=str(m.get("content", "")),
                category=str(m.get("category", "general")),
                created_at=float(m.get("created_at", 0.0)),
                tags=[str(t) for t in m.get("tags", [])] if isinstance(m.get("tags"), list) else [],
            )
            for idx, m in enumerate(memories)
        ]

        report = self._service.curate_and_tombstone(
            memories=candidates, auto_tombstone=auto_tombstone
        )

        serialized_contradictions = [
            {
                "new_memory_id": p.new_memory_id,
                "outdated_memory_id": p.outdated_memory_id,
                "topic_keyword": p.topic_keyword,
                "confidence_score": p.confidence_score,
                "reason": p.reason,
            }
            for p in report.contradictions
        ]

        return {
            "total_scanned": report.total_scanned,
            "total_contradictions_found": report.total_contradictions_found,
            "total_tombstoned": report.total_tombstoned,
            "total_evicted": report.total_evicted,
            "timestamp": report.timestamp,
            "contradictions": serialized_contradictions,
        }

    def filter_active_memories(
        self,
        candidates: list[dict[str, str | float | list[str]]],
    ) -> list[dict[str, str | float | list[str]]]:
        """Hard recall gate discarding any tombstoned or evicted memories before context assembly."""
        items = [
            TombstoneCandidateItem(
                memory_id=str(m.get("memory_id", "")),
                content=str(m.get("content", "")),
                category=str(m.get("category", "general")),
                created_at=float(m.get("created_at", 0.0)),
                tags=[str(t) for t in m.get("tags", [])] if isinstance(m.get("tags"), list) else [],
            )
            for m in candidates
        ]

        active_items = self._service.filter_active_memories(items)
        return [
            {
                "memory_id": it.memory_id,
                "content": it.content,
                "category": it.category,
                "created_at": it.created_at,
                "tags": it.tags,
            }
            for it in active_items
        ]

    def revive_tombstone_memory(self, memory_id: str) -> dict[str, str | bool]:
        """Reinstate a tombstoned memory item back to active recall pool upon user feedback."""
        success = self._service.revive_tombstone(memory_id)
        return {
            "success": success,
            "memory_id": memory_id,
            "message": (
                f"Memory {memory_id} successfully revived to active status."
                if success
                else f"Memory {memory_id} was not in tombstoned state or not found."
            ),
        }

    def evict_tombstoned_memories(
        self, memory_ids: list[str] | None = None
    ) -> dict[str, int | str]:
        """Physically evict tombstoned entries after user review or retention expiration."""
        count = self._service.evict_tombstones(memory_ids)
        return {
            "evicted_count": count,
            "message": f"Successfully evicted {count} tombstoned memory entries.",
        }

    def list_tombstone_records(self) -> list[dict[str, str | float | None]]:
        """List all non-active memory audit records for UI panel display."""
        records = self._service.list_curation_records()
        return [
            {
                "memory_id": r.memory_id,
                "state": r.state.value,
                "tombstoned_at": r.tombstoned_at,
                "superseded_by_id": r.superseded_by_id,
                "reason": r.reason,
                "evicted_at": r.evicted_at,
            }
            for r in records
        ]
