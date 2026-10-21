"""[INPUT] EvidenceCrossVerificationEngine, models, and diagnostic requests.
[OUTPUT] Pytest verification of 4-tier confidence scoring, dual-channel error audit, and bilateral validation.
[POS] tests/observability/test_evidence_cross_verification.py
"""

import pytest

from myrm_agent_harness.observability.evidence_cross_verification import (
    ConfidenceLevel,
    EvidenceCrossVerificationEngine,
    EvidenceItem,
    EvidenceSourceType,
    VerificationDiagnosisRequest,
    get_default_evidence_verifier,
)


def test_dual_channel_error_code_audit() -> None:
    engine = EvidenceCrossVerificationEngine()

    # 1. Both channels present
    meaning, resolved = engine.resolve_error_code_meaning(
        retcode="E_DOWNSTREAM_502",
        kb_doc="Payment Gateway Bad Gateway",
        code_def="ERR_PAYMENT_GATEWAY_UNAVAILABLE",
    )
    assert resolved is True
    assert "ERR_PAYMENT_GATEWAY_UNAVAILABLE" in meaning
    assert "Payment Gateway Bad Gateway" in meaning

    # 2. Only code definition present
    meaning_code, resolved_code = engine.resolve_error_code_meaning(
        retcode="E_AUTH_401",
        kb_doc="",
        code_def="ERR_UNAUTHORIZED_TOKEN",
    )
    assert resolved_code is True
    assert meaning_code == "ERR_UNAUTHORIZED_TOKEN"

    # 3. Only KB doc present
    meaning_kb, resolved_kb = engine.resolve_error_code_meaning(
        retcode="E_AUTH_403",
        kb_doc="Forbidden user role",
        code_def="",
    )
    assert resolved_kb is True
    assert meaning_kb == "Forbidden user role"

    # 4. Neither channel present -> standardized ErrUnknown fallback without hallucination
    meaning_unknown, resolved_unknown = engine.resolve_error_code_meaning(
        retcode="E_OBSCURE_999",
        kb_doc="",
        code_def="",
    )
    assert resolved_unknown is False
    assert meaning_unknown == "ErrUnknown_E_OBSCURE_999"


def test_bilateral_cross_validation_logic() -> None:
    engine = EvidenceCrossVerificationEngine()

    # 1. Parameter contract mismatch
    consistent, reason = engine.verify_bilateral_call(
        frontend_param="user_id",
        backend_struct="account_uuid, tenant_id",
        trace_duration_ms=200.0,
        downstream_error=False,
    )
    assert consistent is False
    assert "PARAM_MISMATCH" in reason

    # 2. Cumulative serial latency timeout (>5000ms)
    consistent_to, reason_to = engine.verify_bilateral_call(
        frontend_param="account_uuid",
        backend_struct="account_uuid, tenant_id",
        trace_duration_ms=6200.0,
        downstream_error=False,
    )
    assert consistent_to is True
    assert "CUMULATIVE_TIMEOUT" in reason_to

    # 3. Downstream blocker explicitly failing
    consistent_down, reason_down = engine.verify_bilateral_call(
        frontend_param="account_uuid",
        backend_struct="account_uuid, tenant_id",
        trace_duration_ms=300.0,
        downstream_error=True,
    )
    assert consistent_down is True
    assert "DOWNSTREAM_BLOCK" in reason_down


def test_four_tier_confidence_scoring_and_unresolved_guard() -> None:
    engine = EvidenceCrossVerificationEngine()

    # Four distinct sources
    ev_kb = EvidenceItem(
        source_type=EvidenceSourceType.KNOWLEDGE_BASE,
        title="KB Runbook #42",
        detail="Documented known timeout",
        is_verified=True,
    )
    ev_symbol = EvidenceItem(
        source_type=EvidenceSourceType.CODE_SYMBOL,
        title="Code Graph Definition",
        detail="Class PaymentDispatcher located",
        is_verified=True,
    )
    ev_logic = EvidenceItem(
        source_type=EvidenceSourceType.SOURCE_LOGIC,
        title="Source Code Branch",
        detail="Serial loop without timeout deadline",
        is_verified=True,
    )
    ev_runtime = EvidenceItem(
        source_type=EvidenceSourceType.RUNTIME_TELEMETRY,
        title="Distributed Trace Span",
        detail="Duration 5800ms on socket read",
        is_verified=True,
    )

    # All 4 sources verified + error code resolved -> 4 points, HIGH
    score_4, level_4 = engine.calculate_confidence(
        [ev_kb, ev_symbol, ev_logic, ev_runtime],
        error_code_resolved=True,
    )
    assert score_4 == 4
    assert level_4 == ConfidenceLevel.HIGH

    # 3 sources verified + error code resolved -> 3 points, HIGH
    score_3, level_3 = engine.calculate_confidence(
        [ev_symbol, ev_logic, ev_runtime],
        error_code_resolved=True,
    )
    assert score_3 == 3
    assert level_3 == ConfidenceLevel.HIGH

    # 2 sources verified -> 2 points, MEDIUM
    score_2, level_2 = engine.calculate_confidence(
        [ev_logic, ev_runtime],
        error_code_resolved=True,
    )
    assert score_2 == 2
    assert level_2 == ConfidenceLevel.MEDIUM

    # 1 source verified -> 1 point, LOW
    score_1, level_1 = engine.calculate_confidence(
        [ev_runtime],
        error_code_resolved=True,
    )
    assert score_1 == 1
    assert level_1 == ConfidenceLevel.LOW

    # CRITICAL GUARD: If error code is unresolved, max confidence is strictly capped at MEDIUM (2 pts)
    score_capped, level_capped = engine.calculate_confidence(
        [ev_kb, ev_symbol, ev_logic, ev_runtime],
        error_code_resolved=False,
    )
    assert score_capped == 2
    assert level_capped == ConfidenceLevel.MEDIUM


def test_diagnose_root_cause_end_to_end() -> None:
    engine = EvidenceCrossVerificationEngine()
    engine.reset()

    evidences = [
        EvidenceItem(
            source_type=EvidenceSourceType.KNOWLEDGE_BASE,
            title="KB Gateway Spec",
            detail="Timeout SLA is 3000ms",
            is_verified=True,
        ),
        EvidenceItem(
            source_type=EvidenceSourceType.CODE_SYMBOL,
            title="Symbol Router",
            detail="Routed via api/v1/checkout",
            is_verified=True,
            file_path="app/api/checkout.py",
            line_number=88,
        ),
        EvidenceItem(
            source_type=EvidenceSourceType.SOURCE_LOGIC,
            title="Logic Review",
            detail="Serial HTTP request in loop",
            is_verified=True,
            file_path="app/api/checkout.py",
            line_number=95,
        ),
        EvidenceItem(
            source_type=EvidenceSourceType.RUNTIME_TELEMETRY,
            title="Distributed Trace",
            detail="Span timeout 5500ms observed",
            is_verified=True,
            trace_id="tr_9901_abc",
        ),
    ]

    req = VerificationDiagnosisRequest(
        error_code="GATEWAY_TIMEOUT_504",
        event_date="2026-10-13",
        caller_trace_id="tr_9901_abc",
        raw_symptom="Checkout call hung for 5.5s then aborted",
        kb_doc_hint="Downstream checkout SLA violation",
        code_def_hint="ERR_CHECKOUT_TIMEOUT",
        call_budget=15,
    )

    finding = engine.diagnose_root_cause(req=req, evidences=evidences)

    assert finding.error_code == "GATEWAY_TIMEOUT_504"
    assert "ERR_CHECKOUT_TIMEOUT" in finding.resolved_code_meaning
    assert finding.target_file_path == "app/api/checkout.py"
    assert finding.target_line_number == 95
    assert finding.root_cause_category == "CUMULATIVE_TIMEOUT"
    assert finding.confidence_score == 4
    assert finding.confidence_level == ConfidenceLevel.HIGH
    assert finding.bilateral_verified is True
    assert "asyncio.gather" in finding.recommended_patch or "timeout" in finding.recommended_patch

    # Check recent diagnoses
    history = engine.get_recent_diagnoses(limit=5)
    assert len(history) == 1
    assert history[0].diagnosis_id == finding.diagnosis_id

    # Reset
    engine.reset()
    assert len(engine.get_recent_diagnoses()) == 0


def test_singleton_verifier_instance() -> None:
    v1 = get_default_evidence_verifier()
    v2 = get_default_evidence_verifier()
    assert v1 is v2
