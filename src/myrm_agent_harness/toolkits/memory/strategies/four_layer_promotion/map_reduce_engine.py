"""Two-step Map-Reduce memory consolidation engine and structured contract verification.

[INPUT]
- CandidateStatement, CapabilityMethod, PromotionDecision, RulesComplianceItem, ExposureSource
- TriChannelPromotionGate: code-level assertion gate

[OUTPUT]
- TwoStepMapReduceConsolidationEngine: coordinates single-session Map extraction,
  cross-session Reduce clustering and promotion, and structured rules compliance verification.

[POS]
Harness strategy engine implementing Hermes two-step compression (raw -> candidate -> long-term)
with structured rules compliance contract verification.
"""

from __future__ import annotations

import re
import uuid
from typing import Final

from myrm_agent_harness.toolkits.memory.strategies.four_layer_promotion.promotion_gate import (
    TriChannelPromotionGate,
)
from myrm_agent_harness.toolkits.memory.strategies.four_layer_promotion.types import (
    CandidateStatement,
    CapabilityMethod,
    ExposureSource,
    PromotionDecision,
    RulesComplianceItem,
)


class TwoStepMapReduceConsolidationEngine:
    """Engine orchestrating Map-Reduce memory consolidation and structured compliance verification."""

    def __init__(
        self,
        gate: TriChannelPromotionGate | None = None,
    ) -> None:
        self._gate: Final[TriChannelPromotionGate] = gate or TriChannelPromotionGate()

    def map_session(
        self,
        session_id: str,
        events: list[dict[str, str | bool]],
        exposure_source: ExposureSource = ExposureSource.INTERNAL_CHAT,
    ) -> list[CandidateStatement]:
        """Map phase: extract self-contained candidate statements from raw session events.

        Args:
            session_id: Unique session identifier.
            events: Raw event representations, each containing 'id', 'content', and optional 'failed'.
            exposure_source: Origin marker (internal chat vs untrusted external).

        Returns:
            A list of self-contained CandidateStatement objects with evidence bindings.
        """
        candidates: list[CandidateStatement] = []
        for evt in events:
            evt_id = str(evt.get("id", f"evt-{uuid.uuid4().hex[:6]}"))
            content = str(evt.get("content", "")).strip()
            is_failed = bool(evt.get("failed", False))
            is_directive = bool(evt.get("explicit_instruction", False))

            if not content:
                continue

            # Produce clean self-contained statement
            clean_stmt = self._normalize_statement(content)
            candidates.append(
                CandidateStatement(
                    statement=clean_stmt,
                    supported_event_ids=(evt_id,),
                    session_id=session_id,
                    exposure_source=exposure_source,
                    has_tool_failure=is_failed,
                    is_explicit_user_instruction=is_directive,
                )
            )
        return candidates

    def reduce_cross_session(
        self,
        candidates: list[CandidateStatement],
    ) -> tuple[list[CapabilityMethod], list[PromotionDecision]]:
        """Reduce phase: group synonymous statements, evaluate tri-channel gates, and promote methods."""
        clusters = self._cluster_candidates(candidates)
        promoted_methods: list[CapabilityMethod] = []
        decisions: list[PromotionDecision] = []

        for cluster in clusters:
            decision = self._gate.evaluate_statement_group(
                statements=cluster,
                title_hint=f"Consolidated Rule: {cluster[0].statement[:40]}",
                applies_when_hint="Recurring task planning and execution",
            )
            decisions.append(decision)
            if decision.promoted and decision.method_card is not None:
                promoted_methods.append(decision.method_card)

        return promoted_methods, decisions

    def evaluate_rules_compliance(
        self,
        response_text: str,
        active_methods: list[CapabilityMethod],
    ) -> list[RulesComplianceItem]:
        """Verify output text compliance against promoted capability rules (structured verification)."""
        lower_resp = response_text.lower()
        items: list[RulesComplianceItem] = []

        for method in active_methods:
            # Check for compliance with rule steps or failure signals
            is_violated = False
            violation_reason = "Complies with consolidated rule"

            for signal in method.failure_signals:
                if signal.lower() in lower_resp:
                    is_violated = True
                    violation_reason = f"Violated failure signal: '{signal}'"
                    break

            primary_rule = method.method_steps[0] if method.method_steps else method.title
            items.append(
                RulesComplianceItem(
                    rule_id=method.method_id,
                    statement=primary_rule,
                    compliant=not is_violated,
                    rationale=violation_reason,
                )
            )
        return items

    def _normalize_statement(self, raw_text: str) -> str:
        """Strip conversational filler to make the statement standalone and self-contained."""
        cleaned = re.sub(r"^(?:我说|用户说|agent discovered|found that)\s*[:：]?", "", raw_text, flags=re.I).strip()
        return cleaned or raw_text

    def _cluster_candidates(
        self,
        candidates: list[CandidateStatement],
    ) -> list[list[CandidateStatement]]:
        """Group synonymous candidate statements by core semantic key."""
        clusters: dict[str, list[CandidateStatement]] = {}
        for c in candidates:
            # Simple deterministic key: lowercase first 30 normalized chars
            key = re.sub(r"\W+", "", c.statement.lower())[:32]
            if not key:
                key = "general"
            clusters.setdefault(key, []).append(c)
        return list(clusters.values())
