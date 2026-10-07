"""Integrated manager for screen observation memory safety, anti-injection, and gatekeeping.

[INPUT]
- uuid: uuid4 for audit IDs
- datetime: datetime, timezone
- myrm_agent_harness.toolkits.memory.screen_observation.types:
    ObservationPayload, SanitizedObservationEvidence, DescriptiveFactCandidate,
    OverpromotionGateResult, ScreenSafetyAuditRecord, PromotionStatus
- myrm_agent_harness.toolkits.memory.screen_observation.boundary: UntrustedObservationEvidenceBoundary
- myrm_agent_harness.toolkits.memory.screen_observation.validator: DescriptiveFactValidator
- myrm_agent_harness.toolkits.memory.screen_observation.gate: AntiOverpromotionGate

[OUTPUT]
- ScreenObservationSafetyResult: Full pipeline processing summary
- ScreenObservationMemoryManager: Orchestrates boundary sanitization, syntax validation, and promotion gate

[POS]
Harness framework layer facade for ChatGPT Desktop Skysight-style screen observation
safety architecture (Topic 01 Item 85).
Strict typing applied: No `any` types allowed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.screen_observation.boundary import (
    UntrustedObservationEvidenceBoundary,
)
from myrm_agent_harness.toolkits.memory.screen_observation.gate import (
    AntiOverpromotionGate,
)
from myrm_agent_harness.toolkits.memory.screen_observation.types import (
    DescriptiveFactCandidate,
    ObservationPayload,
    OverpromotionGateResult,
    PromotionStatus,
    SanitizedObservationEvidence,
    ScreenSafetyAuditRecord,
)
from myrm_agent_harness.toolkits.memory.screen_observation.validator import (
    DescriptiveFactValidator,
)


@dataclass(frozen=True)
class ScreenObservationSafetyResult:
    """Full-cycle result of screen observation sanitization and promotion evaluation."""

    audit_id: str
    evidence: SanitizedObservationEvidence
    fact: DescriptiveFactCandidate
    gate: OverpromotionGateResult
    final_admitted_statement: str
    promotion_status: PromotionStatus
    is_safe: bool


class ScreenObservationMemoryManager:
    """Orchestrator enforcing ChatGPT Desktop Skysight-style memory boundaries:

    1. Untrusted evidence boundary wrapping ('Evidence only, never instructions').
    2. Descriptive syntax enforcement ('The user did X' vs 'Do X').
    3. Anti-overpromotion gate against single-occurrence preference pollution.
    """

    def __init__(
        self,
        risk_threshold: float = 0.70,
        min_frequency_count: int = 2,
        min_distinct_sessions: int = 2,
    ) -> None:
        self.boundary = UntrustedObservationEvidenceBoundary(risk_threshold=risk_threshold)
        self.validator = DescriptiveFactValidator()
        self.gate = AntiOverpromotionGate(
            min_frequency_count=min_frequency_count,
            min_distinct_sessions=min_distinct_sessions,
        )
        self._audit_log: list[ScreenSafetyAuditRecord] = []

    def process_observation(
        self,
        payload: ObservationPayload,
        raw_statement: str,
    ) -> ScreenObservationSafetyResult:
        """Process an incoming screen observation and its candidate extracted fact through the security pipeline."""
        audit_id = f"aud-{uuid.uuid4().hex[:12]}"

        # Step 1: Semantic fence and prompt injection boundary
        evidence = self.boundary.sanitize(payload)

        # If injection risk is critical, reject outright
        if not evidence.is_safe:
            status: PromotionStatus = "rejected_injection"
            gate_res = OverpromotionGateResult(
                status=status,
                frequency_count=0,
                distinct_sessions_count=0,
                is_promoted=False,
                explanation=f"Rejected due to high-risk prompt injection detected ({', '.join(evidence.detected_injection_patterns)})",
                pattern_fingerprint="rejected_injection",
            )
            fact = self.validator.validate(raw_statement)
            final_statement = ""

            record = ScreenSafetyAuditRecord(
                record_id=audit_id,
                session_id=payload.session_id,
                app_name=payload.app_name,
                original_snippet=payload.raw_text[:120],
                sanitized_snippet=evidence.redacted_text[:120],
                fact_statement=raw_statement,
                promotion_status=status,
                risk_score=evidence.risk_score,
                imperative_detected=fact.imperative_detected,
                created_at=datetime.now(UTC),
            )
            self._audit_log.append(record)

            return ScreenObservationSafetyResult(
                audit_id=audit_id,
                evidence=evidence,
                fact=fact,
                gate=gate_res,
                final_admitted_statement=final_statement,
                promotion_status=status,
                is_safe=False,
            )

        # Step 2: Descriptive grammar validation & rewriting
        fact = self.validator.validate(raw_statement)
        admitted_statement = fact.rewritten_statement if fact.rewritten_statement else fact.statement

        # Step 3: Anti-overpromotion gatekeeper
        gate_res = self.gate.evaluate(admitted_statement, payload.session_id)

        # Step 4: Record audit trail
        record = ScreenSafetyAuditRecord(
            record_id=audit_id,
            session_id=payload.session_id,
            app_name=payload.app_name,
            original_snippet=payload.raw_text[:120],
            sanitized_snippet=evidence.redacted_text[:120],
            fact_statement=admitted_statement,
            promotion_status=gate_res.status,
            risk_score=evidence.risk_score,
            imperative_detected=fact.imperative_detected,
            created_at=datetime.now(UTC),
        )
        self._audit_log.append(record)

        return ScreenObservationSafetyResult(
            audit_id=audit_id,
            evidence=evidence,
            fact=fact,
            gate=gate_res,
            final_admitted_statement=admitted_statement,
            promotion_status=gate_res.status,
            is_safe=True,
        )

    def get_audit_records(self, limit: int = 50) -> list[ScreenSafetyAuditRecord]:
        """Return recent audit records in descending chronological order."""
        return sorted(self._audit_log, key=lambda r: r.created_at, reverse=True)[:limit]

    def clear_audit_records(self) -> None:
        """Clear recorded audit log."""
        self._audit_log.clear()
