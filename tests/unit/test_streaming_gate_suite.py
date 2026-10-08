"""Unit tests for Streaming Endpoint Identity Gate Parity Suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.streaming_gate import (
    GateDecision,
    StreamingAccessDeniedError,
    StreamingClientIdentity,
    StreamingEndpointContract,
    StreamingEndpointRegistry,
    StreamingIdentityGateEvaluator,
    StreamingTransport,
)


@pytest.fixture
def sample_registry() -> StreamingEndpointRegistry:
    registry = StreamingEndpointRegistry()
    registry.register_contracts(
        [
            StreamingEndpointContract(
                endpoint_path="/api/v1/agents/general_agent/streaming",
                transport=StreamingTransport.SERVER_SENT_EVENTS,
                requires_auth=True,
                required_scope="chat:stream",
                target_resource_type="chat",
                supports_remote_access=True,
            ),
            StreamingEndpointContract(
                endpoint_path="/api/v1/tasks/stream",
                transport=StreamingTransport.SERVER_SENT_EVENTS,
                requires_auth=True,
                required_scope="tasks:stream",
                target_resource_type="task",
                supports_remote_access=True,
            ),
            StreamingEndpointContract(
                endpoint_path="/api/v1/debug/local_event_stream",
                transport=StreamingTransport.WEBSOCKET,
                requires_auth=True,
                required_scope="debug:stream",
                supports_remote_access=False,  # Local only
            ),
        ]
    )
    return registry


def test_unauthenticated_stream_rejected(sample_registry: StreamingEndpointRegistry) -> None:
    evaluator = StreamingIdentityGateEvaluator(registry=sample_registry)
    contract = sample_registry.get_contract("/api/v1/tasks/stream")
    assert contract is not None

    anonymous_identity = StreamingClientIdentity(
        subject_id=None,
        auth_source=None,
    )

    verdict = evaluator.evaluate_access(contract, anonymous_identity)
    assert verdict.decision == GateDecision.DENIED_UNAUTHENTICATED
    assert verdict.status_code == 401

    with pytest.raises(StreamingAccessDeniedError, match=r"\[401\]"):
        evaluator.assert_access(contract, anonymous_identity)


def test_scope_mismatch_rejected(sample_registry: StreamingEndpointRegistry) -> None:
    evaluator = StreamingIdentityGateEvaluator(registry=sample_registry)
    contract = sample_registry.get_contract("/api/v1/tasks/stream")
    assert contract is not None

    identity = StreamingClientIdentity(
        subject_id="user_123",
        auth_source="bearer_token",
        granted_scopes=("chat:read",),  # Missing tasks:stream
    )

    verdict = evaluator.evaluate_access(contract, identity)
    assert verdict.decision == GateDecision.DENIED_SCOPE_MISMATCH
    assert verdict.status_code == 403

    with pytest.raises(StreamingAccessDeniedError, match=r"\[403\].*Missing required permission scope"):
        evaluator.assert_access(contract, identity)


def test_resource_binding_confinement(sample_registry: StreamingEndpointRegistry) -> None:
    evaluator = StreamingIdentityGateEvaluator(registry=sample_registry)
    contract = sample_registry.get_contract("/api/v1/agents/general_agent/streaming")
    assert contract is not None

    # Mobile pair token restricted strictly to chat_session_001
    scoped_identity = StreamingClientIdentity(
        subject_id="mobile_user",
        auth_source="pair_token",
        granted_scopes=("chat:stream",),
        bound_resource_ids=("chat_session_001",),
    )

    # 1. Access to bound chat_session_001 is allowed
    allowed_verdict = evaluator.evaluate_access(
        contract, scoped_identity, requested_resource_id="chat_session_001"
    )
    assert allowed_verdict.decision == GateDecision.ALLOWED
    assert allowed_verdict.status_code == 200

    # 2. Access to another user's chat_session_999 is blocked
    denied_verdict = evaluator.evaluate_access(
        contract, scoped_identity, requested_resource_id="chat_session_999"
    )
    assert denied_verdict.decision == GateDecision.DENIED_RESOURCE_UNBOUND
    assert denied_verdict.status_code == 403


def test_remote_exposure_blocked_for_local_only_stream(
    sample_registry: StreamingEndpointRegistry,
) -> None:
    evaluator = StreamingIdentityGateEvaluator(registry=sample_registry)
    contract = sample_registry.get_contract("/api/v1/debug/local_event_stream")
    assert contract is not None

    remote_identity = StreamingClientIdentity(
        subject_id="remote_admin",
        auth_source="bearer_token",
        granted_scopes=("debug:stream",),
        is_remote=True,
    )

    verdict = evaluator.evaluate_access(contract, remote_identity)
    assert verdict.decision == GateDecision.DENIED_REMOTE_BLOCKED
    assert verdict.status_code == 403


def test_parity_audit_detects_unauthenticated_and_unscoped_endpoints() -> None:
    contracts = [
        # Insecure contract missing authentication
        StreamingEndpointContract(
            endpoint_path="/insecure/stream",
            transport=StreamingTransport.SERVER_SENT_EVENTS,
            requires_auth=False,
        ),
        # Resource stream missing explicit scope definition
        StreamingEndpointContract(
            endpoint_path="/api/notifications/stream",
            transport=StreamingTransport.SERVER_SENT_EVENTS,
            requires_auth=True,
            target_resource_type="notification",
            required_scope=None,
        ),
    ]

    issues = StreamingIdentityGateEvaluator.audit_parity(contracts)
    assert len(issues) == 2
    assert any(i.issue_type == "UNAUTHENTICATED_STREAM" and i.severity == "CRITICAL" for i in issues)
    assert any(i.issue_type == "UNSCOPED_RESOURCE_STREAM" and i.severity == "HIGH" for i in issues)
