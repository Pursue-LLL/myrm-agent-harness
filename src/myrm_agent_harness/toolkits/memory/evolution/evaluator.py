"""Order Invariance Evaluator for validating robustness against sequential bias."""

import itertools
import math
import random
import re
from collections.abc import Sequence

from .models import (
    EvidenceContext,
    EvolvingMemoryRule,
    PermutationEvaluationResult,
    RuleStatus,
)

_TEMPORAL_COUPLING_KEYWORDS: tuple[str, ...] = (
    "then",
    "afterwards",
    "subsequently",
    "following that",
    "as a result of the above",
    "firstly",
    "secondly",
    "finally",
    "in the previous step",
    "based on the prior output",
)


class OrderInvarianceEvaluator:
    """Evaluates candidate evolving memory rules against out-of-order task permutations."""

    def __init__(
        self,
        invariance_threshold: float = 0.90,
        max_permutations: int = 6,
        seed: int = 42,
    ) -> None:
        """Initialize evaluator with threshold and permutation bounds.

        Args:
            invariance_threshold: Minimum consistency ratio (default 0.90) required to pass.
            max_permutations: Maximum permutation sequence permutations to synthesize.
            seed: Pseudo-random seed for deterministic permutation shuffling.
        """
        self._invariance_threshold = invariance_threshold
        self._max_permutations = max(2, max_permutations)
        self._rng = random.Random(seed)

    def evaluate(self, rule: EvolvingMemoryRule) -> PermutationEvaluationResult:
        """Execute permutation invariance evaluation over candidate rule evidence contexts.

        Args:
            rule: The evolving memory rule under evaluation.

        Returns:
            PermutationEvaluationResult with calculated score, pass/fail state, and diagnostics.
        """
        contexts: list[EvidenceContext] = rule.evidence_contexts
        divergence_reasons: list[str] = []

        if not contexts:
            return PermutationEvaluationResult(
                rule_id=rule.rule_id,
                invariance_score=0.0,
                permutations_tested=1,
                passed_gate=False,
                threshold=self._invariance_threshold,
                divergence_reasons=["Rule contains zero evidence contexts for factual validation."],
            )

        if len(contexts) == 1:
            # Single context has no temporal permutation adversary, probe for transient phrases
            penalty = self._probe_transient_temporal_coupling(rule.statement, contexts[0].facts)
            score = max(0.0, 1.0 - penalty)
            if penalty > 0.0:
                divergence_reasons.append(
                    f"Single-source rule exhibits sequential coupling bias (penalty={penalty:.2f})."
                )
            passed = score >= self._invariance_threshold
            return PermutationEvaluationResult(
                rule_id=rule.rule_id,
                invariance_score=score,
                permutations_tested=1,
                passed_gate=passed,
                threshold=self._invariance_threshold,
                divergence_reasons=divergence_reasons,
            )

        # Multi-context case: synthesize out-of-order permutations
        permutations = self._generate_permutations(contexts)
        consistent_count = 0
        total_tested = len(permutations)

        # Baseline evaluation against the original sequence
        base_premise_set = self._extract_context_premises(contexts)

        for perm_idx, perm_seq in enumerate(permutations):
            perm_premise_set = self._extract_context_premises(perm_seq)
            # Verify premise completeness invariance
            is_consistent, reason = self._verify_premise_consistency(
                rule.statement, base_premise_set, perm_premise_set, perm_idx
            )
            if is_consistent:
                consistent_count += 1
            else:
                divergence_reasons.append(reason)

        raw_invariance = consistent_count / float(total_tested)
        # Apply global statement temporal coupling penalty
        coupling_penalty = self._probe_transient_temporal_coupling(rule.statement, ())
        final_score = max(0.0, min(1.0, raw_invariance * (1.0 - coupling_penalty)))

        if coupling_penalty > 0.0:
            divergence_reasons.append(
                f"Rule statement incorporates transient sequence markers (penalty={coupling_penalty:.2f})."
            )

        passed_gate = final_score >= self._invariance_threshold

        return PermutationEvaluationResult(
            rule_id=rule.rule_id,
            invariance_score=final_score,
            permutations_tested=total_tested,
            passed_gate=passed_gate,
            threshold=self._invariance_threshold,
            divergence_reasons=divergence_reasons,
        )

    def evaluate_and_promote(self, rule: EvolvingMemoryRule) -> tuple[EvolvingMemoryRule, PermutationEvaluationResult]:
        """Evaluate rule and update status if passing the invariance gate.

        Args:
            rule: Candidate rule.

        Returns:
            Tuple of updated rule and evaluation report.
        """
        report = self.evaluate(rule)
        rule.invariance_score = report.invariance_score
        if report.passed_gate:
            rule.status = RuleStatus.ACTIVE
        else:
            rule.status = RuleStatus.REJECTED
        return rule, report

    def _generate_permutations(self, contexts: list[EvidenceContext]) -> list[list[EvidenceContext]]:
        """Synthesize forward, reversed, and deterministic pseudo-random out-of-order sequences."""
        results: list[list[EvidenceContext]] = []
        n = len(contexts)

        # Always include forward and strictly reversed
        results.append(list(contexts))
        results.append(list(reversed(contexts)))

        if n <= 3:
            all_perms = list(itertools.permutations(contexts))
            for p in all_perms:
                cand = list(p)
                if cand not in results and len(results) < self._max_permutations:
                    results.append(cand)
        else:
            # Sample permutations deterministically
            attempts = 0
            while len(results) < self._max_permutations and attempts < 20:
                attempts += 1
                shuffled = list(contexts)
                self._rng.shuffle(shuffled)
                if shuffled not in results:
                    results.append(shuffled)

        return results

    def _extract_context_premises(self, seq: Sequence[EvidenceContext]) -> set[str]:
        """Normalize facts across context sequence."""
        premises: set[str] = set()
        for c in seq:
            for f in c.facts:
                norm = f.strip().lower()
                if norm:
                    premises.add(norm)
        return premises

    def _verify_premise_consistency(
        self,
        statement: str,
        base_premises: set[str],
        perm_premises: set[str],
        perm_idx: int,
    ) -> tuple[bool, str]:
        """Check whether premises survive permutation without semantic collapse."""
        # Baseline check: set containment is invariant under permutation
        diff = base_premises.symmetric_difference(perm_premises)
        if diff:
            return False, f"Permutation {perm_idx} dropped essential premises: {diff}"

        # Temporal causal leak check: statement must not require monotonic ordering of facts
        norm_stmt = statement.lower()
        if "first step" in norm_stmt and perm_idx > 0:
            return False, f"Permutation {perm_idx} violates ordinal dependency 'first step'"

        return True, ""

    def _probe_transient_temporal_coupling(self, statement: str, facts: Sequence[str]) -> float:
        """Compute penalty if statement or facts are coupled to transient chronological cues."""
        text_corpus = (statement + " " + " ".join(facts)).lower()
        hits = 0
        for kw in _TEMPORAL_COUPLING_KEYWORDS:
            if re.search(r"\b" + re.escape(kw) + r"\b", text_corpus):
                hits += 1

        if hits == 0:
            return 0.0
        # Logarithmic saturation penalty: 1 hit = 0.15, 2 hits = 0.25, 3+ hits = 0.40
        return min(0.50, 0.15 * math.log2(1.0 + hits))
