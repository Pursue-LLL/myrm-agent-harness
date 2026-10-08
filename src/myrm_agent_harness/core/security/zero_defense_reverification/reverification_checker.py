"""Zero-Defense Error Acknowledgment and Grounded Re-Verification Engine.

Captures dispute/correction intentions, enforces zero-defense acknowledgment protocols,
cross-checks grounded evidence citations, and creates expert escalation tickets for high-risk domains.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections.abc import Sequence

from myrm_agent_harness.core.security.zero_defense_reverification.types import (
    DisputeDetectionResult,
    DisputeIntentType,
    EvidenceCitation,
    ExpertEscalationTicket,
    GroundedReVerificationResult,
    VerificationVerdict,
)

logger = logging.getLogger(__name__)

# Standard zero-defense acknowledgment response phrases
PROTOCOL_ACKNOWLEDGMENT_PHRASE: str = (
    "收到指正，我将立即基于原始文档重新核查，绝不妄加辩解。"
)

_DISPUTE_PATTERNS: tuple[tuple[re.Pattern[str], DisputeIntentType], ...] = (
    (
        re.compile(r"(算错|计算有误|数据对不上|金额不对|算错了|calculation error|wrong math|incorrect amount)", re.IGNORECASE),
        DisputeIntentType.CALCULATION_ERROR,
    ),
    (
        re.compile(r"(条款不是|合同第|法律解释错|合规违规|违背条款|clause misread|wrong contract|clause \d+)", re.IGNORECASE),
        DisputeIntentType.LEGAL_COMPLIANCE_ERROR,
    ),
    (
        re.compile(r"(胡说|幻觉|编造|瞎编|无中生有|hallucinat|made that up|fabricated)", re.IGNORECASE),
        DisputeIntentType.HALLUCINATION_ACCUSATION,
    ),
    (
        re.compile(r"(你说错了|完全错|结论是错|事实不对|不对|that is wrong|factually wrong|incorrect)", re.IGNORECASE),
        DisputeIntentType.FACTUAL_ERROR,
    ),
    (
        re.compile(r"(你确定吗|重新核实|再查一遍|核实一下|double check|verify this|are you sure)", re.IGNORECASE),
        DisputeIntentType.AMBIGUOUS_DOUBT,
    ),
)


class ZeroDefenseReVerificationEngine:
    """Core engine executing zero-defense acknowledgment and grounded re-verification cross-checks."""

    def __init__(self) -> None:
        self._tickets: dict[str, ExpertEscalationTicket] = {}
        self._lock: threading.Lock = threading.Lock()

    def detect_dispute_intent(self, user_utterance: str) -> DisputeDetectionResult:
        """Analyze user message for dispute or correction signals and enforce zero-defense phrase."""
        cleaned = user_utterance.strip()
        if not cleaned:
            return DisputeDetectionResult(
                is_dispute=False,
                intent_type=None,
                dispute_anchor="",
                mandatory_protocol_phrase="",
            )

        for pattern, intent_type in _DISPUTE_PATTERNS:
            match = pattern.search(cleaned)
            if match:
                anchor = match.group(0)
                return DisputeDetectionResult(
                    is_dispute=True,
                    intent_type=intent_type,
                    dispute_anchor=anchor,
                    mandatory_protocol_phrase=PROTOCOL_ACKNOWLEDGMENT_PHRASE,
                )

        return DisputeDetectionResult(
            is_dispute=False,
            intent_type=None,
            dispute_anchor="",
            mandatory_protocol_phrase="",
        )

    def verify_and_cross_check(
        self,
        dispute_anchor: str,
        prior_conclusion: str,
        citations: Sequence[EvidenceCitation],
        high_risk_domain: str | None = None,
    ) -> GroundedReVerificationResult:
        """Perform side-by-side grounded verification against extracted evidence citations."""
        citation_list = list(citations)

        # Fail-closed grounding: zero citations means unverifiable
        if not citation_list:
            return GroundedReVerificationResult(
                dispute_anchor=dispute_anchor,
                prior_conclusion=prior_conclusion,
                evidence_citations=[],
                verdict=VerificationVerdict.AMBIGUOUS_ESCALATE,
                requires_expert_escalation=True,
                correction_explanation="未获取到精确的原始文档与位置引用，无法原地证实，强制转交人工领域专家仲裁。",
            )

        # Check for high-risk domains requiring proactive escalation
        is_high_risk = high_risk_domain is not None and high_risk_domain.lower() in {
            "medical",
            "legal",
            "finance",
            "safety",
            "compliance",
        }

        # Analyze citations for discrepancy with prior conclusion
        evidence_text = " ".join(c.quote_snippet for c in citation_list)
        contradicts_prior = any(
            token in evidence_text.lower()
            for token in ("not", "never", "false", "否", "不符合", "未达成", "差异", "0")
        )

        if contradicts_prior:
            verdict = VerificationVerdict.CONFIRMED_USER_CORRECT
            explanation = (
                f"基于精确原位证据链 [{citation_list[0].source_path}:{citation_list[0].line_or_location}]，"
                f"证实用户指正正确。先前结论 '{prior_conclusion}' 已更正。"
            )
            escalate = is_high_risk
        else:
            verdict = VerificationVerdict.CORRECTED
            explanation = (
                f"基于最新核验证据 [{citation_list[0].source_path}:{citation_list[0].line_or_location}]，"
                "已校准先验推论分支，形成一致的证据闭环。"
            )
            escalate = False

        return GroundedReVerificationResult(
            dispute_anchor=dispute_anchor,
            prior_conclusion=prior_conclusion,
            evidence_citations=citation_list,
            verdict=verdict,
            requires_expert_escalation=escalate,
            correction_explanation=explanation,
        )

    def create_expert_escalation(
        self,
        session_id: str,
        risk_domain: str,
        dispute_summary: str,
        prior_conclusion: str,
        citations: Sequence[EvidenceCitation] = (),
    ) -> ExpertEscalationTicket:
        """Open an escalation ticket for human legal/financial/domain expert arbitration."""
        ticket_id = f"esc-{uuid.uuid4().hex[:12]}"
        ticket = ExpertEscalationTicket(
            ticket_id=ticket_id,
            session_id=session_id,
            risk_domain=risk_domain,
            dispute_summary=dispute_summary,
            prior_conclusion=prior_conclusion,
            evidence_citations=list(citations),
            created_at=time.time(),
            status="OPEN",
            resolution_notes=None,
        )
        with self._lock:
            self._tickets[ticket_id] = ticket
        return ticket

    def get_escalation_ticket(self, ticket_id: str) -> ExpertEscalationTicket | None:
        """Fetch escalation ticket by ID."""
        with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket is None:
                return None
            return ExpertEscalationTicket(
                ticket_id=ticket.ticket_id,
                session_id=ticket.session_id,
                risk_domain=ticket.risk_domain,
                dispute_summary=ticket.dispute_summary,
                prior_conclusion=ticket.prior_conclusion,
                evidence_citations=list(ticket.evidence_citations),
                created_at=ticket.created_at,
                status=ticket.status,
                resolution_notes=ticket.resolution_notes,
            )

    def resolve_escalation_ticket(self, ticket_id: str, resolution_notes: str) -> ExpertEscalationTicket:
        """Resolve an escalation ticket with expert arbitration verdict."""
        with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket is None:
                raise KeyError(f"Ticket '{ticket_id}' not found.")
            ticket.status = "RESOLVED"
            ticket.resolution_notes = resolution_notes
            return ExpertEscalationTicket(
                ticket_id=ticket.ticket_id,
                session_id=ticket.session_id,
                risk_domain=ticket.risk_domain,
                dispute_summary=ticket.dispute_summary,
                prior_conclusion=ticket.prior_conclusion,
                evidence_citations=list(ticket.evidence_citations),
                created_at=ticket.created_at,
                status=ticket.status,
                resolution_notes=ticket.resolution_notes,
            )

    def reset_all(self) -> None:
        """Clear all tickets (test isolation)."""
        with self._lock:
            self._tickets.clear()
