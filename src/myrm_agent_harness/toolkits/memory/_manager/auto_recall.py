"""MemoryManager mixin for targeted experience auto-recall gate and sliding dedup.

[INPUT]
- toolkits.memory.auto_recall.recall_gate::ExperienceRecallGate (POS: auto-recall gate orchestrator)
- toolkits.memory.auto_recall.types::AutoRecallDecision, RecallCandidate, RecallGateConfig (POS: contracts)

[OUTPUT]
- MemoryManagerAutoRecallMixin: runtime orchestration methods for targeted auto-recall gate

[POS]
Partial mixin for MemoryManager providing sensitive trigger evaluation, sliding window dedup, and fail-open rerank.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.auto_recall.recall_gate import (
        ExperienceRecallGate,
    )
    from myrm_agent_harness.toolkits.memory.auto_recall.types import (
        AutoRecallDecision,
        RecallCandidate,
    )


class MemoryManagerAutoRecallMixin:
    """Provides methods for evaluating targeted experience auto-recall and sliding-window deduplication."""

    def evaluate_auto_recall_decision(
        self,
        session_id: str,
        current_turn: int,
        raw_candidates: list[RecallCandidate],
        *,
        event_name: str | None = None,
        tool_name: str | None = None,
        query_text: str | None = None,
        force_recall: bool = False,
        gate: ExperienceRecallGate | None = None,
    ) -> AutoRecallDecision:
        """Evaluate context for sensitive triggers (5 scenarios), apply 5-turn sliding dedup, and fail-open rerank."""
        from myrm_agent_harness.toolkits.memory.auto_recall.recall_gate import (
            ExperienceRecallGate,
        )

        active_gate = gate or ExperienceRecallGate()
        return active_gate.evaluate_and_recall(
            session_id=session_id,
            current_turn=current_turn,
            raw_candidates=raw_candidates,
            event_name=event_name,
            tool_name=tool_name,
            query_text=query_text,
            force_recall=force_recall,
        )

    def record_auto_recall_injection(
        self,
        session_id: str,
        injected_ids: list[str],
        turn_index: int,
        *,
        gate: ExperienceRecallGate | None = None,
    ) -> None:
        """Record newly injected memory IDs into the sliding window tracker."""
        from myrm_agent_harness.toolkits.memory.auto_recall.recall_gate import (
            ExperienceRecallGate,
        )

        active_gate = gate or ExperienceRecallGate()
        active_gate.get_dedup_gate().record_injected(
            session_id=session_id,
            injected_ids=injected_ids,
            turn_index=turn_index,
        )

    def get_auto_recall_seen_memories(
        self,
        session_id: str,
        *,
        gate: ExperienceRecallGate | None = None,
    ) -> set[str]:
        """Return the set of memory IDs currently active in the sliding window for a given session."""
        from myrm_agent_harness.toolkits.memory.auto_recall.recall_gate import (
            ExperienceRecallGate,
        )

        active_gate = gate or ExperienceRecallGate()
        return active_gate.get_dedup_gate().get_recent_injected(session_id)

