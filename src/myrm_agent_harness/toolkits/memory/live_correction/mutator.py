"""Atomic memory mutator executing live corrections and version lineage management.

[INPUT]
- slot: CorrectionSlot
- target_candidate: Optional[TargetNodeCandidate]

[OUTPUT]
- LiveCorrectionMutationResult: Atomic mutation details with lineage audit

[POS]
myrm_agent_harness.toolkits.memory.live_correction.mutator
"""

from __future__ import annotations

import uuid
from typing import Protocol

from myrm_agent_harness.toolkits.memory.live_correction.models import (
    CorrectionIntentKind,
    CorrectionSlot,
    LiveCorrectionMutationResult,
    MutationAction,
    TargetNodeCandidate,
)


class MutationSinkProtocol(Protocol):
    """Protocol for persisting mutation results into underlying storage."""

    def record_mutation(self, result: LiveCorrectionMutationResult) -> None:
        """Persist or broadcast memory mutation."""
        ...


class AtomicMemoryMutator:
    """Executes atomic state changes on target memory items with lineage tracking."""

    def __init__(self, sink: MutationSinkProtocol | None = None) -> None:
        self.sink = sink
        self._history: list[LiveCorrectionMutationResult] = []

    def mutate(
        self,
        slot: CorrectionSlot,
        target: TargetNodeCandidate | None = None,
    ) -> LiveCorrectionMutationResult:
        """Perform atomic memory state transition based on correction slot and target."""
        new_id = f"mem_corr_{uuid.uuid4().hex[:12]}"

        # Scenario 1: Retraction request
        if slot.intent == CorrectionIntentKind.RETRACT_MISTAKE:
            target_id = target.memory_id if target else None
            result = LiveCorrectionMutationResult(
                action=MutationAction.RETRACT,
                target_memory_id=target_id,
                new_memory_id=None,
                status="retracted",
                superseded_content=target.content if target else slot.negated_value,
                new_content=None,
                audit_trail={
                    "reason": "user_retraction",
                    "utterance": slot.raw_utterance,
                },
            )

        # Scenario 2: Target node exists -> Supersede or Amend
        elif target is not None:
            action = (
                MutationAction.AMEND
                if slot.intent == CorrectionIntentKind.BEHAVIOR_RULE
                else MutationAction.SUPERSEDE
            )
            result = LiveCorrectionMutationResult(
                action=action,
                target_memory_id=target.memory_id,
                new_memory_id=new_id,
                status="applied",
                superseded_content=target.content,
                new_content=slot.corrected_value,
                audit_trail={
                    "superseded_by": new_id,
                    "previous_id": target.memory_id,
                    "utterance": slot.raw_utterance,
                    "match_score": f"{target.match_score:.2f}",
                },
            )

        # Scenario 3: Novel correction without pre-existing target node
        else:
            result = LiveCorrectionMutationResult(
                action=MutationAction.CREATE_NOVEL,
                target_memory_id=None,
                new_memory_id=new_id,
                status="created",
                superseded_content=None,
                new_content=slot.corrected_value,
                audit_trail={
                    "reason": "novel_live_correction",
                    "utterance": slot.raw_utterance,
                },
            )

        self._history.append(result)
        if self.sink is not None:
            self.sink.record_mutation(result)

        return result

    @property
    def history(self) -> list[LiveCorrectionMutationResult]:
        """Return history of all mutations executed by this mutator."""
        return list(self._history)
