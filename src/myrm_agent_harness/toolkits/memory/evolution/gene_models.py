"""Data models for Causal Experience Genes and Evolution Ledger.

[INPUT]
- External: pydantic

[OUTPUT]
- GenePolarity: Polarity of the causal experience gene.
- ExperienceGene: A persistent causal experience gene capturing signals, refuted hypotheses, and proven
  resolution.
- GeneMatchQuery: Query parameters to match applicable genes against active task signals.
- GeneMutationAdvice: Synthesized guidance for planning stage and workflow mutation.

[POS]
Data models for Causal Experience Genes and Evolution Ledger.
"""

from __future__ import annotations

import time
from enum import StrEnum

from pydantic import BaseModel, Field


class GenePolarity(StrEnum):
    """Polarity of the causal experience gene."""

    POSITIVE = "positive"  # Proven successful workflow / strategy
    NEGATIVE = "negative"  # Proven pitfall / anti-pattern to avoid


class ExperienceGene(BaseModel):
    """A persistent causal experience gene capturing signals, refuted hypotheses, and proven resolution."""

    gene_id: str = Field(..., description="Unique immutable gene identifier")
    trigger_signals: list[str] = Field(
        default_factory=list, description="Combination of pre-execution symptom signals"
    )
    hypotheses_refuted: list[str] = Field(
        default_factory=list, description="Hypotheses proven to be dead-ends during trials"
    )
    proven_resolution: str = Field(
        ..., description="Empirically verified action path that resolved the problem"
    )
    polarity: GenePolarity = Field(
        default=GenePolarity.POSITIVE, description="Positive guidance or negative avoidance"
    )
    confidence_score: float = Field(
        default=0.8, ge=0.0, le=1.0, description="Confidence level evolving with proofs"
    )
    proof_count: int = Field(
        default=1, ge=1, description="Cumulative count of cross-task validations"
    )
    provenance_session_id: str = Field(
        default="", description="Originating task or session identifier"
    )
    tags: list[str] = Field(default_factory=list, description="Categorical and domain tags")
    created_at: float = Field(default_factory=time.time, description="Creation timestamp")
    updated_at: float = Field(default_factory=time.time, description="Last reinforcement timestamp")


class GeneMatchQuery(BaseModel):
    """Query parameters to match applicable genes against active task signals."""

    active_signals: list[str] = Field(
        default_factory=list, description="Active context symptoms or error signals"
    )
    min_confidence: float = Field(
        default=0.6, ge=0.0, le=1.0, description="Minimum confidence threshold"
    )
    limit: int = Field(default=5, ge=1, le=50, description="Maximum number of genes to return")


class GeneMutationAdvice(BaseModel):
    """Synthesized guidance for planning stage and workflow mutation."""

    gene_id: str
    matched_signals: list[str]
    refuted_paths: list[str]
    recommended_resolution: str
    confidence: float
    polarity: GenePolarity
