import threading
import time

from .types import (
    ActionEvaluationVerdictEnum,
    ConsumerActionEvaluationResult,
    ConsumerActionTypeEnum,
    ConsumerGuardPolicy,
)


class ActionVelocityLimiter:
    """Sliding-window velocity and burst rate limiter preventing runaway loop execution."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Key: (agent_id, action_type.value) -> list of execution epoch timestamps
        self._history: dict[tuple[str, str], list[float]] = {}

    def check_velocity(
        self,
        agent_id: str,
        action_type: ConsumerActionTypeEnum,
        policy: ConsumerGuardPolicy,
        current_time: float | None = None,
    ) -> ConsumerActionEvaluationResult | None:
        """Check if action rate exceeds velocity window threshold."""
        now = current_time if current_time is not None else time.time()
        window_start = now - policy.velocity_window_seconds
        key = (agent_id, action_type.value)

        with self._lock:
            timestamps = self._history.get(key, [])
            valid_timestamps = [ts for ts in timestamps if ts >= window_start]
            self._history[key] = valid_timestamps

            if len(valid_timestamps) >= policy.max_actions_per_window:
                minutes_window = policy.velocity_window_seconds / 60.0
                return ConsumerActionEvaluationResult(
                    is_allowed=False,
                    verdict=ActionEvaluationVerdictEnum.VELOCITY_RATE_LIMITED,
                    message=(
                        f"Action '{action_type.value}' velocity limit exceeded: "
                        f"{len(valid_timestamps)} action(s) within {minutes_window:.1f} minutes window. "
                        f"Max allowed is {policy.max_actions_per_window}."
                    ),
                    requires_hitl=False,
                )

        return None

    def record_action(
        self,
        agent_id: str,
        action_type: ConsumerActionTypeEnum,
        current_time: float | None = None,
    ) -> None:
        """Record an executed action timestamp into the sliding window bucket."""
        now = current_time if current_time is not None else time.time()
        key = (agent_id, action_type.value)
        with self._lock:
            if key not in self._history:
                self._history[key] = []
            self._history[key].append(now)

    def reset(self, agent_id: str | None = None) -> None:
        """Reset velocity history for an agent or all agents."""
        with self._lock:
            if agent_id is None:
                self._history.clear()
            else:
                keys_to_remove = [k for k in self._history if k[0] == agent_id]
                for k in keys_to_remove:
                    del self._history[k]
