"""Unit tests for Spatiotemporal Dual-Engine, Connector Trust & Declarative Saga Suite."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from myrm_agent_harness.core.security.saga_dual_engine import (
    ConnectorTrustGate,
    ConnectorUntrustedError,
    EmissionUnconfirmedError,
    JsonScalar,
    SagaExecutionEngine,
    SpatiotemporalDualEngineGuard,
    ToolIntent,
)


def test_acquisition_tool_intent_bypasses_gates() -> None:
    """Test ACQUISITION tools (read-only) execute freely without connector lease or HITL."""
    guard = SpatiotemporalDualEngineGuard()

    output, audit_rec = guard.execute_tool(
        tool_name="read_local_file",
        intent=ToolIntent.ACQUISITION,
        action_fn=lambda: "content_of_file",
        params={"path": "report.pdf"},
        agent_id="agent-analyst",
    )

    assert output == "content_of_file"
    assert audit_rec is None
    assert guard.saga_engine.step_count == 1


def test_emission_tool_requires_connector_trust() -> None:
    """Test EMISSION tools are blocked if target connector lacks explicit trust lease."""
    guard = SpatiotemporalDualEngineGuard()

    # Attempting emission without trust lease raises ConnectorUntrustedError
    with pytest.raises(ConnectorUntrustedError, match="is UNTRUSTED"):
        guard.execute_tool(
            tool_name="send_payment",
            intent=ToolIntent.EMISSION,
            action_fn=lambda: "tx-ok",
            params={"amount": 100},
            agent_id="agent-payer",
            connector_id="stripe_gateway",
            connector_host="api.stripe.com",
            required_scope="payments:write",
            hitl_confirmed=True,
        )


def test_emission_tool_requires_hitl_confirmation() -> None:
    """Test EMISSION tools with valid connector trust still require secondary HITL confirmation."""
    trust_gate = ConnectorTrustGate()
    trust_gate.grant_lease(
        connector_id="stripe_gateway",
        host="api.stripe.com",
        authorized_scopes=["payments:write"],
    )
    guard = SpatiotemporalDualEngineGuard(trust_gate=trust_gate)

    # Without HITL confirmation, raises EmissionUnconfirmedError
    with pytest.raises(EmissionUnconfirmedError, match="requires explicit secondary HITL confirmation"):
        guard.execute_tool(
            tool_name="send_payment",
            intent=ToolIntent.EMISSION,
            action_fn=lambda: "tx-ok",
            params={"amount": 100},
            agent_id="agent-payer",
            connector_id="stripe_gateway",
            connector_host="api.stripe.com",
            required_scope="payments:write",
            hitl_confirmed=False,
        )


def test_emission_execution_and_audit_record() -> None:
    """Test fully authorized EMISSION executes and generates immutable audit entry."""
    trust_gate = ConnectorTrustGate()
    trust_gate.grant_lease(
        connector_id="db_connector",
        host="db.internal.corp",
        authorized_scopes=["write"],
    )
    guard = SpatiotemporalDualEngineGuard(trust_gate=trust_gate)

    output, audit_rec = guard.execute_tool(
        tool_name="insert_order",
        intent=ToolIntent.EMISSION,
        action_fn=lambda: "inserted-order-42",
        params={"order_id": 42, "item": "laptop"},
        agent_id="agent-ops",
        approver_id="manager-bob",
        connector_id="db_connector",
        connector_host="db.internal.corp",
        required_scope="write",
        hitl_confirmed=True,
        compensator_name="delete_order",
        compensation_params={"order_id": 42},
    )

    assert output == "inserted-order-42"
    assert audit_rec is not None
    assert audit_rec.connector_id == "db_connector"
    assert audit_rec.approver_id == "manager-bob"
    assert audit_rec.compensation_status == "PENDING"
    assert len(guard.get_audit_log()) == 1


def test_declarative_saga_reverse_lifo_rollback() -> None:
    """Test Saga rollback executes compensating actions in reverse LIFO order."""
    saga_engine = SagaExecutionEngine()
    trust_gate = ConnectorTrustGate()
    trust_gate.grant_lease("corp_api", "api.corp.internal", ["all"])
    guard = SpatiotemporalDualEngineGuard(saga_engine=saga_engine, trust_gate=trust_gate)

    compensation_log: list[str] = []

    def undo_step1(params: Mapping[str, JsonScalar]) -> bool:
        compensation_log.append(f"undo_step1::{params.get('uid')}")
        return True

    def undo_step2(params: Mapping[str, JsonScalar]) -> bool:
        compensation_log.append(f"undo_step2::{params.get('charge_id')}")
        return True

    def undo_step3(params: Mapping[str, JsonScalar]) -> bool:
        compensation_log.append(f"undo_step3::{params.get('email_id')}")
        return True

    saga_engine.register_compensator("undo_step1", undo_step1)
    saga_engine.register_compensator("undo_step2", undo_step2)
    saga_engine.register_compensator("undo_step3", undo_step3)

    # Step 1: Create User
    guard.execute_tool(
        tool_name="create_user",
        intent=ToolIntent.EMISSION,
        action_fn=lambda: "created-u1",
        params={"uid": "u1"},
        agent_id="agent-1",
        connector_id="corp_api",
        connector_host="api.corp.internal",
        hitl_confirmed=True,
        compensator_name="undo_step1",
        compensation_params={"uid": "u1"},
    )

    # Step 2: Charge Card
    guard.execute_tool(
        tool_name="charge_card",
        intent=ToolIntent.EMISSION,
        action_fn=lambda: "charged-c1",
        params={"charge_id": "c1"},
        agent_id="agent-1",
        connector_id="corp_api",
        connector_host="api.corp.internal",
        hitl_confirmed=True,
        compensator_name="undo_step2",
        compensation_params={"charge_id": "c1"},
    )

    # Step 3: Send Welcome Email
    guard.execute_tool(
        tool_name="send_welcome_email",
        intent=ToolIntent.EMISSION,
        action_fn=lambda: "sent-e1",
        params={"email_id": "e1"},
        agent_id="agent-1",
        connector_id="corp_api",
        connector_host="api.corp.internal",
        hitl_confirmed=True,
        compensator_name="undo_step3",
        compensation_params={"email_id": "e1"},
    )

    # Workflow encounters error or abort: trigger Saga Rollback!
    rollback_results = guard.rollback_saga()
    assert len(rollback_results) == 3
    assert all(ok for _, ok in rollback_results)

    # Assert reverse LIFO execution: Step 3 first, then Step 2, then Step 1
    assert compensation_log == [
        "undo_step3::e1",
        "undo_step2::c1",
        "undo_step1::u1",
    ]


def test_revoked_lease_immediately_blocks_emission() -> None:
    """Test revoking connector trust lease halts subsequent emissions on that host."""
    trust_gate = ConnectorTrustGate()
    lease = trust_gate.grant_lease("mail_srv", "smtp.corp.internal", ["send"])
    guard = SpatiotemporalDualEngineGuard(trust_gate=trust_gate)

    # Emission allowed while lease is active
    out, _ = guard.execute_tool(
        tool_name="send_mail",
        intent=ToolIntent.EMISSION,
        action_fn=lambda: "mail_sent",
        params={},
        agent_id="agt",
        connector_id="mail_srv",
        connector_host="smtp.corp.internal",
        hitl_confirmed=True,
    )
    assert out == "mail_sent"

    # Revoke lease
    trust_gate.revoke_lease(lease.lease_id)

    # Emission now blocked
    with pytest.raises(ConnectorUntrustedError):
        guard.execute_tool(
            tool_name="send_mail",
            intent=ToolIntent.EMISSION,
            action_fn=lambda: "mail_sent",
            params={},
            agent_id="agt",
            connector_id="mail_srv",
            connector_host="smtp.corp.internal",
            hitl_confirmed=True,
        )
