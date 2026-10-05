"""Memory capacity saturation governor and low-rank capacity manager.

Monitors memory pool capacity, calculates redundancy entropy, and executes
two-phase governance (consolidation + LRU-confidence eviction) (inspired by Metis / arXiv:2607.26760).

[INPUT]
- myrm_agent_harness.toolkits.memory.governor.models::* (POS: schemas, metrics, reports)
- asyncio, datetime (POS: concurrency locking and temporal calculation)

[OUTPUT]
- MemoryCapacityManager: Service managing memory pool capacity and eviction.

[POS]
Governance engine maintaining bounded memory capacity and maximum epistemic density.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.governor.models import (
    CapacityGovernorMetrics,
    EvictionReport,
    GovernedMemoryEntry,
    MemorySourceAnchor,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryCapacityManager:
    """Monitors capacity saturation and executes adaptive consolidation and eviction."""

    def __init__(
        self,
        max_capacity: int = 100,
        target_headroom_ratio: float = 0.8,
        redundancy_threshold: float = 0.25,
    ) -> None:
        self.max_capacity = max(1, max_capacity)
        self.target_headroom_ratio = min(0.95, max(0.5, target_headroom_ratio))
        self.redundancy_threshold = redundancy_threshold
        self._lock = asyncio.Lock()
        # entry_id -> GovernedMemoryEntry
        self._entries: dict[str, GovernedMemoryEntry] = {}

    async def register_entry(
        self,
        entity: str,
        statement: str,
        confidence: float = 0.9,
        anchor: MemorySourceAnchor | None = None,
        is_locked: bool = False,
    ) -> GovernedMemoryEntry:
        """Register a new memory entry under capacity governance."""
        async with self._lock:
            anchor = anchor or MemorySourceAnchor()
            now = _utc_now()

            # Check for existing matching entry for same entity in same workspace
            for existing in self._entries.values():
                if (
                    existing.entity.strip().lower() == entity.strip().lower()
                    and existing.anchor.workspace_root == anchor.workspace_root
                    and existing.statement.strip().lower() == statement.strip().lower()
                ):
                    existing.access_count += 1
                    existing.confidence = min(1.0, max(existing.confidence, confidence) + 0.05)
                    existing.last_accessed_at = now
                    if is_locked:
                        existing.is_locked = True
                    return existing

            new_entry = GovernedMemoryEntry(
                entity=entity,
                statement=statement,
                confidence=confidence,
                anchor=anchor,
                is_locked=is_locked,
                created_at=now,
                last_accessed_at=now,
            )
            self._entries[new_entry.entry_id] = new_entry

            # Trigger auto-governance if capacity exceeded
            if len(self._entries) > self.max_capacity:
                await self._enforce_capacity_unlocked()

            return new_entry

    async def get_metrics(self) -> CapacityGovernorMetrics:
        """Compute current memory pool capacity telemetry and redundancy density."""
        async with self._lock:
            return self._compute_metrics_unlocked()

    async def enforce_capacity(self) -> EvictionReport:
        """Explicitly run capacity enforcement: consolidation followed by low-confidence eviction."""
        async with self._lock:
            return await self._enforce_capacity_unlocked()

    async def list_active_entries(self) -> list[GovernedMemoryEntry]:
        """Return all active governed memory entries."""
        async with self._lock:
            return list(self._entries.values())

    def _compute_metrics_unlocked(self) -> CapacityGovernorMetrics:
        """Calculate telemetry metrics without acquiring lock (internal)."""
        total = len(self._entries)
        saturation = round(total / self.max_capacity, 4)

        # Calculate redundancy density (proportion of duplicate entity names)
        entities = [e.entity.strip().lower() for e in self._entries.values()]
        unique_entities = set(entities)
        duplicate_count = total - len(unique_entities)
        redundancy = round(duplicate_count / total, 4) if total > 0 else 0.0

        return CapacityGovernorMetrics(
            total_active_entries=total,
            max_capacity=self.max_capacity,
            saturation_ratio=saturation,
            redundancy_density=redundancy,
            is_over_capacity=total > self.max_capacity,
        )

    async def _enforce_capacity_unlocked(self) -> EvictionReport:
        """Execute two-phase consolidation and eviction while lock is held."""
        initial_total = len(self._entries)
        consolidated_count = 0

        # Phase 1: Consolidation of duplicate/redundant entities
        entity_groups: dict[str, list[GovernedMemoryEntry]] = {}
        for entry in list(self._entries.values()):
            key = f"{entry.anchor.workspace_root}::{entry.entity.strip().lower()}"
            entity_groups.setdefault(key, []).append(entry)

        for _, group in entity_groups.items():
            if len(group) > 1:
                # Keep the entry with highest confidence / newest access, consolidate access counts
                group.sort(key=lambda e: (e.confidence, e.last_accessed_at), reverse=True)
                primary = group[0]
                for redundant in group[1:]:
                    if not redundant.is_locked:
                        primary.access_count += redundant.access_count
                        primary.confidence = min(1.0, primary.confidence + 0.02)
                        del self._entries[redundant.entry_id]
                        consolidated_count += 1

        # Phase 2: Eviction of unlocked low-confidence / stale entries if still above target
        target_slots = int(self.max_capacity * self.target_headroom_ratio)
        evicted_ids: list[str] = []

        if len(self._entries) > target_slots:
            # Sort unlockable candidates: lowest confidence and oldest access first
            candidates = [e for e in self._entries.values() if not e.is_locked]
            now = _utc_now()

            def eviction_score(e: GovernedMemoryEntry) -> float:
                age_hours = (now - e.last_accessed_at).total_seconds() / 3600.0
                # Lower confidence and higher staleness yields higher eviction score
                return (1.0 - e.confidence) * 0.7 + min(1.0, age_hours / 72.0) * 0.3

            candidates.sort(key=eviction_score, reverse=True)
            excess = len(self._entries) - target_slots
            to_evict = candidates[:excess]

            for entry in to_evict:
                del self._entries[entry.entry_id]
                evicted_ids.append(entry.entry_id)

        freed = initial_total - len(self._entries)
        new_saturation = round(len(self._entries) / self.max_capacity, 4)
        logger.info(
            "Capacity enforcement complete: consolidated %d, evicted %d, freed %d slots",
            consolidated_count,
            len(evicted_ids),
            freed,
        )

        return EvictionReport(
            evicted_entry_ids=evicted_ids,
            consolidated_count=consolidated_count,
            freed_slots=freed,
            new_saturation_ratio=new_saturation,
        )
