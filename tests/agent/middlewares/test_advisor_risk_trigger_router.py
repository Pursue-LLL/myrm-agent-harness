"""Tests for AdvisorRiskTriggerRouter.

Verifies:
1. ReplanMiddleware consecutive failures trigger
2. LoopGuard warning / break / anomaly patterns trigger
3. Fatal unrecoverable errors bypass trigger
4. Immune turns cooldown gate
5. Max per session quota ceiling
6. Reset functionality
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage, ToolMessage

from myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router import (
    AdvisorRiskTriggerRouter,
    RiskTriggerReason,
    is_unrecoverable_fatal_error,
)
from myrm_agent_harness.agent.security.guards.loop_guard.types import (
    LoopGuardMetrics,
    LoopKind,
)
from myrm_agent_harness.toolkits.llms.consensus.moa_overlay_types import (
    MoAOverlayConfig,
)


def test_fatal_error_bypass_detection() -> None:
    assert is_unrecoverable_fatal_error("HTTP 401 Unauthorized: Invalid API key")
    assert is_unrecoverable_fatal_error("Permission denied: /etc/shadow (403)")
    assert is_unrecoverable_fatal_error("OSError: [Errno 28] No space left on device: ENOSPC")
    assert is_unrecoverable_fatal_error("ConnectionRefusedError: [Errno 111] ECONNREFUSED")

    # Regular tool errors are recoverable
    assert not is_unrecoverable_fatal_error("SyntaxError: invalid syntax at line 10")
    assert not is_unrecoverable_fatal_error("ValueError: unexpected parameter")
    assert not is_unrecoverable_fatal_error("")


def test_router_nominal_no_trigger() -> None:
    router = AdvisorRiskTriggerRouter(MoAOverlayConfig())
    messages = [HumanMessage(content="Hello")]
    decision = router.evaluate_trigger(messages=messages, current_turn=1)

    assert not decision.should_trigger
    assert decision.reason is None
    assert decision.risk_score == 0.0


def test_router_triggers_on_consecutive_replan_errors() -> None:
    router = AdvisorRiskTriggerRouter(MoAOverlayConfig(risk_trigger_failure_threshold=2))

    with patch(
        "myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router.get_max_consecutive_replan_errors",
        return_value=2,
    ):
        decision = router.evaluate_trigger(messages=[], current_turn=1)

    assert decision.should_trigger
    assert decision.reason == RiskTriggerReason.CONSECUTIVE_TOOL_FAILURES
    assert decision.risk_score >= 0.8


def test_router_triggers_on_multi_tool_failures() -> None:
    router = AdvisorRiskTriggerRouter(MoAOverlayConfig(risk_trigger_failure_threshold=3))

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router.get_max_consecutive_replan_errors",
            return_value=1,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router.get_replan_error_summary",
            return_value={"bash": 1, "fetch_web": 1},
        ),
    ):
        decision = router.evaluate_trigger(messages=[], current_turn=1)

    assert decision.should_trigger
    assert decision.reason == RiskTriggerReason.MULTI_TOOL_FAILURES


def test_router_triggers_on_loop_guard_anomaly() -> None:
    router = AdvisorRiskTriggerRouter(MoAOverlayConfig())
    mock_guard = MagicMock()
    mock_guard.last_detection_kind = LoopKind.REPETITION.value

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router.get_max_consecutive_replan_errors",
            return_value=0,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router.get_replan_error_summary",
            return_value={},
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router.get_loop_guard",
            return_value=mock_guard,
        ),
    ):
        decision = router.evaluate_trigger(messages=[], current_turn=1)

    assert decision.should_trigger
    assert decision.reason == RiskTriggerReason.LOOP_GUARD_WARNING


def test_router_triggers_on_loop_guard_metrics_detection() -> None:
    router = AdvisorRiskTriggerRouter(MoAOverlayConfig())
    mock_guard = MagicMock()
    mock_guard.last_detection_kind = None
    mock_guard.get_metrics.return_value = LoopGuardMetrics(total_detections=2)

    with (
        patch(
            "myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router.get_max_consecutive_replan_errors",
            return_value=0,
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router.get_replan_error_summary",
            return_value={},
        ),
        patch(
            "myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router.get_loop_guard",
            return_value=mock_guard,
        ),
    ):
        decision = router.evaluate_trigger(messages=[], current_turn=1)

    assert decision.should_trigger
    assert decision.reason == RiskTriggerReason.LOOP_GUARD_WARNING
    assert "2 anomaly pattern(s)" in decision.detail



def test_router_bypasses_fatal_error() -> None:
    router = AdvisorRiskTriggerRouter(MoAOverlayConfig(risk_trigger_failure_threshold=1))
    messages = [
        ToolMessage(
            content="Error 401 Unauthorized: Invalid API token provided",
            status="error",
            tool_call_id="call_1",
        )
    ]

    with patch(
        "myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router.get_max_consecutive_replan_errors",
        return_value=2,
    ):
        decision = router.evaluate_trigger(messages=messages, current_turn=1)

    assert not decision.should_trigger
    assert decision.reason == RiskTriggerReason.UNRECOVERABLE_FATAL_ERROR


def test_router_enforces_cooldown_window() -> None:
    router = AdvisorRiskTriggerRouter(MoAOverlayConfig(risk_trigger_immune_turns=3))
    router.record_trigger(turn_index=2)

    with patch(
        "myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router.get_max_consecutive_replan_errors",
        return_value=5,
    ):
        # turn 3 is within cooldown (3 - 2 = 1 < 3)
        decision = router.evaluate_trigger(messages=[], current_turn=3)
        assert not decision.should_trigger
        assert "Immune cooldown active" in decision.detail

        # turn 5 has cooled down (5 - 2 = 3 >= 3)
        decision_cooled = router.evaluate_trigger(messages=[], current_turn=5)
        assert decision_cooled.should_trigger


def test_router_enforces_session_quota() -> None:
    router = AdvisorRiskTriggerRouter(
        MoAOverlayConfig(risk_trigger_max_per_session=2, risk_trigger_immune_turns=1)
    )

    with patch(
        "myrm_agent_harness.agent.middlewares.advisor_risk_trigger_router.get_max_consecutive_replan_errors",
        return_value=5,
    ):
        router.record_trigger(turn_index=1)
        router.record_trigger(turn_index=3)

        assert router.triggers_count == 2
        decision = router.evaluate_trigger(messages=[], current_turn=5)
        assert not decision.should_trigger
        assert "Session trigger quota reached" in decision.detail


def test_router_reset() -> None:
    router = AdvisorRiskTriggerRouter(MoAOverlayConfig())
    router.record_trigger(turn_index=5)
    assert router.triggers_count == 1
    assert router.last_trigger_turn == 5

    router.reset()
    assert router.triggers_count == 0
    assert router.last_trigger_turn == -999
