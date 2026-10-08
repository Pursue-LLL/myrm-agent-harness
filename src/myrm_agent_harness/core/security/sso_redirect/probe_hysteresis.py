"""Probe Hysteresis Evaluator for Network Probes and Session Keepalive.

[INPUT]
- Success/Failure probe signals, failure threshold configurations.

[OUTPUT]
- ProbeEvaluationResult with stable hysteresis states (prevents UI flicker).

[POS]
- Harness core security engine for IHUI-AI #2728e745 probe hysteresis against UI toggling.
"""

from __future__ import annotations

from .types import (
    ProbeEvaluationResult,
    ProbeHysteresisState,
)


class ProbeHysteresisController:
    """Manages hysteresis for connection and health probes to prevent jitter."""

    def __init__(
        self,
        offline_failure_threshold: int = 3,
        degraded_failure_threshold: int = 1,
    ) -> None:
        if offline_failure_threshold < 1:
            raise ValueError("offline_failure_threshold must be >= 1")
        self._offline_threshold = offline_failure_threshold
        self._degraded_threshold = min(
            degraded_failure_threshold, offline_failure_threshold
        )

        self._state = ProbeHysteresisState.ONLINE
        self._consecutive_failures = 0
        self._consecutive_successes = 0

    @property
    def current_state(self) -> ProbeHysteresisState:
        """Current hysteresis state."""
        return self._state

    def record_probe_result(self, is_success: bool) -> ProbeEvaluationResult:
        """Record a single probe outcome and evaluate the hysteresis transition."""
        prev_state = self._state

        if is_success:
            self._consecutive_successes += 1
            self._consecutive_failures = 0
            # Single success immediately restores to ONLINE state
            new_state = ProbeHysteresisState.ONLINE
            recommended_action = "none"
        else:
            self._consecutive_failures += 1
            self._consecutive_successes = 0

            if self._consecutive_failures >= self._offline_threshold:
                new_state = ProbeHysteresisState.OFFLINE
                recommended_action = "switch_to_offline_fallback"
            elif self._consecutive_failures >= self._degraded_threshold:
                new_state = ProbeHysteresisState.DEGRADED
                recommended_action = "retry_probe"
            else:
                new_state = prev_state
                recommended_action = "observe"

        state_changed = new_state != prev_state
        self._state = new_state

        return ProbeEvaluationResult(
            previous_state=prev_state,
            new_state=new_state,
            consecutive_failures=self._consecutive_failures,
            consecutive_successes=self._consecutive_successes,
            state_changed=state_changed,
            recommended_action=recommended_action,
        )

    def reset(self) -> None:
        """Reset hysteresis state back to clean online baseline."""
        self._state = ProbeHysteresisState.ONLINE
        self._consecutive_failures = 0
        self._consecutive_successes = 0
