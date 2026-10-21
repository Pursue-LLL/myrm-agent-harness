"""Types for compile-time contradiction synthesis (CCSP).

[INPUT]
- None (self-contained dataclasses)

[OUTPUT]
- ConceptPair, ConflictVerdict, SynthesisPassResult

[POS]
SSOT value objects for cross-concept evolution page synthesis during wiki compile batches.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConceptPair:
    """A candidate pair of distinct concepts to compare for factual conflict."""

    concept_a: str
    concept_b: str
    reason: str


@dataclass(frozen=True, slots=True)
class ConflictVerdict:
    """Structured LLM verdict for a concept pair."""

    is_factual_conflict: bool
    confidence: float
    topic: str
    side_a: str
    side_b: str
    resolution_hint: str


@dataclass(frozen=True, slots=True)
class SynthesisPassResult:
    """Outcome of a CCSP run."""

    pairs_considered: int
    synthesis_staged: int
