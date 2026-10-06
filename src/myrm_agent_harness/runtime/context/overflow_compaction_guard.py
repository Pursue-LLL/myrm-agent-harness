"""One-recovery-per-conversational-input overflow compaction guard.

Implements the Pi Harness v2 overflow loop-bounding specification:
1. is_recoverable_length:
   Distinguishes genuine output-cap stops from context-pressure truncation.
2. One recovery per conversational input:
   An overflow-reason compaction is strictly permitted at most ONCE per
   conversational input window (prompt, steering, follow-up).
3. Fail-Closed Give-Up:
   A second recoverable overflow inside the same input window terminates
   the run with an explicit give-up error, preventing infinite compact-and-retry loops.

[INPUT]
- stop_reason: str | None
- output_tokens: int
- desired_max_output: int
- conversational_input_id: str

[OUTPUT]
- OverflowClassification
- OverflowRecoveryDecision
- OverflowCompactionExhaustedGiveUpError
- is_recoverable_length
- classify_response_overflow
- OverflowCompactionOnePerInputGuard

[POS]
Harness runtime context layer. Bounds the compact-and-retry loop at one attempt
per user action, preventing infinite compaction token burn.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from enum import StrEnum

OVERFLOW_ERROR_PATTERNS = (
    re.compile(r"context_length_exceeded", re.IGNORECASE),
    re.compile(r"maximum context length", re.IGNORECASE),
    re.compile(r"prompt is too long", re.IGNORECASE),
    re.compile(r"token limit exceeded", re.IGNORECASE),
    re.compile(r"too many tokens", re.IGNORECASE),
)


class OverflowClassification(StrEnum):
    """Classification of model responses regarding context overflow and truncation."""

    NORMAL = "normal"
    GENUINE_OUTPUT_CAP = "genuine_output_cap"
    RECOVERABLE_OVERFLOW = "recoverable_overflow"


class OverflowCompactionExhaustedGiveUpError(Exception):
    """Raised when context overflow persists after the single permitted compaction per input."""

    def __init__(self, session_id: str, input_id: str, message: str) -> None:
        super().__init__(f"[{session_id}][input={input_id}] Overflow compaction exhausted: {message}")
        self.session_id = session_id
        self.input_id = input_id


@dataclass(slots=True, frozen=True)
class OverflowRecoveryDecision:
    """Decision evaluated by the overflow compaction guard."""

    should_compact: bool
    give_up: bool
    classification: OverflowClassification
    input_id: str
    attempt_count: int
    reason: str


def is_recoverable_length(
    stop_reason: str | None,
    output_tokens: int,
    desired_max_output: int,
) -> bool:
    """Evaluate whether a 'length' stop is recoverable via context compaction.

    A genuine output-limit stop occurs when actual output reached the caller's
    intended output cap (desired_max_output). Compacting context cannot help.
    Stopping below the intended cap signals context pressure or provider-side
    clamping, which is recoverable through context compaction.
    """
    if stop_reason not in ("length", "max_tokens"):
        return False
    return desired_max_output <= 0 or output_tokens < desired_max_output


def classify_response_overflow(
    stop_reason: str | None,
    output_tokens: int,
    desired_max_output: int,
    *,
    is_explicit_error: bool = False,
    error_message: str = "",
) -> OverflowClassification:
    """Classify model outcome into normal, genuine output cap, or recoverable overflow."""
    if is_explicit_error:
        for pat in OVERFLOW_ERROR_PATTERNS:
            if pat.search(error_message):
                return OverflowClassification.RECOVERABLE_OVERFLOW
        # If error was an explicit 400 or context message
        if "400" in error_message and "token" in error_message.lower():
            return OverflowClassification.RECOVERABLE_OVERFLOW

    if stop_reason in ("length", "max_tokens"):
        if is_recoverable_length(stop_reason, output_tokens, desired_max_output):
            return OverflowClassification.RECOVERABLE_OVERFLOW
        return OverflowClassification.GENUINE_OUTPUT_CAP

    return OverflowClassification.NORMAL


class OverflowCompactionOnePerInputGuard:
    """Thread-safe state machine bounding overflow compaction to 1 attempt per input."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._lock = threading.Lock()
        self._current_input_id: str = "initial"
        self._overflow_compaction_count: int = 0

    def on_conversational_input_consumed(self, input_id: str) -> None:
        """Reset overflow compaction counter when a fresh user action is consumed."""
        with self._lock:
            self._current_input_id = input_id
            self._overflow_compaction_count = 0

    def evaluate_recovery(
        self,
        classification: OverflowClassification,
    ) -> OverflowRecoveryDecision:
        """Evaluate whether compaction is permitted or give-up error must be raised."""
        with self._lock:
            cur_input = self._current_input_id

            if classification != OverflowClassification.RECOVERABLE_OVERFLOW:
                return OverflowRecoveryDecision(
                    should_compact=False,
                    give_up=False,
                    classification=classification,
                    input_id=cur_input,
                    attempt_count=self._overflow_compaction_count,
                    reason=f"Classification is {classification.value}; no overflow recovery required.",
                )

            if self._overflow_compaction_count == 0:
                self._overflow_compaction_count = 1
                return OverflowRecoveryDecision(
                    should_compact=True,
                    give_up=False,
                    classification=classification,
                    input_id=cur_input,
                    attempt_count=1,
                    reason="First recoverable overflow for this conversational input; triggering single allowed compaction.",
                )

            # Second recoverable overflow inside the same input window -> Give up
            return OverflowRecoveryDecision(
                should_compact=False,
                give_up=True,
                classification=classification,
                input_id=cur_input,
                attempt_count=self._overflow_compaction_count + 1,
                reason="Second recoverable overflow within the same conversational input window; give-up error triggered to bound compaction loop.",
            )

    def check_and_enforce(
        self,
        classification: OverflowClassification,
    ) -> bool:
        """Evaluate decision and raise OverflowCompactionExhaustedGiveUpError on give-up."""
        decision = self.evaluate_recovery(classification)
        if decision.give_up:
            raise OverflowCompactionExhaustedGiveUpError(
                session_id=self.session_id,
                input_id=decision.input_id,
                message=decision.reason,
            )
        return decision.should_compact

    @property
    def current_input_id(self) -> str:
        """Identifier of currently active input window."""
        with self._lock:
            return self._current_input_id

    @property
    def overflow_compaction_count(self) -> int:
        """Number of overflow compactions performed in the current input window."""
        with self._lock:
            return self._overflow_compaction_count
