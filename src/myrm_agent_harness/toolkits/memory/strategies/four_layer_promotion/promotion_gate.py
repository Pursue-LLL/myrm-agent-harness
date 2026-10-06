"""Tri-channel code-level verification gate for memory promotion.

[INPUT]
- CandidateStatement: candidate text with session, failure, and provenance metadata
- types: PromotionDecision, PromotionChannel, ExposureSource, CapabilityMethod

[OUTPUT]
- TriChannelPromotionGate: deterministic code assertion gate evaluating
  tri-channel criteria and blocking E->M->B silent poisoning.

[POS]
Harness strategy gate separating LLM natural language extraction from deterministic
code-level assertions (status == failed, cross-session repetition, explicit user directive).
"""

from __future__ import annotations

import uuid
from typing import Final

from myrm_agent_harness.toolkits.memory.strategies.four_layer_promotion.types import (
    CandidateStatement,
    CapabilityMethod,
    ExposureSource,
    PromotionChannel,
    PromotionDecision,
)


class TriChannelPromotionGate:
    """Deterministic code assertion gate enforcing tri-channel criteria for long-term promotion."""

    def __init__(self, min_distinct_sessions: int = 2) -> None:
        self._min_distinct_sessions: Final[int] = max(2, min_distinct_sessions)

    def evaluate_candidates(
        self,
        statements: list[CandidateStatement],
        title_hint: str = "Distilled Method",
        applies_when_hint: str = "General Task Execution",
    ) -> list[PromotionDecision]:
        """Evaluate a list of candidate statements and yield deterministic promotion decisions."""
        return [self.evaluate_statement_group([stmt], title_hint, applies_when_hint) for stmt in statements]

    def evaluate_statement_group(
        self,
        statements: list[CandidateStatement],
        title_hint: str = "Distilled Method",
        applies_when_hint: str = "General Task Execution",
    ) -> PromotionDecision:
        """Evaluate a group of synonymous statements clustered across one or more sessions.

        Enforces the three promotion channels:
        1. TOOL_FAILURE_EVIDENCE: Grounded in real tool failure (status == failed).
        2. REPEATED_ACROSS_SESSIONS: Supported across >= min_distinct_sessions distinct sessions.
        3. EXPLICIT_USER_INSTRUCTION: Direct explicit user directive.

        Blocks E->M->B silent poisoning from external untrusted exposure unless explicitly commanded.
        """
        if not statements:
            return PromotionDecision(
                promoted=False,
                channel=None,
                reason="Empty candidate statement group cannot be promoted.",
                method_card=None,
            )

        # 1. Anti-Poisoning Nail: Block unverified external untrusted exposure
        has_untrusted_exposure = any(
            stmt.exposure_source == ExposureSource.EXTERNAL_UNTRUSTED for stmt in statements
        )
        has_explicit_user_override = any(stmt.is_explicit_user_instruction for stmt in statements)
        if has_untrusted_exposure and not has_explicit_user_override:
            return PromotionDecision(
                promoted=False,
                channel=None,
                reason="E->M->B Anti-Poisoning Gate: Blocked promotion originating from untrusted external source.",
                method_card=None,
            )

        # Collect distinct sessions and aggregated supported event IDs
        distinct_sessions = {stmt.session_id for stmt in statements if stmt.session_id.strip()}
        all_event_ids: list[str] = []
        for stmt in statements:
            for eid in stmt.supported_event_ids:
                if eid not in all_event_ids:
                    all_event_ids.append(eid)
        event_ids_tuple = tuple(all_event_ids)

        # Primary statement text
        primary_text = statements[0].statement

        # Channel 1: TOOL_FAILURE_EVIDENCE
        has_failure_evidence = any(stmt.has_tool_failure for stmt in statements)
        if has_failure_evidence and event_ids_tuple:
            method_card = CapabilityMethod(
                method_id=f"method-{uuid.uuid4().hex[:8]}",
                title=title_hint or "Failure Recovery Rule",
                applies_when=applies_when_hint or "Preventing repeat tool failure",
                method_steps=(f"Rule: {primary_text}", "Enforce pre-execution check"),
                validation_criteria="Tool execution succeeds without repeat failure",
                failure_signals=("Tool returned error or non-zero exit code",),
                supported_event_ids=event_ids_tuple,
                promotion_channel=PromotionChannel.TOOL_FAILURE_EVIDENCE,
            )
            return PromotionDecision(
                promoted=True,
                channel=PromotionChannel.TOOL_FAILURE_EVIDENCE,
                reason="Verified hard tool failure evidence present in supported events.",
                method_card=method_card,
            )

        # Channel 2: EXPLICIT_USER_INSTRUCTION
        if has_explicit_user_override and event_ids_tuple:
            method_card = CapabilityMethod(
                method_id=f"method-{uuid.uuid4().hex[:8]}",
                title=title_hint or "Explicit Directive Rule",
                applies_when=applies_when_hint or "User-defined constraint context",
                method_steps=(f"Guideline: {primary_text}", "Strict adherence required"),
                validation_criteria="Follows exact user specification",
                failure_signals=("Deviates from explicit user directive",),
                supported_event_ids=event_ids_tuple,
                promotion_channel=PromotionChannel.EXPLICIT_USER_INSTRUCTION,
            )
            return PromotionDecision(
                promoted=True,
                channel=PromotionChannel.EXPLICIT_USER_INSTRUCTION,
                reason="Explicit user directive verified with evidence anchor.",
                method_card=method_card,
            )

        # Channel 3: REPEATED_ACROSS_SESSIONS
        if len(distinct_sessions) >= self._min_distinct_sessions and event_ids_tuple:
            method_card = CapabilityMethod(
                method_id=f"method-{uuid.uuid4().hex[:8]}",
                title=title_hint or "Cross-Session Consolidated Practice",
                applies_when=applies_when_hint or "General workflow pattern",
                method_steps=(f"Pattern: {primary_text}", "Apply standard pattern"),
                validation_criteria="Consistent outcome across independent runs",
                failure_signals=("Pattern mismatch or regression detected",),
                supported_event_ids=event_ids_tuple,
                promotion_channel=PromotionChannel.REPEATED_ACROSS_SESSIONS,
            )
            return PromotionDecision(
                promoted=True,
                channel=PromotionChannel.REPEATED_ACROSS_SESSIONS,
                reason=f"Pattern verified across {len(distinct_sessions)} independent sessions.",
                method_card=method_card,
            )

        # Rejection: insufficient code assertions
        return PromotionDecision(
            promoted=False,
            channel=None,
            reason=(
                f"Insufficient evidence for promotion: sessions={len(distinct_sessions)} (need >={self._min_distinct_sessions}), "
                f"failure_evidence={has_failure_evidence}, explicit_instruction={has_explicit_user_override}."
            ),
            method_card=None,
        )
