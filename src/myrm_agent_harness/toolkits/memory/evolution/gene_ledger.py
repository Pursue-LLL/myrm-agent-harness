"""Confidence Evolution Ledger and retrieval matcher for Experience Genes.

[INPUT]
- toolkits.memory.evolution.gene_models::ExperienceGene, GeneMatchQuery, GeneMutationAdvice (POS: Data
  models for Causal Experience Genes and Evolution Ledger.)

[OUTPUT]
- ExperienceGeneLedger: In-memory and persistent evolution ledger governing experience genes and confidence
  scoring.

[POS]
Confidence Evolution Ledger and retrieval matcher for Experience Genes.
"""

from __future__ import annotations

import time

from .gene_models import (
    ExperienceGene,
    GeneMatchQuery,
    GeneMutationAdvice,
)


class ExperienceGeneLedger:
    """In-memory and persistent evolution ledger governing experience genes and confidence scoring."""

    def __init__(self, max_genes: int = 1000) -> None:
        self._max_genes = max_genes
        self._genes: dict[str, ExperienceGene] = {}

    def register_or_reinforce(self, gene: ExperienceGene) -> ExperienceGene:
        """Register a new experience gene or reinforce existing gene confidence upon re-validation."""
        # 1. Check exact ID match
        existing = self._genes.get(gene.gene_id)
        if existing:
            return self._reinforce(existing, gene)

        # 2. Check signal Jaccard overlap match (>= 0.75)
        for _cand_id, cand_gene in self._genes.items():
            overlap = self._compute_signal_overlap(cand_gene.trigger_signals, gene.trigger_signals)
            if overlap >= 0.75:
                return self._reinforce(cand_gene, gene)

        # 3. New gene registration (LRU purge if full)
        if len(self._genes) >= self._max_genes:
            self._evict_weakest_gene()

        self._genes[gene.gene_id] = gene
        return gene

    def penalize_gene(self, gene_id: str, penalty: float = 0.2) -> ExperienceGene | None:
        """Apply negative feedback deduction when a gene guidance path fails during runtime."""
        gene = self._genes.get(gene_id)
        if not gene:
            return None

        new_conf = max(0.1, round(gene.confidence_score - penalty, 4))
        updated = ExperienceGene(
            gene_id=gene.gene_id,
            trigger_signals=gene.trigger_signals,
            hypotheses_refuted=gene.hypotheses_refuted,
            proven_resolution=gene.proven_resolution,
            polarity=gene.polarity,
            confidence_score=new_conf,
            proof_count=gene.proof_count,
            provenance_session_id=gene.provenance_session_id,
            tags=gene.tags,
            created_at=gene.created_at,
            updated_at=time.time(),
        )
        self._genes[gene_id] = updated
        return updated

    def match_genes(self, query: GeneMatchQuery) -> list[ExperienceGene]:
        """Match and rank stored genes against active symptoms and signals."""
        if not query.active_signals or not self._genes:
            return []

        active_set = {s.lower() for s in query.active_signals}
        scored: list[tuple[float, ExperienceGene]] = []

        for gene in self._genes.values():
            if gene.confidence_score < query.min_confidence:
                continue

            gene_sigs = {s.lower() for s in gene.trigger_signals}
            inter = active_set.intersection(gene_sigs)
            if not inter:
                continue

            # Overlap coefficient
            relevance = len(inter) / max(1, len(gene_sigs))
            # Blended ranking score: relevance * 0.6 + confidence * 0.3 + log(proof_count) * 0.1
            composite_score = relevance * 0.7 + gene.confidence_score * 0.3
            scored.append((composite_score, gene))

        # Sort by composite score descending, then proof count descending
        scored.sort(key=lambda x: (x[0], x[1].proof_count), reverse=True)
        return [item[1] for item in scored[: query.limit]]

    def generate_planning_mutation_advice(
        self,
        active_signals: list[str],
        min_confidence: float = 0.6,
        limit: int = 5,
    ) -> list[GeneMutationAdvice]:
        """Synthesize planning-stage guidance to preempt dead-ends and steer towards proven resolutions."""
        query = GeneMatchQuery(
            active_signals=active_signals,
            min_confidence=min_confidence,
            limit=limit,
        )
        matched = self.match_genes(query)
        advices: list[GeneMutationAdvice] = []

        active_lower = {s.lower() for s in active_signals}
        for g in matched:
            matched_sigs = [s for s in g.trigger_signals if s.lower() in active_lower]
            advices.append(
                GeneMutationAdvice(
                    gene_id=g.gene_id,
                    matched_signals=matched_sigs or g.trigger_signals,
                    refuted_paths=g.hypotheses_refuted,
                    recommended_resolution=g.proven_resolution,
                    confidence=g.confidence_score,
                    polarity=g.polarity,
                )
            )
        return advices

    def get_gene(self, gene_id: str) -> ExperienceGene | None:
        """Retrieve a single gene by its unique identifier."""
        return self._genes.get(gene_id)

    def list_genes(self) -> list[ExperienceGene]:
        """Return all tracked genes sorted by proof count descending."""
        return sorted(self._genes.values(), key=lambda g: g.proof_count, reverse=True)

    def get_stats(self) -> dict[str, int | float]:
        """Aggregate summary metrics of the experience gene ledger."""
        total = len(self._genes)
        if total == 0:
            return {"total_genes": 0, "avg_confidence": 0.0, "total_proof_count": 0}

        avg_conf = sum(g.confidence_score for g in self._genes.values()) / total
        total_proofs = sum(g.proof_count for g in self._genes.values())
        return {
            "total_genes": total,
            "avg_confidence": round(avg_conf, 4),
            "total_proof_count": total_proofs,
        }

    def _reinforce(self, existing: ExperienceGene, incoming: ExperienceGene) -> ExperienceGene:
        """Apply asymptotic confidence gain and merge new refuted hypotheses."""
        new_proof_count = existing.proof_count + 1
        # Asymptotic saturation formula: conf + (1 - conf) * 0.15
        new_conf = min(0.99, round(existing.confidence_score + (1.0 - existing.confidence_score) * 0.15, 4))

        merged_hypotheses = list(existing.hypotheses_refuted)
        for h in incoming.hypotheses_refuted:
            if h not in merged_hypotheses:
                merged_hypotheses.append(h)

        merged_signals = sorted(set(existing.trigger_signals).union(incoming.trigger_signals))
        merged_tags = sorted(set(existing.tags).union(incoming.tags))

        reinforced = ExperienceGene(
            gene_id=existing.gene_id,
            trigger_signals=merged_signals,
            hypotheses_refuted=merged_hypotheses[:10],
            proven_resolution=incoming.proven_resolution or existing.proven_resolution,
            polarity=existing.polarity,
            confidence_score=new_conf,
            proof_count=new_proof_count,
            provenance_session_id=incoming.provenance_session_id or existing.provenance_session_id,
            tags=merged_tags,
            created_at=existing.created_at,
            updated_at=time.time(),
        )
        self._genes[existing.gene_id] = reinforced
        return reinforced

    @staticmethod
    def _compute_signal_overlap(sig_a: list[str], sig_b: list[str]) -> float:
        """Compute Jaccard similarity between two signal lists."""
        set_a = {s.lower() for s in sig_a}
        set_b = {s.lower() for s in sig_b}
        if not set_a or not set_b:
            return 0.0
        return len(set_a.intersection(set_b)) / len(set_a.union(set_b))

    def _evict_weakest_gene(self) -> None:
        """Evict the gene with lowest confidence score and lowest proof count."""
        if not self._genes:
            return
        weakest_id = min(
            self._genes.keys(),
            key=lambda gid: (self._genes[gid].confidence_score, self._genes[gid].proof_count),
        )
        del self._genes[weakest_id]
