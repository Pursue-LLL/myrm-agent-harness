"""MemoryManager mixin for causal experience gene evolution and planning-stage guidance.

[INPUT]
- toolkits.memory.evolution.causal_extractor::CausalGeneExtractor, MultiTurnTaskTrace (POS: trajectory extractor)
- toolkits.memory.evolution.gene_ledger::ExperienceGeneLedger (POS: experience gene ledger)
- toolkits.memory.evolution.gene_models::ExperienceGene, GeneMutationAdvice (POS: gene data models)

[OUTPUT]
- MemoryManagerExperienceEvolutionMixin: runtime orchestration methods for causal experience genes

[POS]
Partial mixin for MemoryManager providing experience gene synthesis, reinforcement, and planning advice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.evolution.causal_extractor import (
        MultiTurnTaskTrace,
    )
    from myrm_agent_harness.toolkits.memory.evolution.gene_ledger import (
        ExperienceGeneLedger,
    )
    from myrm_agent_harness.toolkits.memory.evolution.gene_models import (
        ExperienceGene,
        GeneMutationAdvice,
    )


class MemoryManagerExperienceEvolutionMixin:
    """Provides methods for synthesizing causal experience genes and querying planning mutation advice."""

    def get_planning_gene_mutation_advice(
        self,
        active_signals: list[str],
        *,
        min_confidence: float = 0.6,
        limit: int = 5,
        ledger: ExperienceGeneLedger | None = None,
    ) -> list[GeneMutationAdvice]:
        """Query evolutionary advice matching active symptom signals to avoid known dead-ends."""
        from myrm_agent_harness.toolkits.memory.evolution.gene_ledger import (
            ExperienceGeneLedger,
        )

        active_ledger = ledger or ExperienceGeneLedger()
        return active_ledger.generate_planning_mutation_advice(
            active_signals=active_signals,
            min_confidence=min_confidence,
            limit=limit,
        )

    def extract_and_reinforce_causal_genes(
        self,
        trace: MultiTurnTaskTrace,
        *,
        ledger: ExperienceGeneLedger | None = None,
    ) -> list[ExperienceGene]:
        """Extract causal experience genes from a multi-turn task trace and reinforce them in the ledger."""
        from myrm_agent_harness.toolkits.memory.evolution.causal_extractor import (
            CausalGeneExtractor,
        )
        from myrm_agent_harness.toolkits.memory.evolution.gene_ledger import (
            ExperienceGeneLedger,
        )

        active_ledger = ledger or ExperienceGeneLedger()
        gene = CausalGeneExtractor.extract_gene(trace)
        if gene is not None:
            saved = active_ledger.register_or_reinforce(gene)
            return [saved]
        return []


    def penalize_experience_gene(
        self,
        gene_id: str,
        *,
        penalty: float = 0.2,
        ledger: ExperienceGeneLedger | None = None,
    ) -> ExperienceGene | None:
        """Apply confidence penalty when a recommended gene fails in production."""
        from myrm_agent_harness.toolkits.memory.evolution.gene_ledger import (
            ExperienceGeneLedger,
        )

        active_ledger = ledger or ExperienceGeneLedger()
        return active_ledger.penalize_gene(gene_id=gene_id, penalty=penalty)

    def list_experience_genes(
        self,
        *,
        ledger: ExperienceGeneLedger | None = None,
    ) -> list[ExperienceGene]:
        """List all evolutionary experience genes tracked in the ledger."""
        from myrm_agent_harness.toolkits.memory.evolution.gene_ledger import (
            ExperienceGeneLedger,
        )

        active_ledger = ledger or ExperienceGeneLedger()
        return active_ledger.list_genes()

    def get_experience_gene_stats(
        self,
        *,
        ledger: ExperienceGeneLedger | None = None,
    ) -> dict[str, int | float]:
        """Get summary statistics of the experience gene ledger."""
        from myrm_agent_harness.toolkits.memory.evolution.gene_ledger import (
            ExperienceGeneLedger,
        )

        active_ledger = ledger or ExperienceGeneLedger()
        return active_ledger.get_stats()
