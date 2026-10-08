"""Unit test suite for Zero-Defense Error Acknowledgment and Grounded Re-Verification."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.zero_defense_reverification import (
    PROTOCOL_ACKNOWLEDGMENT_PHRASE,
    DisputeIntentType,
    EvidenceCitation,
    VerificationVerdict,
    ZeroDefenseReVerificationEngine,
)


@pytest.fixture
def engine() -> ZeroDefenseReVerificationEngine:
    eng = ZeroDefenseReVerificationEngine()
    eng.reset_all()
    return eng


def test_detect_dispute_intent_calculation_error(engine: ZeroDefenseReVerificationEngine) -> None:
    text = "你算错了，表格里的汇总金额完全对不上！"
    result = engine.detect_dispute_intent(text)
    assert result.is_dispute is True
    assert result.intent_type == DisputeIntentType.CALCULATION_ERROR
    assert result.mandatory_protocol_phrase == PROTOCOL_ACKNOWLEDGMENT_PHRASE


def test_detect_dispute_intent_legal_error(engine: ZeroDefenseReVerificationEngine) -> None:
    text = "合同第5条根本不是免责条款，你解释完全错了"
    result = engine.detect_dispute_intent(text)
    assert result.is_dispute is True
    assert result.intent_type == DisputeIntentType.LEGAL_COMPLIANCE_ERROR
    assert result.mandatory_protocol_phrase == PROTOCOL_ACKNOWLEDGMENT_PHRASE


def test_detect_dispute_intent_hallucination(engine: ZeroDefenseReVerificationEngine) -> None:
    text = "你在胡说八道，这个库根本没有这个方法"
    result = engine.detect_dispute_intent(text)
    assert result.is_dispute is True
    assert result.intent_type == DisputeIntentType.HALLUCINATION_ACCUSATION


def test_detect_dispute_intent_normal_query(engine: ZeroDefenseReVerificationEngine) -> None:
    text = "请帮我分析一下这篇论文的核心论点"
    result = engine.detect_dispute_intent(text)
    assert result.is_dispute is False
    assert result.intent_type is None
    assert result.mandatory_protocol_phrase == ""


def test_verify_and_cross_check_empty_citations_fail_closed(
    engine: ZeroDefenseReVerificationEngine,
) -> None:
    res = engine.verify_and_cross_check(
        dispute_anchor="Q3 Revenue",
        prior_conclusion="Q3 revenue was $10M",
        citations=[],
    )
    assert res.verdict == VerificationVerdict.AMBIGUOUS_ESCALATE
    assert res.requires_expert_escalation is True
    assert "无法原地证实" in res.correction_explanation


def test_verify_and_cross_check_with_grounded_citation(
    engine: ZeroDefenseReVerificationEngine,
) -> None:
    citations = [
        EvidenceCitation(
            source_path="contracts/master_agreement.md",
            line_or_location="line 88-92",
            quote_snippet="Party B shall not be liable for incidental damages.",
        )
    ]
    res = engine.verify_and_cross_check(
        dispute_anchor="Incidental damages",
        prior_conclusion="Party B has full unlimited liability",
        citations=citations,
        high_risk_domain="legal",
    )
    assert res.verdict == VerificationVerdict.CONFIRMED_USER_CORRECT
    assert res.requires_expert_escalation is True
    assert "master_agreement.md" in res.correction_explanation


def test_expert_escalation_lifecycle(engine: ZeroDefenseReVerificationEngine) -> None:
    ticket = engine.create_expert_escalation(
        session_id="sess-corp-99",
        risk_domain="finance",
        dispute_summary="Dispute regarding EBITDA reconciliation discrepancy",
        prior_conclusion="EBITDA stands at $5.2M",
    )
    assert ticket.ticket_id.startswith("esc-")
    assert ticket.status == "OPEN"

    # Query
    queried = engine.get_escalation_ticket(ticket.ticket_id)
    assert queried is not None
    assert queried.ticket_id == ticket.ticket_id

    # Resolve
    resolved = engine.resolve_escalation_ticket(
        ticket.ticket_id,
        resolution_notes="CFO confirmed line item 14 exclusion was correct.",
    )
    assert resolved.status == "RESOLVED"
    assert resolved.resolution_notes == "CFO confirmed line item 14 exclusion was correct."
