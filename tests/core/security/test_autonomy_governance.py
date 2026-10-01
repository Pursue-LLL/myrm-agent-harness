"""Unit tests for data-driven autonomy level escalation and exception circuit breaker governance suite.

[INPUT]
- myrm_agent_harness.core.security.autonomy::*

[OUTPUT]
- 100% test coverage for AutonomyLevel, PromotionGateCalculator, AutonomyCircuitBreaker, and AutonomyExecutionInterceptor.
"""

from __future__ import annotations

import concurrent.futures
import time

from myrm_agent_harness.core.security.autonomy import (
    AutonomyBreakerEvent,
    AutonomyCircuitBreaker,
    AutonomyExecutionInterceptor,
    AutonomyLevel,
    BreakerState,
    PromotionGateCalculator,
)


class TestAutonomyLevelAndModels:
    """Validates autonomy enum values and telemetry models."""

    def test_level_ordering(self) -> None:
        assert AutonomyLevel.L1_ADVISOR < AutonomyLevel.L2_COLLABORATOR
        assert AutonomyLevel.L2_COLLABORATOR < AutonomyLevel.L3_SUPERVISOR
        assert AutonomyLevel.L3_SUPERVISOR < AutonomyLevel.L4_CONDITIONAL
        assert AutonomyLevel.L4_CONDITIONAL < AutonomyLevel.L5_AUTONOMOUS

    def test_breaker_event_serialization(self) -> None:
        event = AutonomyBreakerEvent(
            event_id="breaker-test-1",
            session_id="session-xyz",
            reason="Repeated failure",
            error_details="Command failed with exit code 1",
            triggered_tool="bash_code_execute_tool",
            previous_level=AutonomyLevel.L4_CONDITIONAL,
            degraded_level=AutonomyLevel.L2_COLLABORATOR,
            breaker_state=BreakerState.OPEN,
            timestamp=1700000000.0,
        )
        d = event.to_dict()
        assert d["eventId"] == "breaker-test-1"
        assert d["sessionId"] == "session-xyz"
        assert d["previousLevel"] == 4
        assert d["degradedLevel"] == 2
        assert d["breakerState"] == "open"


class TestPromotionGateCalculator:
    """Tests the sliding-window metrics and multi-factor promotion gate."""

    def test_empty_window_metrics(self) -> None:
        calc = PromotionGateCalculator(capacity=50, min_samples=20)
        metrics = calc.get_metrics()
        assert metrics.total_invocations == 0
        assert metrics.success_rate == 0.0
        assert not metrics.is_reliable

    def test_insufficient_samples_rejection(self) -> None:
        calc = PromotionGateCalculator(capacity=50, min_samples=20)
        # Record only 10 invocations (100% success)
        for _ in range(10):
            calc.record_invocation(is_success=True, is_destructive=True)

        res = calc.evaluate_promotion(AutonomyLevel.L2_COLLABORATOR)
        assert not res.eligible
        assert "Insufficient sample window" in res.reason
        assert res.recommended_level is None

    def test_security_violation_zero_tolerance(self) -> None:
        calc = PromotionGateCalculator(capacity=50, min_samples=20)
        for _ in range(25):
            calc.record_invocation(is_success=True, is_destructive=True)
        # Inject 1 security violation
        calc.record_invocation(is_success=False, is_destructive=False, is_violation=True)

        res = calc.evaluate_promotion(AutonomyLevel.L2_COLLABORATOR)
        assert not res.eligible
        assert "Security violations detected" in res.reason

    def test_low_success_rate_rejection(self) -> None:
        calc = PromotionGateCalculator(capacity=50, min_samples=20, required_success_rate=0.95)
        # 18 successes, 2 failures = 90%
        for _ in range(18):
            calc.record_invocation(is_success=True, is_destructive=True)
        for _ in range(2):
            calc.record_invocation(is_success=False, is_destructive=True)

        res = calc.evaluate_promotion(AutonomyLevel.L2_COLLABORATOR)
        assert not res.eligible
        assert "below required" in res.reason

    def test_goodhart_read_only_grinding_rejection(self) -> None:
        calc = PromotionGateCalculator(
            capacity=50,
            min_samples=20,
            required_success_rate=0.98,
            required_mutation_ratio=0.20,
        )
        # 30 successes, but only 2 were destructive (2/30 = 6.6% < 20%)
        for _ in range(28):
            calc.record_invocation(is_success=True, is_destructive=False)
        for _ in range(2):
            calc.record_invocation(is_success=True, is_destructive=True)

        res = calc.evaluate_promotion(AutonomyLevel.L2_COLLABORATOR)
        assert not res.eligible
        assert "read-only grinding rejected" in res.reason

    def test_successful_promotion_transitions(self) -> None:
        calc = PromotionGateCalculator(
            capacity=50,
            min_samples=20,
            required_success_rate=0.95,
            required_mutation_ratio=0.20,
        )
        # 25 total: 24 successes (8 destructive), 1 fail -> 96% success, 32% destructive
        for _ in range(16):
            calc.record_invocation(is_success=True, is_destructive=False)
        for _ in range(8):
            calc.record_invocation(is_success=True, is_destructive=True)
        calc.record_invocation(is_success=False, is_destructive=False)

        # L1 -> L2
        r1 = calc.evaluate_promotion(AutonomyLevel.L1_ADVISOR)
        assert r1.eligible
        assert r1.recommended_level == AutonomyLevel.L2_COLLABORATOR

        # L2 -> L4
        r2 = calc.evaluate_promotion(AutonomyLevel.L2_COLLABORATOR)
        assert r2.eligible
        assert r2.recommended_level == AutonomyLevel.L4_CONDITIONAL

        # L3 -> L4
        r3 = calc.evaluate_promotion(AutonomyLevel.L3_SUPERVISOR)
        assert r3.eligible
        assert r3.recommended_level == AutonomyLevel.L4_CONDITIONAL

        # L4 -> Already at autonomy
        r4 = calc.evaluate_promotion(AutonomyLevel.L4_CONDITIONAL)
        assert not r4.eligible
        assert "already at or above L4" in r4.reason

    def test_sliding_window_eviction(self) -> None:
        calc = PromotionGateCalculator(capacity=10, min_samples=5)
        # Fill with 10 failures
        for _ in range(10):
            calc.record_invocation(is_success=False)
        assert calc.get_metrics().success_rate == 0.0

        # Push 10 successes; all 10 failures must be evicted from ring buffer
        for _ in range(10):
            calc.record_invocation(is_success=True, is_destructive=True)

        metrics = calc.get_metrics()
        assert metrics.total_invocations == 10
        assert metrics.success_rate == 1.0


class TestAutonomyCircuitBreaker:
    """Tests 3-state circuit breaker mechanics, consecutive failure trips, and half-open healing."""

    def test_single_failure_does_not_trip(self) -> None:
        breaker = AutonomyCircuitBreaker(failure_threshold=2)
        event = breaker.on_failure(
            error_msg="First error",
            tool_name="tool_a",
            session_id="s1",
            current_level=AutonomyLevel.L4_CONDITIONAL,
        )
        assert event is None
        assert breaker.state == BreakerState.CLOSED
        assert breaker.consecutive_failures == 1

    def test_two_consecutive_failures_trips_breaker(self) -> None:
        breaker = AutonomyCircuitBreaker(failure_threshold=2)
        breaker.on_failure("Err 1", "tool_a", "s1", AutonomyLevel.L4_CONDITIONAL)
        event = breaker.on_failure("Err 2", "tool_a", "s1", AutonomyLevel.L4_CONDITIONAL)

        assert event is not None
        assert breaker.state == BreakerState.OPEN
        assert event.breaker_state == BreakerState.OPEN
        assert event.previous_level == AutonomyLevel.L4_CONDITIONAL
        assert event.degraded_level == AutonomyLevel.L2_COLLABORATOR

    def test_success_resets_consecutive_failures(self) -> None:
        breaker = AutonomyCircuitBreaker(failure_threshold=2)
        breaker.on_failure("Err 1", "tool_a", "s1", AutonomyLevel.L4_CONDITIONAL)
        breaker.on_success()
        assert breaker.consecutive_failures == 0

        # Next failure is only 1 consecutive, so does not trip
        event = breaker.on_failure("Err 2", "tool_a", "s1", AutonomyLevel.L4_CONDITIONAL)
        assert event is None
        assert breaker.state == BreakerState.CLOSED

    def test_manual_trip_and_cooldown_to_half_open(self) -> None:
        breaker = AutonomyCircuitBreaker(cooldown_seconds=0.1)
        event = breaker.trip_manually(
            reason="Direct escape detected",
            error_msg="Unauthorized path access",
            tool_name="fs_write",
            session_id="s1",
            current_level=AutonomyLevel.L4_CONDITIONAL,
        )
        assert breaker.state == BreakerState.OPEN
        assert event.previous_level == AutonomyLevel.L4_CONDITIONAL

        # Wait for cooldown
        time.sleep(0.15)
        # Breaker should now automatically evaluate to HALF_OPEN
        assert breaker.state == BreakerState.HALF_OPEN

    def test_half_open_healing_with_consecutive_successes(self) -> None:
        breaker = AutonomyCircuitBreaker(recovery_threshold=3)
        breaker.trip_manually("trip", "err", "tool", "s1", AutonomyLevel.L4_CONDITIONAL)
        breaker.manual_reset(to_half_open=True)
        assert breaker.state == BreakerState.HALF_OPEN

        assert not breaker.on_success()  # 1/3
        assert not breaker.on_success()  # 2/3
        healed = breaker.on_success()  # 3/3 -> transitions to CLOSED
        assert healed
        assert breaker.state == BreakerState.CLOSED

    def test_half_open_failure_immediately_retrips(self) -> None:
        breaker = AutonomyCircuitBreaker(recovery_threshold=3)
        breaker.manual_reset(to_half_open=True)
        assert breaker.state == BreakerState.HALF_OPEN

        event = breaker.on_failure("probe failed", "tool", "s1", AutonomyLevel.L4_CONDITIONAL)
        assert event is not None
        assert breaker.state == BreakerState.OPEN
        assert "Failure during trial probe in HALF_OPEN" in event.reason


class TestAutonomyExecutionInterceptor:
    """Tests the unified session execution interceptor."""

    def test_permission_gates_by_level(self) -> None:
        interceptor = AutonomyExecutionInterceptor(session_id="s1", initial_level=AutonomyLevel.L1_ADVISOR)
        # L1 allows read, rejects write
        can_exec, _ = interceptor.check_permission("read_file", is_write=False)
        assert can_exec
        can_exec, _ = interceptor.check_permission("write_file", is_write=True)
        assert not can_exec

        # L2 allows read, rejects write (requires manual approval)
        interceptor.set_level(AutonomyLevel.L2_COLLABORATOR)
        can_exec, _ = interceptor.check_permission("read_file", is_write=False)
        assert can_exec
        can_exec, _ = interceptor.check_permission("write_file", is_write=True)
        assert not can_exec

        # L4 allows both
        interceptor.set_level(AutonomyLevel.L4_CONDITIONAL)
        can_exec, _ = interceptor.check_permission("read_file", is_write=False)
        assert can_exec
        can_exec, _ = interceptor.check_permission("write_file", is_write=True)
        assert can_exec

    def test_breaker_trip_forces_downgrade_and_blocks_write(self) -> None:
        interceptor = AutonomyExecutionInterceptor(session_id="s1", initial_level=AutonomyLevel.L4_CONDITIONAL)
        assert interceptor.effective_level == AutonomyLevel.L4_CONDITIONAL

        # 2 consecutive failures
        interceptor.record_result("tool_x", is_write=True, is_success=False, error_msg="Error 1")
        event = interceptor.record_result("tool_x", is_write=True, is_success=False, error_msg="Error 2")

        assert event is not None
        assert interceptor.breaker_state == BreakerState.OPEN
        assert interceptor.effective_level == AutonomyLevel.L2_COLLABORATOR

        # When breaker is open, silent write execution is blocked
        can_exec, reason = interceptor.check_permission("write_file", is_write=True)
        assert not can_exec
        assert "circuit breaker is OPEN" in reason

        # User manual recovery restores configured level
        interceptor.manual_recover(restore_configured_level=True)
        assert interceptor.breaker_state == BreakerState.HALF_OPEN
        assert interceptor.effective_level == AutonomyLevel.L4_CONDITIONAL

    def test_organization_ceiling_capping(self) -> None:
        # Organization ceiling capped at L3
        interceptor = AutonomyExecutionInterceptor(
            session_id="s1",
            initial_level=AutonomyLevel.L2_COLLABORATOR,
            max_allowed_level=AutonomyLevel.L3_SUPERVISOR,
        )

        # Seed calculator for promotion
        for _ in range(16):
            interceptor.record_result("read", is_write=False, is_success=True)
        for _ in range(8):
            interceptor.record_result("write", is_write=True, is_success=True)

        res = interceptor.evaluate_promotion()
        # Normal gate would recommend L4, but ceiling caps it
        assert not res.eligible
        assert "capped by organization ceiling" in res.reason

    def test_telemetry_snapshot(self) -> None:
        interceptor = AutonomyExecutionInterceptor(session_id="s1", initial_level=AutonomyLevel.L2_COLLABORATOR)
        interceptor.record_result("tool_read", is_write=False, is_success=True)
        interceptor.record_result("tool_write", is_write=True, is_success=True)

        snap = interceptor.get_telemetry_snapshot()
        assert snap["sessionId"] == "s1"
        assert snap["configuredLevel"] == 2
        assert snap["effectiveLevel"] == 2
        metrics = snap["metrics"]
        assert isinstance(metrics, dict)
        assert metrics["total"] == 2
        assert metrics["successes"] == 2

    def test_security_violation_immediate_trip(self) -> None:
        interceptor = AutonomyExecutionInterceptor(session_id="s1", initial_level=AutonomyLevel.L4_CONDITIONAL)
        event = interceptor.record_result(
            tool_name="shell_exec",
            is_write=True,
            is_success=False,
            error_msg="Unauthorized root escape",
            is_violation=True,
        )
        assert event is not None
        assert event.breaker_state == BreakerState.OPEN
        assert "Security policy violation detected" in event.reason
        assert interceptor.effective_level == AutonomyLevel.L2_COLLABORATOR

    def test_manual_set_level_resets_breaker(self) -> None:
        interceptor = AutonomyExecutionInterceptor(session_id="s1", initial_level=AutonomyLevel.L4_CONDITIONAL)
        interceptor.record_result("tool", is_write=True, is_success=False, is_violation=True)
        assert interceptor.breaker_state == BreakerState.OPEN

        # User manually sets level back to L3
        interceptor.set_level(AutonomyLevel.L3_SUPERVISOR)
        assert interceptor.configured_level == AutonomyLevel.L3_SUPERVISOR
        assert interceptor.effective_level == AutonomyLevel.L3_SUPERVISOR
        assert interceptor.breaker_state == BreakerState.CLOSED



class TestConcurrencySafety:
    """Verifies thread-safety under heavy concurrent execution recording."""

    def test_concurrent_recording(self) -> None:
        interceptor = AutonomyExecutionInterceptor(session_id="s-concurrent", initial_level=AutonomyLevel.L4_CONDITIONAL)
        num_threads = 8
        invocations_per_thread = 50

        def _worker(thread_id: int) -> None:
            for i in range(invocations_per_thread):
                is_write = (i % 2 == 0)
                interceptor.record_result(
                    tool_name=f"tool_{thread_id}",
                    is_write=is_write,
                    is_success=True,
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(_worker, tid) for tid in range(num_threads)]
            concurrent.futures.wait(futures)

        metrics = interceptor.get_telemetry_snapshot()["metrics"]
        assert isinstance(metrics, dict)
        # Ring buffer capacity is 50, so total invocations in window is capped at 50
        assert metrics["total"] == 50
        assert metrics["successes"] == 50
        assert metrics["fails"] == 0
        assert metrics["successRate"] == 1.0
