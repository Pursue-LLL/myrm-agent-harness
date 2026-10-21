"""Unit tests for Tool-Level Circuit Breaker and Graceful Fallback Firewall Suite."""

from __future__ import annotations

import asyncio
import time

import pytest

from myrm_agent_harness.runtime.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitState,
    ErrorCategory,
    ErrorClassifier,
    GracefulFallbackFirewall,
    ToolCircuitBreaker,
)


def test_error_classifier_boundaries() -> None:
    """Verify error classification strictly separates transient network faults from fatal errors."""
    # 1. Transient Retryable Faults
    assert ErrorClassifier.classify(TimeoutError("Socket read timeout")) == ErrorCategory.RETRYABLE_TRANSIENT
    assert ErrorClassifier.classify(ConnectionResetError("Peer reset connection")) == ErrorCategory.RETRYABLE_TRANSIENT
    assert ErrorClassifier.classify(RuntimeError("HTTP 429 Too Many Requests: rate limited")) == ErrorCategory.RETRYABLE_TRANSIENT
    assert ErrorClassifier.classify(RuntimeError("503 Service Unavailable")) == ErrorCategory.RETRYABLE_TRANSIENT

    # 2. Fatal Non-Retryable Faults
    assert ErrorClassifier.classify(ValueError("Invalid argument syntax")) == ErrorCategory.NON_RETRYABLE_FATAL
    assert ErrorClassifier.classify(RuntimeError("HTTP 401 Unauthorized: token expired")) == ErrorCategory.NON_RETRYABLE_FATAL
    assert ErrorClassifier.classify(RuntimeError("400 Bad Request: missing param")) == ErrorCategory.NON_RETRYABLE_FATAL
    assert ErrorClassifier.classify(FileNotFoundError("Target binary does not exist")) == ErrorCategory.NON_RETRYABLE_FATAL


@pytest.mark.asyncio
async def test_fatal_error_aborts_retries_immediately() -> None:
    """Verify fatal errors trigger immediate Fail-Fast without generating retry storms."""
    config = CircuitBreakerConfig(max_retries=3)
    breaker = ToolCircuitBreaker("test_api", config)
    call_count = 0

    def mock_fatal_tool() -> str:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("HTTP 401 Unauthorized")

    outcome = await breaker.execute_with_resilience(
        mock_fatal_tool,
        fallback_fn=lambda: "fallback",
    )

    # Invariant: Must fail fast with 0 retries attempted
    assert outcome.success is False
    assert outcome.retries_attempted == 0
    assert call_count == 1
    assert "Fatal error" in outcome.error_msg


@pytest.mark.asyncio
async def test_circuit_breaker_tripping_to_open_and_fast_fallback() -> None:
    """Verify circuit breaker trips to OPEN upon threshold failures and executes 0ms fallback."""
    config = CircuitBreakerConfig(failure_threshold=2, max_retries=0, recovery_timeout_s=10.0)
    breaker = ToolCircuitBreaker("search_engine", config)

    def failing_tool() -> str:
        raise TimeoutError("Simulated upstream gateway timeout")

    # Call 1: fails
    await breaker.execute_with_resilience(failing_tool, fallback_fn=lambda: "fallback_1")
    assert breaker.state == CircuitState.CLOSED

    # Call 2: fails -> trips circuit to OPEN
    await breaker.execute_with_resilience(failing_tool, fallback_fn=lambda: "fallback_2")
    assert breaker.state == CircuitState.OPEN

    # Call 3: OPEN state must short-circuit in 0ms without invoking failing_tool
    invoked = False

    def monitored_tool() -> str:
        nonlocal invoked
        invoked = True
        return "ok"

    t0 = time.time()
    outcome_3 = await breaker.execute_with_resilience(
        monitored_tool,
        fallback_fn=lambda: "graceful_cached_knowledge",
    )
    elapsed = time.time() - t0

    assert outcome_3.is_fallback is True
    assert outcome_3.return_value == "graceful_cached_knowledge"
    assert outcome_3.circuit_state == CircuitState.OPEN
    assert invoked is False  # Protected tool never touched
    assert elapsed < 0.05  # Instantaneous intercept


@pytest.mark.asyncio
async def test_circuit_half_open_probe_and_recovery() -> None:
    """Verify circuit transitions to HALF_OPEN after cooldown and recovers to CLOSED on success."""
    config = CircuitBreakerConfig(
        failure_threshold=1,
        max_retries=0,
        recovery_timeout_s=0.05,  # Short cooldown for test
    )
    breaker = ToolCircuitBreaker("weather_api", config)

    # Trip to OPEN
    await breaker.execute_with_resilience(
        lambda: (_ for _ in ()).throw(TimeoutError("Drop")),
        fallback_fn=lambda: "fb",
    )
    assert breaker.state == CircuitState.OPEN

    # Wait for cooldown to expire
    await asyncio.sleep(0.08)
    assert breaker.state == CircuitState.HALF_OPEN

    # Probe call succeeds
    probe_outcome = await breaker.execute_with_resilience(
        lambda: "Sunny 25C",
        fallback_fn=lambda: "fb",
    )

    assert probe_outcome.success is True
    assert probe_outcome.return_value == "Sunny 25C"
    # Successful probe restores circuit back to CLOSED
    assert breaker.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_graceful_fallback_firewall_and_markdown() -> None:
    """Verify central firewall manages multiple breakers and renders dashboard markdown."""
    firewall = GracefulFallbackFirewall()

    # 1. Healthy tool execution
    res_ok = await firewall.execute_tool(
        "calculator",
        lambda: "42",
    )
    assert res_ok.success is True
    assert res_ok.return_value == "42"

    # 2. Trip one tool to OPEN
    breaker = firewall.get_or_create_breaker("broken_search")
    breaker.force_state(CircuitState.OPEN)

    # 3. Fire-walled tool call receives semantic JSON fallback
    res_fallback = await firewall.execute_tool(
        "broken_search",
        lambda: "never_called",
    )
    assert res_fallback.is_fallback is True
    assert "TOOL_CIRCUIT_OPEN" in res_fallback.return_value

    # 4. Render Markdown dashboard
    dashboard = firewall.render_firewall_markdown()
    assert "### 🛡️ 工具级自适应熔断器与优雅降级防火墙看板" in dashboard
    assert "broken_search" in dashboard
    assert "> [!WARNING]" in dashboard
    assert "**[熔断报警]**" in dashboard
