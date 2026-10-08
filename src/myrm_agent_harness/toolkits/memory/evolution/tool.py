"""Agent-facing LangChain tool for querying causal experience gene advice and dead-end avoidance.

[INPUT]
- toolkits.memory.evolution.gene_ledger::ExperienceGeneLedger (POS: ledger for experience genes)
- toolkits.memory.evolution.gene_models::GeneMatchQuery, GeneMutationAdvice (POS: gene query models)

[OUTPUT]
- InspectExperienceGeneAdviceInput: Pydantic input schema for gene advice tool
- create_experience_gene_advice_tool: Factory creating LangChain BaseTool for Agent runtime

[POS]
Agent-facing LangChain tool allowing agents to proactively query causal experience genes during planning.
"""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.evolution.gene_ledger import (
    ExperienceGeneLedger,
)


class InspectExperienceGeneAdviceInput(BaseModel):
    """Input schema for querying causal experience gene advice."""

    active_signals: list[str] = Field(
        ...,
        description="List of symptom signals, error signatures, or environmental indicators observed in the current task",
    )
    min_confidence: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold required for matched experience genes",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of gene mutation advice records to return",
    )


def create_experience_gene_advice_tool(
    ledger: ExperienceGeneLedger | None = None,
) -> BaseTool:
    """Create a LangChain standard tool allowing agents to retrieve causal advice and dead-ends for planning."""
    active_ledger = ledger or ExperienceGeneLedger()

    @tool("inspect_experience_gene_advice", args_schema=InspectExperienceGeneAdviceInput)
    def inspect_experience_gene_advice(
        active_signals: list[str],
        min_confidence: float = 0.6,
        limit: int = 5,
    ) -> str:
        """Inspect causal experience genes to discover refuted dead-end hypotheses and proven resolutions matching symptoms."""
        advices = active_ledger.generate_planning_mutation_advice(
            active_signals=active_signals,
            min_confidence=min_confidence,
            limit=limit,
        )

        formatted = [
            {
                "gene_id": adv.gene_id,
                "matched_signals": adv.matched_signals,
                "refuted_paths": adv.refuted_paths,
                "recommended_resolution": adv.recommended_resolution,
                "confidence": adv.confidence,
                "polarity": adv.polarity.value,
            }
            for adv in advices
        ]

        payload = {
            "query_signals": active_signals,
            "total_matches": len(formatted),
            "advice": formatted,
        }
        return json.dumps(payload, ensure_ascii=False)

    return inspect_experience_gene_advice
