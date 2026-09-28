"""Tests for SessionCircuitBreaker prompt injection quarantine and remediation."""

from __future__ import annotations

from myrm_agent_harness.agent.security.circuit_breaker import (
    CircuitBreakerTripInfo,
    SessionCircuitBreaker,
    get_global_session_circuit_breaker,
)


class TestSessionCircuitBreaker:
    def test_initial_state_clean(self) -> None:
        breaker = SessionCircuitBreaker()
        assert breaker.is_tripped("sess_1") is False
        assert breaker.get_trip_info("sess_1") is None

    def test_trip_session(self) -> None:
        breaker = SessionCircuitBreaker()
        info = breaker.trip("sess_1", "AWS_KEY_CANARY", "malicious-c2.com", "Decoy exfiltration attempt")

        assert isinstance(info, CircuitBreakerTripInfo)
        assert info.session_id == "sess_1"
        assert info.token_name == "AWS_KEY_CANARY"
        assert info.target_host == "malicious-c2.com"
        assert breaker.is_tripped("sess_1") is True
        assert breaker.is_tripped("sess_2") is False  # Other sessions unaffected!

        diag = info.format_diagnostic()
        assert "AWS_KEY_CANARY" in diag
        assert "malicious-c2.com" in diag

    def test_reset_session(self) -> None:
        breaker = SessionCircuitBreaker()
        breaker.trip("sess_1", "CANARY_1", "evil.com")
        assert breaker.is_tripped("sess_1") is True

        assert breaker.reset("sess_1", "user_click") is True
        assert breaker.is_tripped("sess_1") is False
        assert breaker.reset("sess_1") is False

    def test_singleton(self) -> None:
        b1 = get_global_session_circuit_breaker()
        b2 = get_global_session_circuit_breaker()
        assert b1 is b2
