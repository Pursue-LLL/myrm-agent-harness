"""Master facade suite for summary call context overflow tail clipping and single retry guard.

[INPUT]
- overflow_clip_types: All contracts, enums, actions, outcomes, and configuration models.
- tail_message_clipper: TailMessageClipper.
- overflow_retry_guard: OverflowRetryGuard.

[OUTPUT]
- SummaryCallOverflowTailClipRetrySuite: Master facade coordinating
  trailing tool message head-slicing, offload stub replacement, and single-retry gating.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.summary_overflow_clip
- Module: summary_overflow_clip_suite.py
"""

from typing import Mapping, Optional, Sequence, Tuple

from myrm_agent_harness.agent.context_management.summary_overflow_clip.overflow_clip_types import (
    OverflowClipOutcome,
    SummaryOverflowClipConfig,
    SummaryRetryVerdict,
)
from myrm_agent_harness.agent.context_management.summary_overflow_clip.overflow_retry_guard import (
    OverflowRetryGuard,
)
from myrm_agent_harness.agent.context_management.summary_overflow_clip.tail_message_clipper import (
    TailMessageClipper,
)


class SummaryCallOverflowTailClipRetrySuite:
    """Master facade mitigating provider context overflow errors during auxiliary summarization calls."""

    def __init__(self, config: Optional[SummaryOverflowClipConfig] = None) -> None:
        self._config = config or SummaryOverflowClipConfig()
        self._clipper = TailMessageClipper(self._config)
        self._guard = OverflowRetryGuard(self._config)

    @property
    def clipper(self) -> TailMessageClipper:
        """Access the trailing message clipper."""
        return self._clipper

    @property
    def guard(self) -> OverflowRetryGuard:
        """Access the single-retry guard."""
        return self._guard

    def handle_summary_context_overflow(
        self,
        session_id: str,
        messages: Sequence[Mapping[str, str]],
    ) -> Tuple[SummaryRetryVerdict, OverflowClipOutcome]:
        """Handles context overflow during summary calls by clipping tail tool results and vetting retries.

        Args:
            session_id: Target session identifier.
            messages: Full message history that overflowed the summarizer context window.

        Returns:
            Tuple containing:
            1. SummaryRetryVerdict (PERMITTED_ONCE, RETRY_EXHAUSTED, or IRREDUCIBLE_OVERFLOW)
            2. OverflowClipOutcome containing shrunk messages and diagnostic stats.
        """
        outcome = self._clipper.clip_trailing_tool_overflow(messages)
        verdict = self._guard.evaluate_retry_eligibility(session_id, outcome)
        return verdict, outcome

    def clip_messages_tail(
        self,
        messages: Sequence[Mapping[str, str]],
    ) -> OverflowClipOutcome:
        """Directly applies tail clipping without consuming retry tokens."""
        return self._clipper.clip_trailing_tool_overflow(messages)

    def reset_session_retry_state(self, session_id: str) -> None:
        """Resets retry state when a session completes or successfully generates a summary."""
        self._guard.reset_session_retry_state(session_id)

    def get_retry_attempts(self, session_id: str) -> int:
        """Returns the number of retry attempts recorded for the session."""
        return self._guard.get_attempt_count(session_id)
