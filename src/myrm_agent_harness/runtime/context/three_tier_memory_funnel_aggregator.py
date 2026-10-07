"""Aggregates Active Workbench (Layer 1), Session Notes & Ledger (Layer 2), and Archive Vault (Layer 3).

[INPUT]
- agent.artifacts.work_notes_syncer_types::WorkNotesSnapshot (POS: Types and models for workspace work notes
  and progress file synchronization.)
- runtime.context.context_cognitive_gauge_types::ContextCognitiveSnapshot (POS: Types and models for Context
  Cognitive Gauge and Agent Context Self-Awareness.)
- runtime.context.negative_decision_ledger::NegativeDecisionLedger (POS: Engine for Negative Decision Ledger
  and Anti-Regression Protection.)
- runtime.context.session_archive_search_engine::SessionArchiveRepositoryProtocol (POS: Engine and Meta-Tool
  Factory for Session Archive Search.)
- runtime.context.session_archive_search_types::ArchiveSearchFilter (POS: Types and models for Full Archive
  Searchable History Meta-Tool.)
- runtime.context.three_tier_memory_funnel_types::ActiveWorkbenchStatus, SearchableArchiveStatus,
  StageNotesAndLedgerStatus, ThreeTierMemoryFunnelSnapshot

[OUTPUT]
- ThreeTierMemoryFunnelAggregator: Aggregates Active Workbench (Layer 1), Session Notes & Ledger (Layer 2),
  and Archive Vault (Layer 3).

[POS]
Aggregates Active Workbench (Layer 1), Session Notes & Ledger (Layer 2), and Archive Vault (Layer 3).
"""

from __future__ import annotations

from datetime import UTC, datetime

from myrm_agent_harness.agent.artifacts.work_notes_syncer_types import WorkNotesSnapshot
from myrm_agent_harness.runtime.context.context_cognitive_gauge_types import ContextCognitiveSnapshot
from myrm_agent_harness.runtime.context.negative_decision_ledger import NegativeDecisionLedger
from myrm_agent_harness.runtime.context.session_archive_search_engine import SessionArchiveRepositoryProtocol
from myrm_agent_harness.runtime.context.session_archive_search_types import ArchiveSearchFilter
from myrm_agent_harness.runtime.context.three_tier_memory_funnel_types import (
    ActiveWorkbenchStatus,
    SearchableArchiveStatus,
    StageNotesAndLedgerStatus,
    ThreeTierMemoryFunnelSnapshot,
)


class ThreeTierMemoryFunnelAggregator:
    """Aggregates Active Workbench (Layer 1), Session Notes & Ledger (Layer 2), and Archive Vault (Layer 3)."""

    def aggregate(
        self,
        session_id: str,
        cognitive_snapshot: ContextCognitiveSnapshot | None = None,
        active_turns_count: int = 0,
        notes_snapshot: WorkNotesSnapshot | None = None,
        negative_ledger: NegativeDecisionLedger | None = None,
        archive_store: SessionArchiveRepositoryProtocol | None = None,
    ) -> ThreeTierMemoryFunnelSnapshot:
        """Compile a unified three-tier cognitive memory funnel snapshot."""
        # 1. Compile Layer 1: Active Workbench Status
        if cognitive_snapshot is not None:
            workbench = ActiveWorkbenchStatus(
                active_turns_count=max(0, active_turns_count),
                current_tokens=cognitive_snapshot.used_tokens,
                token_limit=cognitive_snapshot.total_limit_tokens,
                capacity_percentage=cognitive_snapshot.capacity_pct,
                urgency_level=cognitive_snapshot.urgency_level.value,
                guidance=cognitive_snapshot.suggested_action.value,
            )
        else:
            workbench = ActiveWorkbenchStatus(
                active_turns_count=max(0, active_turns_count),
                current_tokens=0,
                token_limit=128_000,
                capacity_percentage=0.0,
                urgency_level="nominal",
                guidance="EXPLORE_FREELY",
            )

        # 2. Compile Layer 2: Stage Notes & Negative Ledger Status
        disqualified_set: list[str] = []
        if negative_ledger is not None:
            for entry in negative_ledger.get_entries(session_id=session_id):
                for pattern in entry.disqualified_patterns:
                    if pattern not in disqualified_set:
                        disqualified_set.append(pattern)

        if notes_snapshot is not None:
            for pattern in notes_snapshot.disqualified_approaches:
                if pattern not in disqualified_set:
                    disqualified_set.append(pattern)

            stage_notes = StageNotesAndLedgerStatus(
                goal=notes_snapshot.goal,
                current_step_index=notes_snapshot.current_step_index,
                completed_milestones=[
                    step.description for step in notes_snapshot.steps if step.status.value == "COMPLETED"
                ],
                active_hypotheses=[],
                key_findings=list(notes_snapshot.key_findings),
                disqualified_patterns=disqualified_set,
                pending_todos=list(notes_snapshot.todos),
            )
        else:
            stage_notes = StageNotesAndLedgerStatus(
                goal="",
                current_step_index=0,
                completed_milestones=[],
                active_hypotheses=[],
                key_findings=[],
                disqualified_patterns=disqualified_set,
                pending_todos=[],
            )

        # 3. Compile Layer 3: Searchable Archive Status
        if archive_store is not None:
            records = archive_store.query(ArchiveSearchFilter(session_id=session_id))
            archive_status = SearchableArchiveStatus(
                total_archived_turns=len(records),
                searchable=True,
                last_archived_timestamp=records[-1].timestamp_iso if records else None,
            )
        else:
            archive_status = SearchableArchiveStatus(
                total_archived_turns=0,
                searchable=True,
                last_archived_timestamp=None,
            )

        return ThreeTierMemoryFunnelSnapshot(
            session_id=session_id,
            active_workbench=workbench,
            stage_notes_and_ledger=stage_notes,
            searchable_archive=archive_status,
            snapshot_timestamp_iso=datetime.now(UTC).isoformat(),
        )
