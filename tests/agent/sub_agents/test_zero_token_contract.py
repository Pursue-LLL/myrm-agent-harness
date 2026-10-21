"""Unit tests for Zero-Token Fleet Runtime Event Mirror Contract Pack."""

import pytest

from myrm_agent_harness.agent.sub_agents.zero_token_contract import (
    PROTECTED_VIZ_SURFACES,
    ZeroTokenContractGuard,
    ZeroTokenContractViolationError,
    ZeroTokenEvent,
)


def test_mirror_runtime_event_zero_tokens() -> None:
    """Verifies that mirroring runtime events consumes strictly 0 tokens."""
    guard = ZeroTokenContractGuard(chat_id="chat-test-001", estimated_tokens_per_event=150)
    event = ZeroTokenEvent(
        event_id="evt-001",
        source="runtime_sse",
        event_type="subagent_status_update",
        agent_id="agent-scout-1",
        payload={"status": "executing", "progress": 45},
    )

    snapshot = guard.mirror_runtime_event(event)
    assert snapshot.chat_id == "chat-test-001"
    assert snapshot.total_events_mirrored == 1
    assert snapshot.total_tokens_spent == 0
    assert snapshot.saved_tokens_estimated == 150
    assert snapshot.violations_intercepted == 0
    assert snapshot.is_compliant is True
    assert snapshot.last_mirrored_at is not None


def test_mirror_batch_events() -> None:
    """Verifies batch mirroring of multiple runtime events."""
    guard = ZeroTokenContractGuard(chat_id="chat-test-002", estimated_tokens_per_event=200)
    events = [
        ZeroTokenEvent(
            event_id=f"evt-{i}",
            source="gateway_webhook",
            event_type="tool_start",
            agent_id="agent-worker-1",
            payload={"tool": "search_code", "step": i},
        )
        for i in range(5)
    ]

    snapshot = guard.mirror_batch_events(events)
    assert snapshot.total_events_mirrored == 5
    assert snapshot.total_tokens_spent == 0
    assert snapshot.saved_tokens_estimated == 1000
    assert len(guard.get_recent_events(limit=3)) == 3


def test_intercept_protected_viz_surface_llm_call() -> None:
    """Verifies Doctor guard blocks illegal LLM invocations from viz surfaces."""
    guard = ZeroTokenContractGuard(chat_id="chat-test-003")

    for surface in ("fleet_canvas", "3d_office", "pet_status", "custom_viz_widget"):
        with pytest.raises(ZeroTokenContractViolationError) as exc_info:
            guard.intercept_llm_call(
                caller_surface=surface,
                prompt="Tell me what animation to play for the agent",
            )
        assert surface in str(exc_info.value)

    snapshot = guard.get_audit_snapshot()
    assert snapshot.violations_intercepted == 4
    assert snapshot.is_compliant is False
    assert snapshot.total_tokens_spent == 0  # Still zero because it was blocked!
    assert len(snapshot.recent_violations) == 4


def test_allow_non_viz_surface_llm_call() -> None:
    """Verifies business non-viz surfaces are safely passed without violation."""
    guard = ZeroTokenContractGuard(chat_id="chat-test-004")

    # Should not raise exception
    guard.intercept_llm_call(
        caller_surface="core_orchestrator",
        prompt="Analyze the repo and plan the refactoring",
    )
    guard.intercept_llm_call(
        caller_surface="tool_execution_agent",
        prompt="Synthesize tool outputs",
    )

    snapshot = guard.get_audit_snapshot()
    assert snapshot.violations_intercepted == 0
    assert snapshot.is_compliant is True


def test_protected_surfaces_constant_membership() -> None:
    """Verifies standard protected surfaces are defined in constant set."""
    assert "fleet_canvas" in PROTECTED_VIZ_SURFACES
    assert "3d_office" in PROTECTED_VIZ_SURFACES
    assert "pet_status" in PROTECTED_VIZ_SURFACES
    assert "ambient_display" in PROTECTED_VIZ_SURFACES


def test_reset_clears_audit_ledger() -> None:
    """Verifies reset cleans up all events and violations."""
    guard = ZeroTokenContractGuard(chat_id="chat-test-005")
    guard.mirror_runtime_event(
        ZeroTokenEvent(
            event_id="evt-reset",
            source="liveness_heartbeat",
            event_type="node_heartbeat",
            agent_id="node-1",
            payload={"alive": True},
        )
    )
    with pytest.raises(ZeroTokenContractViolationError):
        guard.intercept_llm_call("3d_office", "generate avatar mood")

    snap_before = guard.get_audit_snapshot()
    assert snap_before.total_events_mirrored == 1
    assert snap_before.violations_intercepted == 1

    guard.reset()
    snap_after = guard.get_audit_snapshot()
    assert snap_after.total_events_mirrored == 0
    assert snap_after.violations_intercepted == 0
    assert snap_after.is_compliant is True
    assert snap_after.last_mirrored_at is None
    assert len(guard.get_recent_events()) == 0
