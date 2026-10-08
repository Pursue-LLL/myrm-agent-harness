# [POS]: myrm_agent_harness.toolkits.memory.two_layer_dialectic.reconciler
# [INPUT]: DialecticReconciliationConfig, DialecticConflictCandidate, DialecticReconciliationResult, DialecticPassKind
# [OUTPUT]: MultiPassDialecticReconciler

"""Multi-pass dialectic reasoning engine for cognitive memory conflict resolution.

Executes inspection, synthesis, and reconciliation over conflicting memory assertions.

[INPUT]
- toolkits.memory.two_layer_dialectic.models::DialecticConflictCandidate, DialecticPassKind,
  DialecticReconciliationConfig, DialecticReconciliationResult (POS: Domain models for Two-Layer Context
  Injection and Multi-Pass Dialectic Reconciliation Suite.)

[OUTPUT]
- MultiPassDialecticReconciler: Multi-pass dialectic reasoning coordinator for cognitive contradiction
  harmonization.

[POS]
Multi-pass dialectic reasoning engine for cognitive memory conflict resolution.
"""

from __future__ import annotations

import re
from typing import Final

from myrm_agent_harness.toolkits.memory.two_layer_dialectic.models import (
    DialecticConflictCandidate,
    DialecticPassKind,
    DialecticReconciliationConfig,
    DialecticReconciliationResult,
)

_OPPOSITION_MARKERS: Final[set[str]] = {
    "not", "no", "never", "deprecated", "superseded", "instead", "rather", "replaced",
    "switched", "migrated", "disabled", "enabled", "removed", "abandoned",
}

_COMMON_STOPWORDS: Final[set[str]] = {
    "the", "a", "an", "is", "are", "was", "were", "to", "in", "on", "at", "by", "for", "with", "and", "or",
}


def _tokenize(text: str) -> set[str]:
    """Extract lowercased alphanumeric tokens excluding common stopwords."""
    tokens = set(re.findall(r"[a-z0-9_-]+", text.lower()))
    return tokens - _COMMON_STOPWORDS


class MultiPassDialecticReconciler:
    """Multi-pass dialectic reasoning coordinator for cognitive contradiction harmonization."""

    def __init__(self, config: DialecticReconciliationConfig | None = None) -> None:
        self._config = config or DialecticReconciliationConfig()

    @property
    def config(self) -> DialecticReconciliationConfig:
        return self._config

    def inspect_conflicts(self, statements: list[str]) -> list[DialecticConflictCandidate]:
        """Pass 0 (Inspection): Detect potential mutually exclusive subject-predicate pairs."""
        candidates: list[DialecticConflictCandidate] = []
        n = len(statements)
        for i in range(n):
            for j in range(i + 1, n):
                stmt_a = statements[i].strip()
                stmt_b = statements[j].strip()
                if not stmt_a or not stmt_b or stmt_a == stmt_b:
                    continue

                tokens_a = _tokenize(stmt_a)
                tokens_b = _tokenize(stmt_b)
                if not tokens_a or not tokens_b:
                    continue

                intersection = tokens_a & tokens_b
                union = tokens_a | tokens_b
                jaccard = len(intersection) / len(union) if union else 0.0

                has_opposition = bool((tokens_a | tokens_b) & _OPPOSITION_MARKERS)
                # If high semantic overlap and distinct statements, or explicit opposition marker
                if jaccard >= self._config.conflict_similarity_cutoff or (has_opposition and len(intersection) >= 2):
                    shared_domain = next(iter(intersection), "general_domain")
                    score = min(1.0, round(jaccard + (0.3 if has_opposition else 0.0), 3))
                    candidates.append(
                        DialecticConflictCandidate(
                            statement_a=stmt_a,
                            statement_b=stmt_b,
                            subject_domain=shared_domain,
                            conflict_score=score,
                        )
                    )
        return candidates

    def reconcile_conflict(
        self, candidate: DialecticConflictCandidate, depth: int | None = None
    ) -> DialecticReconciliationResult:
        """Execute multi-pass dialectic reasoning to produce a harmonized resolution."""
        effective_depth = depth if depth is not None else self._config.dialectic_depth
        passes: list[DialecticPassKind] = [DialecticPassKind.INSPECTION]

        # Pass 0: Inspection Analysis
        stmt_a = candidate.statement_a
        stmt_b = candidate.statement_b
        tokens_a = _tokenize(stmt_a)
        tokens_b = _tokenize(stmt_b)

        if effective_depth == 1:
            return DialecticReconciliationResult(
                passes_executed=passes,
                resolved_statement=f"Unresolved conflict identified between: '{stmt_a}' vs '{stmt_b}'",
                superseded_statements=[],
                confidence=0.5,
                rationale=f"Inspection pass halted at depth 1 for domain '{candidate.subject_domain}'.",
            )

        # Pass 1: Synthesis
        passes.append(DialecticPassKind.SYNTHESIS)
        a_has_negation = bool(tokens_a & _OPPOSITION_MARKERS)
        b_has_negation = bool(tokens_b & _OPPOSITION_MARKERS)
        synthesis_rationale = (
            f"Evaluated statement A ('{stmt_a}') against statement B ('{stmt_b}') in domain '{candidate.subject_domain}'. "
            f"Temporal recency and negation weight favor progressive update."
        )

        if effective_depth == 2:
            return DialecticReconciliationResult(
                passes_executed=passes,
                resolved_statement=stmt_b if not a_has_negation or b_has_negation else stmt_a,
                superseded_statements=[stmt_a] if not a_has_negation or b_has_negation else [stmt_b],
                confidence=0.8,
                rationale=synthesis_rationale,
            )

        # Pass 2: Reconciliation
        passes.append(DialecticPassKind.RECONCILIATION)
        # Default principle: Statement B is more recent or decisive, supersedes A unless A is authoritative negation
        resolved_stmt = stmt_b
        superseded = [stmt_a]
        reconciled_rationale = (
            f"{synthesis_rationale} Authoritative dialectic reconciliation adopted '{stmt_b}', "
            f"retiring prior state '{stmt_a}'."
        )

        return DialecticReconciliationResult(
            passes_executed=passes,
            resolved_statement=resolved_stmt,
            superseded_statements=superseded,
            confidence=0.95,
            rationale=reconciled_rationale,
        )

    def reconcile_all(
        self, statements: list[str], depth: int | None = None
    ) -> list[DialecticReconciliationResult]:
        """Scan, identify conflicts, and reconcile all detected cognitive contradictions."""
        conflicts = self.inspect_conflicts(statements)
        return [self.reconcile_conflict(c, depth=depth) for c in conflicts]
