"""Tests for 4-Layer Progressive Disclosure Cognitive Path and Evidence Traceability Suite (Item 227)."""

import pytest

from myrm_agent_harness.agent.context_management.progressive_disclosure import (
    AttributionValidationResult,
    CognitiveMilestoneFact,
    DisclosureStage,
    EvidenceAttributionType,
    EvidenceCitation,
    ProgressiveDisclosureConfig,
    ProgressiveDisclosureEngine,
)


def test_five_stage_state_machine_progression() -> None:
    """Verify state machine progresses sequentially through all 5 cognitive stages with milestone recording."""
    engine = ProgressiveDisclosureEngine()
    session_id = "sess-prog-disclosure-01"

    # 1. Initialize at Stage 1 (BUSINESS_META)
    init_stage = engine.initialize_session_path(session_id, "Refactor enterprise checkout transaction flow")
    assert init_stage == DisclosureStage.BUSINESS_META
    assert engine.get_current_stage(session_id) == DisclosureStage.BUSINESS_META

    # Step to Stage 2: ARCHITECTURE_TOPOLOGY
    cite_meta = EvidenceCitation(
        attribution_type=EvidenceAttributionType.BUSINESS_RULE,
        source_file="docs/domain/checkout_rules.json",
        line_number=24,
        snippet="Order status must transition from PENDING to PAID atomically.",
    )
    s2 = engine.advance_stage(
        session_id=session_id,
        stage_findings="Clarified checkout business boundary and non-reversible settlement rule.",
        citations=[cite_meta],
    )
    assert s2 == DisclosureStage.ARCHITECTURE_TOPOLOGY

    # Step to Stage 3: SERVICE_SCHEMA
    cite_topo = EvidenceCitation(
        attribution_type=EvidenceAttributionType.SERVICE_CONTRACT,
        source_file="specs/topology/services_graph.yaml",
        line_number=58,
        snippet="CheckoutService -> PaymentGateway, InventoryLedger.",
    )
    s3 = engine.advance_stage(
        session_id=session_id,
        stage_findings="Identified upstream and downstream services: PaymentGateway and InventoryLedger.",
        citations=[cite_topo],
    )
    assert s3 == DisclosureStage.SERVICE_SCHEMA

    # Step to Stage 4: INFRASTRUCTURE_GUARD
    cite_schema = EvidenceCitation(
        attribution_type=EvidenceAttributionType.SERVICE_CONTRACT,
        source_file="specs/api/payment_v2.yaml",
        line_number=112,
        snippet="POST /api/v2/charge idempotency_key header required.",
    )
    s4 = engine.advance_stage(
        session_id=session_id,
        stage_findings="Payment schema mandates idempotency_key UUID.",
        citations=[cite_schema],
    )
    assert s4 == DisclosureStage.INFRASTRUCTURE_GUARD

    # Step to Stage 5: CODE_EVIDENCE_GROUNDING
    cite_infra = EvidenceCitation(
        attribution_type=EvidenceAttributionType.INFRA_PRINCIPLE,
        source_file="docs/platform/sla_timeouts.md",
        line_number=15,
        snippet="Maximum RPC timeout is bounded at 2500ms.",
    )
    s5 = engine.advance_stage(
        session_id=session_id,
        stage_findings="Enforced 2500ms timeout and retry circuit breaker.",
        citations=[cite_infra],
    )
    assert s5 == DisclosureStage.CODE_EVIDENCE_GROUNDING

    # Step to COMPLETED
    cite_code = EvidenceCitation(
        attribution_type=EvidenceAttributionType.CODE_SLICE,
        source_file="src/checkout/service.py",
        line_number=145,
        snippet="charge_payment(token, idempotency_key=req.key, timeout_ms=2500)",
    )
    s_done = engine.advance_stage(
        session_id=session_id,
        stage_findings="Grounded implementation in exact checkout code slice.",
        citations=[cite_code],
    )
    assert s_done == DisclosureStage.COMPLETED

    # Check milestone history count
    milestones = engine.get_cognitive_path_summary(session_id)
    assert len(milestones) == 5
    assert milestones[0].stage == DisclosureStage.BUSINESS_META
    assert milestones[4].stage == DisclosureStage.CODE_EVIDENCE_GROUNDING


def test_assemble_stage_context_minimalism() -> None:
    """Verify assemble_stage_context provides condensed prior facts and focused stage payload."""
    engine = ProgressiveDisclosureEngine()
    session_id = "sess-context-minimal"
    engine.initialize_session_path(session_id, "Audit auth token expiration")

    cite = EvidenceCitation(
        attribution_type=EvidenceAttributionType.BUSINESS_RULE,
        source_file="auth/policy.json",
        line_number=10,
        snippet="JWT expires in 15 minutes.",
    )
    engine.advance_stage(session_id, "Verified token lifetime is 15 min", [cite])

    # Currently in Stage 2 (ARCHITECTURE_TOPOLOGY)
    context_bundle = engine.assemble_stage_context(
        session_id=session_id,
        stage_specific_payload="Topology: Gateway -> AuthServer -> RedisStore",
    )

    assert context_bundle["stage"] == DisclosureStage.ARCHITECTURE_TOPOLOGY.value
    assert "Current Cognitive Stage: [ARCHITECTURE_TOPOLOGY]" in context_bundle["guidance_header"]
    assert "[规则] auth/policy.json:10" in context_bundle["guidance_header"]
    assert "Topology: Gateway -> AuthServer -> RedisStore" in context_bundle["stage_payload"]


def test_evidence_attribution_validation_success() -> None:
    """Verify proposals with proper citations pass attribution validation."""
    engine = ProgressiveDisclosureEngine()
    session_id = "sess-attribution-valid"

    proposal_with_evidence = (
        "## Technical Architecture Proposal\n"
        "1. We will modify the payment token validator: [代码] src/auth/token_verifier.py:88\n"
        "2. We will refactor checkout idempotency check: [契约] specs/api/checkout.yaml:42\n"
        "3. Enforce circuit breaker timeout: [原则] infra/reliability_rules.md:19\n"
    )

    result: AttributionValidationResult = engine.validate_evidence_attribution(
        session_id=session_id,
        proposal_text=proposal_with_evidence,
    )

    assert result.is_valid is True
    assert result.total_claims == 3
    assert result.verified_claims == 3
    assert result.unverified_claims == 0
    assert len(result.violations) == 0
    assert len(result.citations_found) == 3


def test_evidence_attribution_validation_violation() -> None:
    """Verify proposals making unsupported modification claims fail validation and trigger violations."""
    engine = ProgressiveDisclosureEngine(ProgressiveDisclosureConfig(strict_evidence_enforcement=True))
    session_id = "sess-attribution-invalid"

    unsupported_proposal = (
        "## Vague Architecture Proposal\n"
        "1. We will modify the payment gateway immediately without checking.\n"
        "2. We will refactor database transaction locks.\n"
    )

    result: AttributionValidationResult = engine.validate_evidence_attribution(
        session_id=session_id,
        proposal_text=unsupported_proposal,
    )

    assert result.is_valid is False
    assert result.total_claims == 2
    assert result.verified_claims == 0
    assert result.unverified_claims == 2
    assert len(result.violations) > 0
    assert any("Unsubstantiated architectural claim" in v for v in result.violations)
