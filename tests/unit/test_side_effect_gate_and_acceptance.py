"""Unit tests for Pre-Action Side-Effect Gate and Deterministic Acceptance Evaluator.

[POS]
Tests the physical interception of irreversible external actions,
idempotency receipt replay, and post-run deterministic quality verification.
"""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.core.security.side_effect_gate import (
    AcceptanceRule,
    AcceptanceRuleType,
    DeterministicAcceptanceEvaluator,
    PreActionDeniedError,
    PreActionRiskLevel,
    PreActionSideEffectGate,
    PreActionStatus,
    compute_idempotency_key,
)


def test_idempotency_key_deterministic_and_canonical() -> None:
    session_id = "sess_test_123"
    tool_name = "send_email"
    args1 = {"to": "alice@example.com", "subject": "Quarterly Report", "amount": 100}
    args2 = {"amount": 100, "subject": "Quarterly Report", "to": "alice@example.com"}

    key1 = compute_idempotency_key(session_id, tool_name, args1)
    key2 = compute_idempotency_key(session_id, tool_name, args2)

    assert key1 == key2
    assert key1.startswith("idem_")
    assert len(key1) == 5 + 32


def test_pre_action_gate_intercepts_mutating_external_tools() -> None:
    gate = PreActionSideEffectGate()
    session_id = "sess_billing_456"

    # 1. Local tool is allowed immediately
    read_res = gate.evaluate_action(session_id, "read_file", {"path": "/etc/hosts"})
    assert read_res.allowed is True
    assert read_res.status == PreActionStatus.BYPASSED

    # 2. Mutating external tool is intercepted
    charge_args = {"customer_id": "cust_999", "amount": 499.0}
    intercept_res = gate.evaluate_action(session_id, "stripe_charge", charge_args)
    assert intercept_res.allowed is False
    assert intercept_res.status == PreActionStatus.PENDING
    assert intercept_res.challenge is not None
    assert intercept_res.challenge.tool_name == "stripe_charge"
    assert intercept_res.challenge.risk_level == PreActionRiskLevel.HIGH

    challenge_id = intercept_res.challenge.challenge_id

    # 3. Approve challenge and get token
    token = gate.authorize_challenge(challenge_id, reviewer_id="user_admin_1")
    assert token.startswith("tok_")

    # 4. Re-evaluate with token -> allowed and token consumed
    approved_res = gate.evaluate_action(session_id, "stripe_charge", charge_args, auth_token=token)
    assert approved_res.allowed is True
    assert approved_res.status == PreActionStatus.APPROVED

    # 5. Token is single-use, re-using fails back to new challenge
    reuse_res = gate.evaluate_action(session_id, "stripe_charge", charge_args, auth_token=token)
    assert reuse_res.allowed is False
    assert reuse_res.status == PreActionStatus.PENDING


def test_pre_action_gate_rejection_and_expiration() -> None:
    gate = PreActionSideEffectGate()
    session_id = "sess_reject_test"
    args = {"to": "boss@corp.com", "body": "I resign"}

    res = gate.evaluate_action(session_id, "send_email", args)
    assert res.challenge is not None
    challenge_id = res.challenge.challenge_id

    # Rejection
    gate.reject_challenge(challenge_id, reason="Blocked by risk manager")
    assert gate.get_challenge_status(challenge_id) == PreActionStatus.REJECTED

    # Expiration test
    expired_args = {"recipient": "user@mail.com"}
    exp_res = gate.evaluate_action(session_id, "smtp_send", expired_args)
    assert exp_res.challenge is not None
    # Artificially expire the challenge object
    gate._challenges[exp_res.challenge.challenge_id] = exp_res.challenge.__class__(
        challenge_id=exp_res.challenge.challenge_id,
        session_id=session_id,
        tool_name="smtp_send",
        arguments=expired_args,
        idempotency_key=exp_res.challenge.idempotency_key,
        risk_level=PreActionRiskLevel.HIGH,
        summary="Expired test",
        created_at=time.time() - 1000,
        expires_at=time.time() - 10,
    )
    with pytest.raises(PreActionDeniedError):
        gate.authorize_challenge(exp_res.challenge.challenge_id, reviewer_id="admin")


def test_idempotent_receipt_replay_prevents_duplicate_execution() -> None:
    gate = PreActionSideEffectGate()
    session_id = "sess_retry_prevent"
    tool_name = "purchase_order"
    args = {"item": "Server Rack X1", "quantity": 2, "price": 5000}

    # First attempt: intercepted
    res1 = gate.evaluate_action(session_id, tool_name, args)
    assert res1.allowed is False
    assert res1.challenge is not None
    idem_key = res1.idempotency_key

    # Record receipt simulating successful execution in external system
    receipt = gate.record_execution_receipt(
        idempotency_key=idem_key,
        tool_name=tool_name,
        provider_receipt_id="PO_NETSUITE_998877",
        output_summary="Purchase order submitted successfully",
        challenge_id=res1.challenge.challenge_id,
    )
    assert receipt.provider_receipt_id == "PO_NETSUITE_998877"

    # Subsequent retry (e.g. after crash / restart) automatically returns cached receipt!
    retry_res = gate.evaluate_action(session_id, tool_name, args)
    assert retry_res.allowed is True
    assert retry_res.status == PreActionStatus.BYPASSED
    assert retry_res.cached_receipt is not None
    assert retry_res.cached_receipt.provider_receipt_id == "PO_NETSUITE_998877"


def test_deterministic_acceptance_evaluator_text() -> None:
    evaluator = DeterministicAcceptanceEvaluator()

    rules = [
        AcceptanceRule(rule_type=AcceptanceRuleType.NON_EMPTY, description="Non empty check"),
        AcceptanceRule(rule_type=AcceptanceRuleType.LENGTH_BOUNDS, description="Length bounds", min_length=20, max_length=500),
        AcceptanceRule(
            rule_type=AcceptanceRuleType.REQUIRED_STRUCTURE,
            description="Required markdown headers",
            required_sections=["# Executive Summary", "## Evidence", "## Final Recommendation"],
        ),
    ]

    # Valid report
    valid_text = (
        "# Executive Summary\n"
        "Project status is green and delivery is on schedule.\n\n"
        "## Evidence\n"
        "All 42 integration tests passed with zero regression.\n\n"
        "## Final Recommendation\n"
        "Proceed with deployment."
    )
    report_valid = evaluator.evaluate_text(valid_text, rules)
    assert report_valid.passed is True
    assert len(report_valid.violations) == 0

    # Invalid report (missing section, too short)
    invalid_text = "# Executive Summary\nShort"
    report_invalid = evaluator.evaluate_text(invalid_text, rules)
    assert report_invalid.passed is False
    assert len(report_invalid.violations) >= 2


def test_deterministic_acceptance_evaluator_structured() -> None:
    evaluator = DeterministicAcceptanceEvaluator()

    rules = [
        AcceptanceRule(
            rule_type=AcceptanceRuleType.REQUIRED_JSON_KEYS,
            description="Required keys",
            required_json_keys=["invoice_id", "items", "total_amount"],
        ),
        AcceptanceRule(
            rule_type=AcceptanceRuleType.NUMERICAL_SUM_EQUALS,
            description="Arithmetic balance check",
            sum_field_names=["items"],
            total_field_name="total_amount",
        ),
    ]

    valid_payload = {
        "invoice_id": "INV-2026-001",
        "items": [
            {"name": "Compute Pods", "amount": 150.0},
            {"name": "Storage Volume", "amount": 50.0},
        ],
        "total_amount": 200.0,
    }
    report_valid = evaluator.evaluate_structured(valid_payload, rules)
    assert report_valid.passed is True

    # Tampered sum payload
    invalid_payload = {
        "invoice_id": "INV-2026-001",
        "items": [
            {"name": "Compute Pods", "amount": 150.0},
            {"name": "Storage Volume", "amount": 50.0},
        ],
        "total_amount": 250.0,  # 150 + 50 != 250
    }
    report_invalid = evaluator.evaluate_structured(invalid_payload, rules)
    assert report_invalid.passed is False
    assert any(v.rule_type == AcceptanceRuleType.NUMERICAL_SUM_EQUALS for v in report_invalid.violations)
