"""Agent-facing LangChain tool for cross-agent memory divergence detection and ground truth arbitration.

[INPUT]
- toolkits.memory.cross_agent.arbitrator::MultiAgentConflictArbitrator (POS: arbitrator)
- toolkits.memory.cross_agent.types::AgentMemoryDivergence, ArbitrationOutcome, MemoryAssertion (POS: types)

[OUTPUT]
- ArbitrateCrossAgentMemoryConflictInput: Pydantic input schema for runtime conflict settlement
- create_cross_agent_arbitration_tool: Factory creating LangChain BaseTool for Agent runtime

[POS]
Agent-facing LangChain tool allowing collaborating agents to arbitrate memory conflicts using ground truth, coordinator authority, and confidence weighting.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.cross_agent.arbitrator import (
    MultiAgentConflictArbitrator,
)
from myrm_agent_harness.toolkits.memory.cross_agent.types import (
    AgentMemoryDivergence,
    ArbitrationOutcome,
    MemoryAssertion,
)


class ArbitrateCrossAgentMemoryConflictInput(BaseModel):
    """Input parameters for arbitrating a factual divergence between two collaborating agents."""

    subject: str = Field(..., description="Subject or entity name under dispute, e.g. 'database_backend'")
    predicate: str = Field(..., description="Relationship or attribute, e.g. 'uses' or 'stores'")
    my_value: str = Field(..., description="Value claimed by the calling agent, e.g. 'sqlite'")
    peer_value: str = Field(..., description="Conflicting value claimed by peer agent, e.g. 'postgres'")
    my_agent_id: str = Field(..., description="Calling agent identifier")
    peer_agent_id: str = Field(..., description="Peer agent identifier")
    my_confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Calling agent confidence score")
    peer_confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Peer agent confidence score")
    my_source_reference: str | None = Field(
        default=None,
        description="Relative file path or code symbol justifying calling agent's claim",
    )
    peer_source_reference: str | None = Field(
        default=None,
        description="Relative file path or code symbol justifying peer agent's claim",
    )
    workspace_root: str | None = Field(
        default=None,
        description="Optional absolute path to workspace root to probe ground truth",
    )


def create_cross_agent_arbitration_tool(
    arbitrator: MultiAgentConflictArbitrator | None = None,
    workspace_root: Path | str | None = None,
) -> BaseTool:
    """Create a LangChain standard tool to arbitrate cross-agent memory discrepancies."""
    active_arbitrator = arbitrator or MultiAgentConflictArbitrator(workspace_root=workspace_root)

    @tool("arbitrate_cross_agent_memory_conflict", args_schema=ArbitrateCrossAgentMemoryConflictInput)
    def arbitrate_cross_agent_memory_conflict(
        subject: str,
        predicate: str,
        my_value: str,
        peer_value: str,
        my_agent_id: str,
        peer_agent_id: str,
        my_confidence: float = 1.0,
        peer_confidence: float = 0.8,
        my_source_reference: str | None = None,
        peer_source_reference: str | None = None,
        workspace_root: str | None = None,
    ) -> str:
        """Arbitrate factual conflicts between two agents by probing code ground truth and coordinator rules."""
        # Use workspace root from input if provided
        runtime_arbitrator = active_arbitrator
        if workspace_root:
            runtime_arbitrator = MultiAgentConflictArbitrator(
                workspace_root=workspace_root,
                coordinator_agent_ids=active_arbitrator.coordinator_agent_ids,
                confidence_delta_threshold=active_arbitrator.confidence_delta_threshold,
            )

        assertion_a = MemoryAssertion(
            assertion_id=f"ast-{my_agent_id[:6]}-{subject[:6]}",
            subject=subject,
            predicate=predicate,
            object_value=my_value,
            confidence=my_confidence,
            source_agent_id=my_agent_id,
            source_reference=my_source_reference,
        )
        assertion_b = MemoryAssertion(
            assertion_id=f"ast-{peer_agent_id[:6]}-{subject[:6]}",
            subject=subject,
            predicate=predicate,
            object_value=peer_value,
            confidence=peer_confidence,
            source_agent_id=peer_agent_id,
            source_reference=peer_source_reference,
        )

        divergence = AgentMemoryDivergence(
            divergence_id=f"div-{subject[:8]}-{my_agent_id[:4]}-{peer_agent_id[:4]}",
            subject=subject,
            predicate=predicate,
            agent_a_id=my_agent_id,
            assertion_a=assertion_a,
            agent_b_id=peer_agent_id,
            assertion_b=assertion_b,
        )

        outcome: ArbitrationOutcome = runtime_arbitrator.arbitrate_divergence(divergence)

        return json.dumps(
            {
                "divergence_id": outcome.divergence_id,
                "resolved": outcome.resolved,
                "policy_applied": outcome.policy_applied.value,
                "winning_assertion": {
                    "assertion_id": outcome.winning_assertion.assertion_id,
                    "subject": outcome.winning_assertion.subject,
                    "predicate": outcome.winning_assertion.predicate,
                    "object_value": outcome.winning_assertion.object_value,
                    "confidence": outcome.winning_assertion.confidence,
                    "source_agent_id": outcome.winning_assertion.source_agent_id,
                    "source_reference": outcome.winning_assertion.source_reference,
                },
                "audit_rationale": outcome.audit_rationale,
                "requires_human_confirmation": outcome.requires_human_confirmation,
            },
            ensure_ascii=False,
        )

    return arbitrate_cross_agent_memory_conflict
