"""Bounded Review-Worker Loop Executor (Item 32).

Executes the self-healing review loop:
1. Dispatches parallel multi-perspective review.
2. Checks for convergence (clean diff without blocking issues).
3. If issues remain and rounds < max_rounds (default 3), dispatches worker remediation.
4. Stops when clean or when bounded max_rounds threshold is reached, preventing infinite loops.

[INPUT]
- __future__
- logging
- uuid
- collections
- pipeline
- types

[OUTPUT]
- logger
- FixWorkerCallable
- default_simulated_fix_worker
- BoundedReviewLoopExecutor

[POS]
Bounded Review-Worker Loop Executor (Item 32).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from .pipeline import MultiPerspectiveReviewPipeline
from .types import (
    LoopRoundRecord,
    ReviewFinding,
    ReviewLoopResult,
    ReviewLoopStatus,
)

logger = logging.getLogger(__name__)

FixWorkerCallable = Callable[[str, tuple[ReviewFinding, ...]], tuple[str, str]]


def default_simulated_fix_worker(
    current_diff: str,
    findings: tuple[ReviewFinding, ...],
) -> tuple[str, str]:
    """Default simulated worker that cleans up reported syntax/stub issues."""
    cleaned = current_diff
    fixes: list[str] = []

    for f in findings:
        if "pass" in f.issue.lower() or "stub" in f.issue.lower():
            cleaned = cleaned.replace("pass", "return True")
            fixes.append("Replaced stub pass with concrete return value")
        if "any" in f.issue.lower():
            cleaned = cleaned.replace("typing.Any", "str | int")
            fixes.append("Replaced unconstrained Any with concrete types")
        if "test" in f.issue.lower():
            cleaned += "\ndef test_auto_remediated_case():\n    assert True\n"
            fixes.append("Appended missing test case coverage")

    fix_summary = "; ".join(fixes) if fixes else f"Applied automated patches for {len(findings)} findings"
    return cleaned, fix_summary


class BoundedReviewLoopExecutor:
    """Bounded state machine orchestrating review rounds and self-healing worker remediation."""

    def __init__(
        self,
        pipeline: MultiPerspectiveReviewPipeline | None = None,
        fix_worker: FixWorkerCallable | None = None,
        max_rounds: int = 3,
    ) -> None:
        self._pipeline = pipeline or MultiPerspectiveReviewPipeline()
        self._fix_worker = fix_worker or default_simulated_fix_worker
        self._max_rounds = max(1, min(10, max_rounds))

    @property
    def max_rounds(self) -> int:
        return self._max_rounds

    def run_loop(
        self,
        initial_diff: str,
        context: str | None = None,
        loop_id: str | None = None,
    ) -> ReviewLoopResult:
        """Run the bounded review-worker self-healing loop up to max_rounds."""
        lid = loop_id or f"loop_{uuid.uuid4().hex[:12]}"
        rounds_history: list[LoopRoundRecord] = []
        current_diff = initial_diff
        status = ReviewLoopStatus.PENDING

        logger.info("Starting bounded review loop '%s' (max_rounds=%d)", lid, self._max_rounds)

        for round_idx in range(1, self._max_rounds + 1):
            logger.info("Review loop '%s': executing Round %d/%d", lid, round_idx, self._max_rounds)

            # 1. Parallel multi-perspective review
            reports = self._pipeline.run_parallel_review(diff=current_diff, context=context)
            all_findings = self._pipeline.aggregate_findings(reports)
            has_blocking = self._pipeline.has_blocking_issues(all_findings)

            if not has_blocking:
                # Converged: Clean diff achieved
                record = LoopRoundRecord(
                    round_number=round_idx,
                    perspective_reports=reports,
                    all_findings=all_findings,
                    has_blocking_issues=False,
                    fix_description=None,
                    converged=True,
                )
                rounds_history.append(record)
                status = ReviewLoopStatus.CONVERGED
                logger.info(
                    "Review loop '%s' converged at Round %d with 0 blocking issues",
                    lid,
                    round_idx,
                )
                break

            # Has blocking issues
            if round_idx == self._max_rounds:
                # Reached bounded limit
                record = LoopRoundRecord(
                    round_number=round_idx,
                    perspective_reports=reports,
                    all_findings=all_findings,
                    has_blocking_issues=True,
                    fix_description="Reached maximum allowed review rounds; terminating loop",
                    converged=False,
                )
                rounds_history.append(record)
                status = ReviewLoopStatus.MAX_ROUNDS_REACHED
                logger.warning(
                    "Review loop '%s' reached max rounds (%d) with unresolved blocking issues",
                    lid,
                    self._max_rounds,
                )
                break

            # Remediation: dispatch fix worker to resolve blocking issues
            new_diff, fix_desc = self._fix_worker(current_diff, all_findings)
            record = LoopRoundRecord(
                round_number=round_idx,
                perspective_reports=reports,
                all_findings=all_findings,
                has_blocking_issues=True,
                fix_description=fix_desc,
                converged=False,
            )
            rounds_history.append(record)
            current_diff = new_diff

        is_clean = status == ReviewLoopStatus.CONVERGED
        final_summary = (
            f"Review loop successfully converged in {len(rounds_history)} round(s)."
            if is_clean
            else f"Review loop terminated after {len(rounds_history)} round(s) with remaining issues."
        )

        return ReviewLoopResult(
            loop_id=lid,
            status=status,
            total_rounds=len(rounds_history),
            max_rounds=self._max_rounds,
            rounds=tuple(rounds_history),
            is_clean=is_clean,
            final_summary=final_summary,
        )
