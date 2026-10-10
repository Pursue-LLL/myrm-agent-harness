"""Central audit suite coordinating decay profiling, fact checks, and consolidation (Item 158).

[INPUT]
- Memory profiles, workspace roots, evaluation timestamps, and consolidation decisions.

[OUTPUT]
- MemoryAuditReport, updated memory profiles, and executed consolidation assets.

[POS]
- Audit suite facade in myrm_agent_harness/toolkits/memory/staleness_consolidation/.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .consolidation_engine import MemoryConsolidationEngine
from .decay_profiler import MemoryHalfLifeDecayProfiler
from .models import (
    ConsolidationProposal,
    MemoryAuditReport,
    MemoryItemProfile,
    MemoryStatus,
    RepoAssertionCheckResult,
)
from .repo_checker import RepoFactInvalidationChecker


class AutoMemoryStalenessAndConsolidationAuditSuite:
    """Master coordinator driving staleness decay, fact validation, and clustering consolidation."""

    def __init__(
        self,
        profiler: MemoryHalfLifeDecayProfiler | None = None,
        repo_checker: RepoFactInvalidationChecker | None = None,
        consolidation_engine: MemoryConsolidationEngine | None = None,
    ) -> None:
        self.profiler = profiler or MemoryHalfLifeDecayProfiler()
        self.repo_checker = repo_checker or RepoFactInvalidationChecker()
        self.consolidation_engine = (
            consolidation_engine or MemoryConsolidationEngine()
        )
        self._items: dict[str, MemoryItemProfile] = {}
        self._proposals: dict[str, ConsolidationProposal] = {}

    def register_memory(self, item: MemoryItemProfile) -> MemoryItemProfile:
        """Register or update an autonomous memory profile."""
        self._items[item.memory_id] = item
        return item

    def get_memory(self, memory_id: str) -> MemoryItemProfile | None:
        """Retrieve a memory profile by ID."""
        return self._items.get(memory_id)

    def list_memories(
        self,
        status: MemoryStatus | None = None,
    ) -> list[MemoryItemProfile]:
        """List tracked memories, optionally filtered by lifecycle status."""
        items = list(self._items.values())
        if status is not None:
            return [it for it in items if it.status == status]
        return items

    def touch_recall(
        self,
        memory_id: str,
        now_iso: str | None = None,
    ) -> MemoryItemProfile | None:
        """Record recall touch to reset decay and increment hit frequency."""
        item = self._items.get(memory_id)
        if item is None:
            return None
        return self.profiler.touch_recall(item, now_iso=now_iso)

    def run_decay_profiling(
        self,
        now_iso: str | None = None,
    ) -> list[MemoryItemProfile]:
        """Recalculate staleness decay scores for all tracked memory profiles."""
        now_dt = (
            datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
            if now_iso
            else datetime.now(timezone.utc)
        )
        for it in self._items.values():
            if it.status in ("active", "stale"):
                self.profiler.evaluate_item(it, now=now_dt)
        return list(self._items.values())

    def run_repo_validation(
        self,
        workspace_dir: str | None = None,
    ) -> list[RepoAssertionCheckResult]:
        """Verify code assumptions and path dependencies against current workspace."""
        active_and_stale = [
            it for it in self._items.values() if it.status in ("active", "stale")
        ]
        return self.repo_checker.check_items(
            active_and_stale, workspace_dir=workspace_dir
        )

    def generate_consolidation_proposals(self) -> list[ConsolidationProposal]:
        """Discover rule fragmentation clusters and register consolidation proposals."""
        proposals = self.consolidation_engine.propose_consolidations(
            list(self._items.values())
        )
        self._proposals = {p.proposal_id: p for p in proposals}
        return proposals

    def apply_consolidation(
        self,
        proposal_id: str,
        now_iso: str | None = None,
    ) -> MemoryItemProfile | None:
        """Approve and execute a consolidation proposal."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return None

        new_item = self.consolidation_engine.apply_consolidation(
            proposal, self._items, now_iso=now_iso
        )
        del self._proposals[proposal_id]
        return new_item

    def archive_memories(self, memory_ids: list[str]) -> list[str]:
        """Safely move specified stale or invalidated memories into archived state."""
        archived_ids: list[str] = []
        for mem_id in memory_ids:
            if mem_id in self._items:
                self._items[mem_id].status = "archived"
                archived_ids.append(mem_id)
        return archived_ids

    def generate_audit_report(
        self,
        workspace_dir: str | None = None,
        now_iso: str | None = None,
    ) -> MemoryAuditReport:
        """Conduct an end-to-end memory health audit and synthesize structured report."""
        now_str = now_iso or datetime.now(timezone.utc).isoformat()

        # 1. Update staleness scores
        self.run_decay_profiling(now_iso=now_str)

        # 2. Run codebase fact checks
        check_results = self.run_repo_validation(workspace_dir=workspace_dir)
        invalidated_results = [r for r in check_results if not r.is_valid]

        # 3. Discover consolidation proposals
        proposals = self.generate_consolidation_proposals()

        # 4. Count statuses
        all_items = list(self._items.values())
        active_count = sum(1 for it in all_items if it.status == "active")
        stale_count = sum(1 for it in all_items if it.status == "stale")
        invalidated_count = sum(1 for it in all_items if it.status == "invalidated")
        consolidated_count = sum(1 for it in all_items if it.status == "consolidated")
        archived_count = sum(1 for it in all_items if it.status == "archived")

        avg_staleness = (
            round(sum(it.staleness_score for it in all_items) / len(all_items), 4)
            if all_items
            else 0.0
        )

        return MemoryAuditReport(
            total_items=len(all_items),
            active_items=active_count,
            stale_items=stale_count,
            invalidated_items=invalidated_count,
            consolidated_items=consolidated_count,
            archived_items=archived_count,
            average_staleness=avg_staleness,
            invalidated_results=invalidated_results,
            consolidation_proposals=proposals,
            generated_at=now_str,
        )
