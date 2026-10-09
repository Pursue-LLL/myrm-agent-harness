"""Single-retry guard latch preventing infinite summary context overflow retry loops.

[INPUT]
- overflow_clip_types: OverflowClipOutcome, SummaryOverflowClipConfig, SummaryRetryVerdict.

[OUTPUT]
- OverflowRetryGuard: Enforces single-retry limits and strictly monotonic token reduction
  checks before allowing an auxiliary summarization LLM call retry.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.summary_overflow_clip
- Module: overflow_retry_guard.py
"""

from typing import Dict

from myrm_agent_harness.agent.context_management.summary_overflow_clip.overflow_clip_types import (
    OverflowClipOutcome,
    SummaryOverflowClipConfig,
    SummaryRetryVerdict,
)


class OverflowRetryGuard:
    """Guards against runaway retry loops when summary model calls encounter context overflow."""

    def __init__(self, config: SummaryOverflowClipConfig) -> None:
        self._config = config
        self._retry_counts: Dict[str, int] = {}

    def evaluate_retry_eligibility(
        self,
        session_id: str,
        clip_outcome: OverflowClipOutcome,
    ) -> SummaryRetryVerdict:
        """Determines whether a clipped request may be retried exactly once.

        Args:
            session_id: Target session identifier.
            clip_outcome: Result of tail clipping performed by TailMessageClipper.

        Returns:
            SummaryRetryVerdict signaling permission or exhaustion reasons.
        """
        current_attempts = self._retry_counts.get(session_id, 0)

        # 1. Enforce strict single-retry ceiling
        if current_attempts >= self._config.max_summary_retries:
            return SummaryRetryVerdict.RETRY_EXHAUSTED

        # 2. Check for genuine monotonic reduction
        if not clip_outcome.is_strictly_reduced or clip_outcome.total_tokens_saved <= 0:
            return SummaryRetryVerdict.IRREDUCIBLE_OVERFLOW

        # 3. Latch and grant exactly one retry
        self._retry_counts[session_id] = current_attempts + 1
        return SummaryRetryVerdict.PERMITTED_ONCE

    def get_attempt_count(self, session_id: str) -> int:
        """Returns the number of retry attempts used for the given session."""
        return self._retry_counts.get(session_id, 0)

    def reset_session_retry_state(self, session_id: str) -> None:
        """Clears retry counters for a successfully resolved or terminated session turn."""
        self._retry_counts.pop(session_id, None)
