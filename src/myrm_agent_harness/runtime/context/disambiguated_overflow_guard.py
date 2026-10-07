"""Disambiguated length overflow detector and single-recovery conversational guard.

Differentiates between benign max_output_tokens exhaustion and genuine context
window overflows, while enforcing a strict one-recovery-per-conversational-input bound
to permanently eliminate infinite compaction loops.
"""

from __future__ import annotations

from collections.abc import Mapping

from .tail_deferred_overflow_types import (
    DisambiguationMetrics,
    RecoveryVerdict,
    StopReasonVerdict,
)


class LengthOverflowDisambiguator:
    """Disambiguates model stop/finish reasons using token budget telemetry."""

    @staticmethod
    def disambiguate(
        finish_reason: str | None,
        metrics: DisambiguationMetrics,
    ) -> StopReasonVerdict:
        """Classify the finish reason based on token measurements."""
        normalized = (finish_reason or "").strip().lower()

        if normalized in {"stop", "end_turn", ""}:
            return StopReasonVerdict.NORMAL_STOP
        if normalized in {"tool_calls", "tool_use", "function_call"}:
            return StopReasonVerdict.TOOL_USE
        if normalized in {"content_filter", "safety"}:
            return StopReasonVerdict.CONTENT_FILTER

        if normalized in {"length", "max_tokens"}:
            # Total tokens consumed so far (prompt + generated output)
            total_tokens = metrics.prompt_tokens + metrics.actual_output_tokens
            # Remaining headroom inside the model's physical window
            physical_window_headroom = metrics.model_context_limit - total_tokens
            # Gap between requested generation budget and actual generated tokens
            output_budget_gap = (
                metrics.max_output_tokens_budget - metrics.actual_output_tokens
            )

            # Case A: Actual output is at or within tolerance of max output budget,
            # and there was sufficient physical window remaining.
            # -> This is purely a configured output cap hit. Do NOT compact context!
            if (
                output_budget_gap <= metrics.output_token_tolerance
                and physical_window_headroom > 0
            ):
                return StopReasonVerdict.MAX_OUTPUT_TOKENS_REACHED

            # Case B: Physical context limit was breached or output was cut short
            # prematurely before hitting the generation budget.
            # -> This is a genuine context window overflow.
            return StopReasonVerdict.CONTEXT_WINDOW_OVERFLOW

        return StopReasonVerdict.UNKNOWN


class ConversationalRecoveryGuard:
    """Enforces the 'One recovery per conversational input' safety invariant."""

    def __init__(self, max_recoveries_per_input: int = 1) -> None:
        self._max_recoveries = max_recoveries_per_input
        self._recovery_counts: dict[str, int] = {}
        self._active_input_id: str | None = None

    def begin_conversational_cycle(self, input_id: str) -> None:
        """Register the start of a new conversational input turn."""
        self._active_input_id = input_id
        if input_id not in self._recovery_counts:
            self._recovery_counts[input_id] = 0

    def check_and_acquire_recovery(
        self,
        input_id: str | None = None,
    ) -> RecoveryVerdict:
        """Evaluate if an overflow recovery attempt is permitted for this input cycle."""
        target_id = input_id or self._active_input_id or "default_input"
        current_attempts = self._recovery_counts.get(target_id, 0)

        if current_attempts >= self._max_recoveries:
            return RecoveryVerdict(
                can_recover=False,
                input_id=target_id,
                recovery_attempts=current_attempts,
                reason=(
                    f"Maximum recovery attempts ({self._max_recoveries}) exhausted for input "
                    f"'{target_id}'. Circuit breaker engaged to prevent infinite compaction loop."
                ),
            )

        self._recovery_counts[target_id] = current_attempts + 1
        return RecoveryVerdict(
            can_recover=True,
            input_id=target_id,
            recovery_attempts=current_attempts + 1,
            reason="Recovery granted for input cycle.",
        )

    def get_recovery_count(self, input_id: str) -> int:
        """Return the number of recoveries consumed for the given input cycle."""
        return self._recovery_counts.get(input_id, 0)

    def export_telemetry(self) -> Mapping[str, int]:
        """Export snapshot of recovery counts across all input cycles."""
        return dict(self._recovery_counts)

    def reset(self) -> None:
        """Reset all recovery counts and active state."""
        self._recovery_counts.clear()
        self._active_input_id = None
