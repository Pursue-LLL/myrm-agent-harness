"""Coordinator orchestrating session sweeps according to auto-archive policy.

[INPUT]
- auto_archive_types: ArchiveEligibilityVerdict, ArchiveEvaluationResult,
  ArchiveSweepSummary, ChatSessionMetadata.
- archive_policy_evaluator: ArchivePolicyEvaluator.

[OUTPUT]
- ArchiveSweepCoordinator: Coordinates candidate evaluation and audit generation.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.auto_archive
- Module: archive_sweep_coordinator.py
"""

import time
from collections import Counter
from typing import Callable, List, Optional, Sequence, Tuple

from myrm_agent_harness.agent.context_management.auto_archive.archive_policy_evaluator import (
    ArchivePolicyEvaluator,
)
from myrm_agent_harness.agent.context_management.auto_archive.auto_archive_types import (
    ArchiveEligibilityVerdict,
    ArchiveEvaluationResult,
    ArchiveSweepSummary,
    ChatSessionMetadata,
)


class ArchiveSweepCoordinator:
    """Orchestrates candidate batch filtering, execution callback, and audit telemetry."""

    def __init__(self, evaluator: ArchivePolicyEvaluator) -> None:
        self._evaluator = evaluator

    @property
    def evaluator(self) -> ArchivePolicyEvaluator:
        """Returns the underlying policy evaluator."""
        return self._evaluator

    def run_sweep(
        self,
        sessions: Sequence[ChatSessionMetadata],
        now_timestamp: Optional[float] = None,
        archive_action: Optional[Callable[[str], bool]] = None,
    ) -> Tuple[ArchiveSweepSummary, Tuple[ArchiveEvaluationResult, ...]]:
        """Executes a sweep over candidate sessions, evaluating and optionally archiving them.

        Args:
            sessions: Collection of session metadata snapshots.
            now_timestamp: Explicit reference epoch time (defaults to time.time()).
            archive_action: Optional callback performing persistent archive transition.
                Returns True if archive operation succeeded, False otherwise.

        Returns:
            Tuple of (ArchiveSweepSummary, tuple of all evaluation results).
        """
        start_time = time.perf_counter()
        reference_now = now_timestamp if now_timestamp is not None else time.time()

        results: List[ArchiveEvaluationResult] = []
        eligible_sessions: List[str] = []
        exemption_counts: Counter[str] = Counter()

        for session in sessions:
            res = self._evaluator.evaluate_session(session, reference_now)
            results.append(res)

            if res.verdict == ArchiveEligibilityVerdict.ELIGIBLE:
                eligible_sessions.append(res.chat_id)
            else:
                exemption_counts[res.reason.value] += 1

        archived_count = 0
        if archive_action is not None and eligible_sessions:
            for chat_id in eligible_sessions:
                try:
                    if archive_action(chat_id):
                        archived_count += 1
                except Exception:
                    # Individual execution failures are tracked via archived_count disparity
                    pass
        else:
            archived_count = len(eligible_sessions)

        elapsed = time.perf_counter() - start_time
        breakdown: Tuple[Tuple[str, int], ...] = tuple(sorted(exemption_counts.items()))

        summary = ArchiveSweepSummary(
            total_scanned=len(sessions),
            eligible_count=len(eligible_sessions),
            archived_count=archived_count,
            exempt_breakdown=breakdown,
            elapsed_seconds=elapsed,
        )

        return summary, tuple(results)
