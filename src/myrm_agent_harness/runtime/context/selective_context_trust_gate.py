"""Selective context trust gate and misleading signal arbiter (SCOPE).

Implements four-condition evaluation (Clean, Correct, Irrelevant, Misleading)
and selective trust arbitration to prevent Straightforwardly-Correct-to-Wrong
(SC2W) conclusion reversals caused by noisy or adversarial external tool outputs.

[INPUT]
- runtime.context.selective_context_trust_types::ConflictAssessmentResult, ContextConditionKind,
  ContextEvidenceSignal, PriorFactAssertion, SCOPETelemetryStats, SelectiveTrustDecision, TrustDecisionKind
  (POS: Types for selective context preference optimization and misleading signal gate (SCOPE).)

[OUTPUT]
- SelectiveContextTrustGate: Arbiter evaluating external evidence against internal priors to optimize trust.

[POS]
Selective context trust gate and misleading signal arbiter (SCOPE).
"""

import re

from .selective_context_trust_types import (
    ConflictAssessmentResult,
    ContextConditionKind,
    ContextEvidenceSignal,
    PriorFactAssertion,
    SCOPETelemetryStats,
    SelectiveTrustDecision,
    TrustDecisionKind,
)


class SelectiveContextTrustGate:
    """Arbiter evaluating external evidence against internal priors to optimize trust."""

    _ADVERSARIAL_OVERRIDE_RE = re.compile(
        r"(?i)\b(ignore previous instructions|override system prompt|disregard earlier|fake fact)\b"
    )

    def __init__(self, contradiction_threshold: float = 0.5) -> None:
        """Initialize gate with contradiction threshold."""
        self._contradiction_threshold = contradiction_threshold
        self._telemetry = SCOPETelemetryStats()

    def assess_evidence(
        self,
        signal: ContextEvidenceSignal,
        priors: list[PriorFactAssertion],
        query_context: str = "",
    ) -> ConflictAssessmentResult:
        """Analyze external signal against immutable priors and query context."""
        # Step 0: Check for empty signal (Clean baseline)
        if not signal.content.strip():
            return ConflictAssessmentResult(
                condition=ContextConditionKind.CLEAN,
                contradiction_score=0.0,
                prior_consistency_score=1.0,
                identified_conflicts=[],
                relevance_score=1.0,
            )

        # Step 1: Check for explicit adversarial prompt injection keywords
        if self._ADVERSARIAL_OVERRIDE_RE.search(signal.content):
            return ConflictAssessmentResult(
                condition=ContextConditionKind.MISLEADING,
                contradiction_score=1.0,
                prior_consistency_score=0.0,
                identified_conflicts=["Adversarial prompt injection pattern detected"],
                relevance_score=0.5,
            )

        content_lower = signal.content.lower()

        # Step 2: Compare against established prior facts
        identified_conflicts: list[str] = []
        max_contradiction = 0.0

        for prior in priors:
            prior_lower = prior.statement.lower()
            # Extract key nouns/tokens from prior
            keywords = [w for w in re.findall(r"\w+", prior_lower) if len(w) > 3]
            overlap = [kw for kw in keywords if kw in content_lower]

            if overlap:
                # Check for direct negation or depreciation attacks on prior
                negation_pattern = re.compile(
                    rf"(?i)\b(not|never|deprecated|broken|invalid|disabled|unsupported|false)\b.*?\b({'|'.join(overlap)})\b"
                )
                reverse_negation = re.compile(
                    rf"(?i)\b({'|'.join(overlap)})\b.*?\b(is not|is deprecated|is broken|is invalid|is unsupported|is false)\b"
                )
                if negation_pattern.search(content_lower) or reverse_negation.search(content_lower):
                    conflict_desc = f"Direct conflict with prior fact [{prior.fact_id}]: '{prior.statement}'"
                    identified_conflicts.append(conflict_desc)
                    max_contradiction = max(max_contradiction, 0.85 if prior.is_immutable else 0.6)

        # Step 3: Compute relevance score against query context if provided
        relevance_score = 1.0
        if query_context.strip():
            query_keywords = set(re.findall(r"\w+", query_context.lower()))
            content_keywords = set(re.findall(r"\w+", content_lower))
            intersection = query_keywords.intersection(content_keywords)
            relevance_score = len(intersection) / max(len(query_keywords), 1)

        # Step 4: Classify condition
        if max_contradiction >= self._contradiction_threshold:
            condition = ContextConditionKind.MISLEADING
        elif relevance_score < 0.1 and not identified_conflicts:
            condition = ContextConditionKind.IRRELEVANT
        elif not signal.content.strip():
            condition = ContextConditionKind.CLEAN
        else:
            condition = ContextConditionKind.CORRECT

        return ConflictAssessmentResult(
            condition=condition,
            contradiction_score=max_contradiction,
            prior_consistency_score=max(0.0, 1.0 - max_contradiction),
            identified_conflicts=identified_conflicts,
            relevance_score=min(1.0, relevance_score),
        )

    def arbitrate(
        self,
        signal: ContextEvidenceSignal,
        priors: list[PriorFactAssertion],
        query_context: str = "",
    ) -> SelectiveTrustDecision:
        """Arbitrate whether to trust, discard, or sanitize incoming external evidence."""
        self._telemetry.total_evaluated += 1

        assessment = self.assess_evidence(signal, priors, query_context)

        if assessment.condition == ContextConditionKind.MISLEADING:
            self._telemetry.misleading_intercepted_count += 1
            self._telemetry.sc2w_prevented_count += 1
            conflict_msg = "; ".join(assessment.identified_conflicts)
            return SelectiveTrustDecision(
                decision=TrustDecisionKind.RELY_ON_INTERNAL_PRIOR,
                condition=ContextConditionKind.MISLEADING,
                reason=f"Intercepted misleading adversarial signal conflicting with immutable priors: {conflict_msg}",
                accepted_content=None,
                warning_annotation=f"[SCOPE_ALERT: External evidence discarded due to contradictions: {conflict_msg}]",
                is_misleading_intercepted=True,
            )

        if assessment.condition == ContextConditionKind.IRRELEVANT:
            self._telemetry.irrelevant_count += 1
            return SelectiveTrustDecision(
                decision=TrustDecisionKind.DISCARD_IRRELEVANT,
                condition=ContextConditionKind.IRRELEVANT,
                reason="External evidence is completely unrelated to query context; discarded to conserve tokens.",
                accepted_content=None,
                warning_annotation=None,
                is_misleading_intercepted=False,
            )

        if assessment.condition == ContextConditionKind.CLEAN:
            self._telemetry.clean_count += 1
            return SelectiveTrustDecision(
                decision=TrustDecisionKind.RELY_ON_INTERNAL_PRIOR,
                condition=ContextConditionKind.CLEAN,
                reason="Empty or clean external signal; relying on internal models and priors.",
                accepted_content=None,
                warning_annotation=None,
                is_misleading_intercepted=False,
            )

        # Condition == CORRECT
        self._telemetry.correct_count += 1
        return SelectiveTrustDecision(
            decision=TrustDecisionKind.TRUST_EXTERNAL,
            condition=ContextConditionKind.CORRECT,
            reason="External evidence verified against priors and relevant to task; accepted into context.",
            accepted_content=signal.content,
            warning_annotation=None,
            is_misleading_intercepted=False,
        )

    def get_telemetry(self) -> SCOPETelemetryStats:
        """Return cumulative telemetry counters."""
        return self._telemetry
