"""Adaptive exponential backoff state machine for self-paced loop pacing.

[INPUT]
- Current delay, consecutive unchanged counter, previous fingerprint, and new response text

[OUTPUT]
- BackoffDecision: next_delay, updated consecutive_unchanged, change and alert flags

[POS]
Harness runtime layer. Enforces Occam's razor: low-token idle pacing with
instantaneous floor snapping upon state changes or critical errors.
"""

from __future__ import annotations

from dataclasses import dataclass

from .fingerprint import extract_semantic_fingerprint, has_alert_anomaly
from .types import (
    DEFAULT_SELF_PACED_CEILING_SECONDS,
    DEFAULT_SELF_PACED_FLOOR_SECONDS,
)


@dataclass(frozen=True)
class BackoffDecision:
    """Outcome of an adaptive backoff evaluation."""

    next_delay: float
    consecutive_unchanged: int
    is_changed: bool
    is_alert: bool
    current_digest: str


class AdaptiveBackoffCalculator:
    """Calculates subsequent wait delay based on semantic change detection."""

    def __init__(
        self,
        floor_seconds: float = float(DEFAULT_SELF_PACED_FLOOR_SECONDS),
        ceiling_seconds: float = float(DEFAULT_SELF_PACED_CEILING_SECONDS),
        multiplier: float = 2.0,
    ) -> None:
        self.floor_seconds = max(5.0, floor_seconds)
        self.ceiling_seconds = max(self.floor_seconds, ceiling_seconds)
        self.multiplier = max(1.1, multiplier)

    def evaluate(
        self,
        new_response: str,
        *,
        previous_digest: str,
        current_delay: float,
        consecutive_unchanged: int,
    ) -> BackoffDecision:
        """Evaluate response against previous digest to compute next delay."""
        new_digest = extract_semantic_fingerprint(new_response)
        is_alert = has_alert_anomaly(new_response)

        # Critical alert bypass: immediately snap back to floor
        if is_alert:
            return BackoffDecision(
                next_delay=self.floor_seconds,
                consecutive_unchanged=0,
                is_changed=True,
                is_alert=True,
                current_digest=new_digest,
            )

        # First evaluation or state changed
        if not previous_digest or new_digest != previous_digest:
            return BackoffDecision(
                next_delay=self.floor_seconds,
                consecutive_unchanged=0,
                is_changed=True,
                is_alert=False,
                current_digest=new_digest,
            )

        # Response content unchanged: back off exponentially
        updated_unchanged = consecutive_unchanged + 1
        effective_delay = current_delay if current_delay > 0 else self.floor_seconds
        next_delay = min(self.ceiling_seconds, effective_delay * self.multiplier)

        return BackoffDecision(
            next_delay=next_delay,
            consecutive_unchanged=updated_unchanged,
            is_changed=False,
            is_alert=False,
            current_digest=new_digest,
        )
