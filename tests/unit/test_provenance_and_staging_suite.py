"""Unit tests for Session Entity Provenance Gate and Two-Stage Staging Approval Suite.

[POS]
Harness core security test suite verifying entity provenance tracking (PROVENANCE_GATE),
out-of-chat host token staging approvals (APPROVAL_GATE), hardcoded Python caps guardrails,
and serialized write locking.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from myrm_agent_harness.core.security.provenance_gate import (
    BusinessCapsGuardrail,
    CapsExceededError,
    HostApprovalToken,
    ProvenanceCheckError,
    SerializedWriteLockManager,
    SessionProvenanceTracker,
    StagedChangeNotApprovedError,
    StagedChangeStatus,
    TwoStageApprovalGate,
)


def test_session_provenance_tracker() -> None:
    tracker = SessionProvenanceTracker()
    session_id = "sess_001"

    # Register read query results
    tracker.record_observed_entity(
        session_id=session_id,
        entity_id="prod_101",
        entity_type="product",
        source_tool="search_catalog",
    )
    tracker.record_observed_entities(
        session_id=session_id,
        entity_ids=["prod_102", "prod_103"],
        entity_type="product",
        source_tool="get_recommendations",
    )

    # 1. Observed entities pass check
    assert tracker.is_entity_observed(session_id, "prod_101") is True
    assert tracker.is_entity_observed(session_id, "prod_102") is True
    assert tracker.is_entity_observed(session_id, "prod_103") is True
    tracker.assert_provenance(session_id, "prod_101", tool_name="add_to_cart")

    # 2. Hallucinated entity is blocked
    assert tracker.is_entity_observed(session_id, "prod_hallucinated_999") is False
    with pytest.raises(ProvenanceCheckError) as exc_info:
        tracker.assert_provenance(session_id, "prod_hallucinated_999", tool_name="add_to_cart")
    assert exc_info.value.entity_id == "prod_hallucinated_999"

    # 3. List and wipe
    assert len(tracker.list_observed_entities(session_id)) == 3
    tracker.clear_session(session_id)
    assert len(tracker.list_observed_entities(session_id)) == 0


def test_two_stage_approval_gate_lifecycle() -> None:
    gate = TwoStageApprovalGate(secret_key="unit_test_secret_key")
    session_id = "sess_002"

    # 1. Stage a high-impact mutation draft
    draft = gate.stage_change(
        session_id=session_id,
        target_entity_id="listing_200",
        mutation_type="price_change",
        diff_payload={"old_price": 100.0, "new_price": 49.0},
    )
    assert draft.status == StagedChangeStatus.STAGED
    assert draft.target_entity_id == "listing_200"

    # 2. Applying without valid token fails
    forged_token = HostApprovalToken(
        token_id="tok_forged",
        staged_id=draft.staged_id,
        operator_id="operator_mallory",
        signature="invalid_signature_hex",
        issued_at=time.time(),
        valid_until=time.time() + 60.0,
    )
    with pytest.raises(StagedChangeNotApprovedError) as exc_info:
        gate.apply_staged_change(draft.staged_id, forged_token)
    assert "Invalid or forged" in exc_info.value.reason

    # 3. Host platform issues authentic signed token
    token = gate.issue_host_approval_token(
        staged_id=draft.staged_id,
        operator_id="operator_alice",
        ttl_seconds=60.0,
    )
    assert token.staged_id == draft.staged_id

    # 4. Applying with authentic token succeeds
    applied = gate.apply_staged_change(draft.staged_id, token)
    assert applied.status == StagedChangeStatus.APPLIED
    assert applied.host_token_id == token.token_id

    # 5. Cannot re-apply already applied draft
    with pytest.raises(StagedChangeNotApprovedError):
        gate.apply_staged_change(draft.staged_id, token)


def test_two_stage_approval_gate_rejection() -> None:
    gate = TwoStageApprovalGate(secret_key="unit_test_secret_key")
    draft = gate.stage_change(
        session_id="sess_003",
        target_entity_id="campaign_300",
        mutation_type="delete_campaign",
        diff_payload={"action": "delete"},
    )
    rejected = gate.reject_staged_change(draft.staged_id)
    assert rejected.status == StagedChangeStatus.REJECTED


def test_business_caps_guardrail() -> None:
    guard = BusinessCapsGuardrail(
        max_discount_percent=40.0,
        max_affected_rows=50,
        max_budget_delta=500.0,
    )

    # 1. Compliant values
    assert len(guard.check_caps(discount_percent=30.0, affected_rows=10, budget_delta=200.0)) == 0
    guard.assert_caps(discount_percent=30.0, affected_rows=10, budget_delta=200.0)

    # 2. Exceeded values produce compliant alternatives
    violations = guard.check_caps(
        discount_percent=70.0,
        affected_rows=120,
        budget_delta=1500.0,
    )
    assert len(violations) == 3
    assert violations[0].parameter_name == "discount_percent"
    assert violations[0].compliant_alternative == 40.0
    assert violations[1].parameter_name == "affected_rows"
    assert violations[1].compliant_alternative == 50.0
    assert violations[2].parameter_name == "budget_delta"
    assert violations[2].compliant_alternative == 500.0

    # 3. assert_caps raises CapsExceededError
    with pytest.raises(CapsExceededError) as exc_info:
        guard.assert_caps(discount_percent=70.0)
    assert len(exc_info.value.violations) == 1


@pytest.mark.asyncio
async def test_serialized_write_lock_manager() -> None:
    manager = SerializedWriteLockManager()
    execution_order: list[int] = []

    async def worker(worker_id: int, delay: float) -> None:
        async with manager.acquire("sess_user_cart"):
            execution_order.append(worker_id)
            await asyncio.sleep(delay)

    # Launch two workers concurrently on the same lock key
    await asyncio.gather(
        worker(1, 0.05),
        worker(2, 0.01),
    )

    # Verify execution was strictly serialized
    assert len(execution_order) == 2
    assert execution_order == [1, 2]
