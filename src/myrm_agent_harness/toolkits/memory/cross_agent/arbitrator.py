"""Multi-agent memory divergence detection and ground truth arbitration probe.

[INPUT]
- toolkits.memory.cross_agent.types::AgentMemoryDivergence, ArbitrationOutcome, ConflictResolutionPolicy, MemoryAssertion (POS: types)

[OUTPUT]
- MultiAgentConflictArbitrator: Detects conflicting memory assertions between peer agents and executes deterministic 3-tier arbitration.

[POS]
Core arbitration probe that prevents logic divergence and task fractures when two agents remember the same task differently.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from myrm_agent_harness.toolkits.memory.cross_agent.types import (
    AgentMemoryDivergence,
    ArbitrationOutcome,
    ConflictResolutionPolicy,
    MemoryAssertion,
)

logger = logging.getLogger(__name__)


class MultiAgentConflictArbitrator:
    """Detects memory discrepancies between agents and arbitrates ground truth via physical environment and coordinator authority."""

    def __init__(
        self,
        workspace_root: Path | str | None = None,
        coordinator_agent_ids: set[str] | None = None,
        confidence_delta_threshold: float = 0.2,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else None
        self.coordinator_agent_ids = coordinator_agent_ids or {"coordinator", "orchestrator", "architect"}
        self.confidence_delta_threshold = confidence_delta_threshold

    def detect_divergences(
        self,
        assertions_agent_a: list[MemoryAssertion],
        assertions_agent_b: list[MemoryAssertion],
    ) -> list[AgentMemoryDivergence]:
        """Scan assertion collections from two agents to detect conflicting factual claims."""
        map_a: dict[tuple[str, str], MemoryAssertion] = {
            (a.subject.lower().strip(), a.predicate.lower().strip()): a for a in assertions_agent_a
        }
        map_b: dict[tuple[str, str], MemoryAssertion] = {
            (b.subject.lower().strip(), b.predicate.lower().strip()): b for b in assertions_agent_b
        }

        divergences: list[AgentMemoryDivergence] = []
        for key, assertion_a in map_a.items():
            if key in map_b:
                assertion_b = map_b[key]
                val_a = assertion_a.object_value.strip().lower()
                val_b = assertion_b.object_value.strip().lower()
                if val_a != val_b:
                    divergences.append(
                        AgentMemoryDivergence(
                            divergence_id=f"div-{uuid.uuid4().hex[:8]}",
                            subject=assertion_a.subject,
                            predicate=assertion_a.predicate,
                            agent_a_id=assertion_a.source_agent_id,
                            assertion_a=assertion_a,
                            agent_b_id=assertion_b.source_agent_id,
                            assertion_b=assertion_b,
                        )
                    )

        return divergences

    def arbitrate_divergence(
        self,
        divergence: AgentMemoryDivergence,
    ) -> ArbitrationOutcome:
        """Arbitrate a detected divergence using the 3-tier priority ladder."""
        # -------------------------------------------------------------
        # Tier 1: Ground Truth Probe (Inspect physical workspace files)
        # -------------------------------------------------------------
        gt_outcome = self._probe_ground_truth(divergence)
        if gt_outcome is not None:
            return gt_outcome

        # -------------------------------------------------------------
        # Tier 2: Coordinator Authority
        # -------------------------------------------------------------
        coord_outcome = self._check_coordinator_authority(divergence)
        if coord_outcome is not None:
            return coord_outcome

        # -------------------------------------------------------------
        # Tier 2.5: Confidence Weighted
        # -------------------------------------------------------------
        conf_a = divergence.assertion_a.confidence
        conf_b = divergence.assertion_b.confidence
        if abs(conf_a - conf_b) >= self.confidence_delta_threshold:
            winner = divergence.assertion_a if conf_a > conf_b else divergence.assertion_b
            loser = divergence.assertion_b if conf_a > conf_b else divergence.assertion_a
            return ArbitrationOutcome(
                divergence_id=divergence.divergence_id,
                resolved=True,
                policy_applied=ConflictResolutionPolicy.CONFIDENCE_WEIGHTED,
                winning_assertion=winner,
                audit_rationale=(
                    f"Resolved by confidence weighting: {winner.source_agent_id} ({winner.confidence:.2f}) "
                    f"substantially exceeds {loser.source_agent_id} ({loser.confidence:.2f})."
                ),
                requires_human_confirmation=False,
            )

        # -------------------------------------------------------------
        # Tier 3: Human-in-the-Loop Escalation (Ambiguous deadlock)
        # -------------------------------------------------------------
        # Default to assertion_a while flagging for human 1-click confirmation
        return ArbitrationOutcome(
            divergence_id=divergence.divergence_id,
            resolved=False,
            policy_applied=ConflictResolutionPolicy.HUMAN_IN_THE_LOOP,
            winning_assertion=divergence.assertion_a,
            audit_rationale=(
                f"Symmetric deadlock between {divergence.agent_a_id} ('{divergence.assertion_a.object_value}') "
                f"and {divergence.agent_b_id} ('{divergence.assertion_b.object_value}') with similar confidence. "
                "Suspended pending human confirmation in UI."
            ),
            requires_human_confirmation=True,
        )

    def _probe_ground_truth(
        self, divergence: AgentMemoryDivergence
    ) -> ArbitrationOutcome | None:
        """Probe workspace filesystem to verify if either assertion is physically attested."""
        if not self.workspace_root or not self.workspace_root.exists():
            return None

        # Check references in assertion A and B
        for claim, peer in [
            (divergence.assertion_a, divergence.assertion_b),
            (divergence.assertion_b, divergence.assertion_a),
        ]:
            if claim.source_reference:
                target_file = (self.workspace_root / claim.source_reference).resolve()
                if target_file.exists() and target_file.is_file():
                    try:
                        content = target_file.read_text(encoding="utf-8")
                        if claim.object_value.lower() in content.lower():
                            return ArbitrationOutcome(
                                divergence_id=divergence.divergence_id,
                                resolved=True,
                                policy_applied=ConflictResolutionPolicy.GROUND_TRUTH_FIRST,
                                winning_assertion=claim,
                                audit_rationale=(
                                    f"Physical ground truth verified in file '{claim.source_reference}': "
                                    f"contains '{claim.object_value}'. Peer '{peer.object_value}' vetoed."
                                ),
                                requires_human_confirmation=False,
                            )
                    except OSError as exc:
                        logger.debug("Failed reading ground truth file: %s", exc)

        return None

    def _check_coordinator_authority(
        self, divergence: AgentMemoryDivergence
    ) -> ArbitrationOutcome | None:
        """Arbitrate based on whether one agent holds coordinator or orchestrator status."""
        a_is_coord = divergence.agent_a_id.lower() in self.coordinator_agent_ids
        b_is_coord = divergence.agent_b_id.lower() in self.coordinator_agent_ids

        if a_is_coord and not b_is_coord:
            return ArbitrationOutcome(
                divergence_id=divergence.divergence_id,
                resolved=True,
                policy_applied=ConflictResolutionPolicy.COORDINATOR_AUTHORITY,
                winning_assertion=divergence.assertion_a,
                audit_rationale=(
                    f"Agent '{divergence.agent_a_id}' holds coordinator authority over '{divergence.agent_b_id}'."
                ),
                requires_human_confirmation=False,
            )
        if b_is_coord and not a_is_coord:
            return ArbitrationOutcome(
                divergence_id=divergence.divergence_id,
                resolved=True,
                policy_applied=ConflictResolutionPolicy.COORDINATOR_AUTHORITY,
                winning_assertion=divergence.assertion_b,
                audit_rationale=(
                    f"Agent '{divergence.agent_b_id}' holds coordinator authority over '{divergence.agent_a_id}'."
                ),
                requires_human_confirmation=False,
            )
        return None
