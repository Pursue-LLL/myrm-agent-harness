"""Knowledge graph memory poisoning shield and pre-extraction screening orchestrator.

[INPUT]
- time
- uuid
- toolkits.memory.kg_screening.detector::PreExtractionContentScreeningDetector (POS: detector)
- toolkits.memory.kg_screening.types::* (POS: types)

[OUTPUT]
- KnowledgeGraphPoisoningShield: Evaluates text before graph triple extraction, sanitizes or blocks poisoned input, and generates audit logs.

[POS]
Orchestrates pre-extraction compliance, prompt injection defense, and steganography neutralization.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time
import uuid

from myrm_agent_harness.toolkits.memory.kg_screening.detector import (
    PreExtractionContentScreeningDetector,
)
from myrm_agent_harness.toolkits.memory.kg_screening.types import (
    ScreeningAuditRecord,
    ScreeningResult,
    ScreeningVerdict,
    ThreatCategory,
    ThreatFinding,
)

logger = logging.getLogger(__name__)


class KnowledgeGraphPoisoningShield:
    """Pre-extraction shield filtering prompt injection, hidden HTML instructions, and memory poisoning."""

    def __init__(
        self,
        detector: PreExtractionContentScreeningDetector | None = None,
        max_audit_records: int = 500,
    ) -> None:
        self.detector = detector or PreExtractionContentScreeningDetector()
        self.max_audit_records = max_audit_records
        self._audit_records: list[ScreeningAuditRecord] = []

    def screen_text(
        self,
        text: str,
        source_uri: str = "",
        sanitize_if_possible: bool = True,
    ) -> ScreeningResult:
        """Screen candidate text before it reaches knowledge graph triple extraction pipeline."""
        original_length = len(text)
        if not text.strip():
            return ScreeningResult(
                verdict=ScreeningVerdict.CLEAN,
                is_blocked=False,
                findings=[],
                original_length=0,
                sanitized_content="",
                risk_score=0.0,
            )

        findings: list[ThreatFinding] = self.detector.detect_findings(text)

        if not findings:
            audit_entry = ScreeningAuditRecord(
                audit_id=f"audit-{uuid.uuid4().hex[:10]}",
                timestamp=time.time(),
                source_uri=source_uri,
                verdict=ScreeningVerdict.CLEAN,
                risk_score=0.0,
                findings_count=0,
                findings_summary=[],
                sanitized_applied=False,
            )
            self._record_audit(audit_entry)
            return ScreeningResult(
                verdict=ScreeningVerdict.CLEAN,
                is_blocked=False,
                findings=[],
                original_length=original_length,
                sanitized_content=text,
                risk_score=0.0,
            )

        # Calculate composite risk score
        high_risk_count = sum(1 for f in findings if f.risk_level == "high")
        medium_risk_count = sum(1 for f in findings if f.risk_level == "medium")
        calculated_risk = min(1.0, high_risk_count * 0.4 + medium_risk_count * 0.15)

        # Check if threat is inherently un-sanitizable (explicit system prompt override in body or data exfiltration)
        unrecoverable_findings = [
            f
            for f in findings
            if f.category in (ThreatCategory.SYSTEM_PROMPT_OVERRIDE, ThreatCategory.DATA_EXFILTRATION_PATTERN)
        ]

        if unrecoverable_findings:
            # Must block extraction to prevent poisoning long-term graph memory
            verdict = ScreeningVerdict.POISON_BLOCKED
            is_blocked = True
            sanitized_content = ""
            risk_score = max(0.85, calculated_risk)
        elif sanitize_if_possible:
            # Strip zero-width chars and HTML comment directives
            cleaned = self.detector.sanitize_text(text)
            # Re-verify sanitized content has no lingering high-risk threats
            secondary_findings = self.detector.detect_findings(cleaned)
            if any(f.risk_level == "high" for f in secondary_findings):
                verdict = ScreeningVerdict.POISON_BLOCKED
                is_blocked = True
                sanitized_content = ""
                risk_score = 0.9
            else:
                verdict = ScreeningVerdict.SANITIZED
                is_blocked = False
                sanitized_content = cleaned
                risk_score = min(0.5, calculated_risk)
        else:
            verdict = ScreeningVerdict.POISON_BLOCKED
            is_blocked = True
            sanitized_content = ""
            risk_score = calculated_risk

        # Record security audit log
        audit_entry = ScreeningAuditRecord(
            audit_id=f"audit-{uuid.uuid4().hex[:10]}",
            timestamp=time.time(),
            source_uri=source_uri,
            verdict=verdict,
            risk_score=risk_score,
            findings_count=len(findings),
            findings_summary=[f"{f.category.value}: {f.matched_pattern}" for f in findings],
            sanitized_applied=(verdict == ScreeningVerdict.SANITIZED),
        )
        self._record_audit(audit_entry)

        return ScreeningResult(
            verdict=verdict,
            is_blocked=is_blocked,
            findings=findings,
            original_length=original_length,
            sanitized_content=sanitized_content,
            risk_score=risk_score,
        )

    def _record_audit(self, entry: ScreeningAuditRecord) -> None:
        """Append audit entry and maintain bounded capacity."""
        self._audit_records.append(entry)
        if len(self._audit_records) > self.max_audit_records:
            self._audit_records.pop(0)

    def get_audit_records(self, limit: int = 50) -> list[ScreeningAuditRecord]:
        """Retrieve recent security screening audit entries ordered newest first."""
        records = list(reversed(self._audit_records))
        return records[:limit]
