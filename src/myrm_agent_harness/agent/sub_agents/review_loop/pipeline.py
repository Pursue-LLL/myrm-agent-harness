"""Tri-Perspective Parallel Review Pipeline (Item 32).

Dispatches code diffs concurrently across the three specialized reviewer subagents
(Correctness, Test Coverage, Simplicity) and aggregates structured findings.

[INPUT]
- __future__
- concurrent
- logging
- collections
- types

[OUTPUT]
- logger
- ReviewerHandler
- default_deterministic_reviewer
- from_keyword_severity
- MultiPerspectiveReviewPipeline

[POS]
Tri-Perspective Parallel Review Pipeline (Item 32).
"""

from __future__ import annotations

import concurrent.futures
import logging
from collections.abc import Callable

from .types import (
    PerspectiveReviewReport,
    ReviewFinding,
    ReviewPerspective,
)

logger = logging.getLogger(__name__)

ReviewerHandler = Callable[[ReviewPerspective, str, str | None], PerspectiveReviewReport]


def default_deterministic_reviewer(
    perspective: ReviewPerspective,
    diff: str,
    context: str | None = None,
) -> PerspectiveReviewReport:
    """Heuristic fallback reviewer inspecting basic patterns when no custom LLM handler is wired."""
    findings: list[ReviewFinding] = []
    diff_lower = diff.lower()

    if perspective == ReviewPerspective.CORRECTNESS:
        if "todo" in diff_lower or "pass" in diff_lower:
            findings.append(
                ReviewFinding(
                    perspective=perspective,
                    severity=from_keyword_severity("major"),
                    file_path="diff_inspection",
                    issue="Unfinished stub or placeholder pass detected in diff",
                    suggestion="Implement full business logic and remove placeholder stubs",
                )
            )
        if "except:" in diff or ("except Exception:" in diff and "pass" in diff):
            findings.append(
                ReviewFinding(
                    perspective=perspective,
                    severity=from_keyword_severity("critical"),
                    file_path="diff_inspection",
                    issue="Potentially swallowed exception handler with bare pass",
                    suggestion="Log exception or reraise explicitly",
                )
            )

    elif perspective == ReviewPerspective.TEST_COVERAGE:
        if "def test_" not in diff and "test" not in diff_lower:
            findings.append(
                ReviewFinding(
                    perspective=perspective,
                    severity=from_keyword_severity("major"),
                    file_path="diff_inspection",
                    issue="No unit test changes or assertions accompanying new logic",
                    suggestion="Add dedicated unit tests asserting boundary conditions",
                )
            )

    elif perspective == ReviewPerspective.SIMPLICITY:
        if "import typing" in diff and "any" in diff_lower:
            findings.append(
                ReviewFinding(
                    perspective=perspective,
                    severity=from_keyword_severity("minor"),
                    file_path="diff_inspection",
                    issue="Unconstrained Any type detected in type signature",
                    suggestion="Replace Any with concrete typed union or generic parameter",
                )
            )

    has_blocking = any(f.severity.is_blocking for f in findings)
    summary = (
        f"{perspective.value} review passed cleanly."
        if not has_blocking
        else f"{perspective.value} review discovered {len(findings)} issues needing resolution."
    )

    return PerspectiveReviewReport(
        perspective=perspective,
        reviewer_name=f"{perspective.value}-reviewer",
        approved=not has_blocking,
        findings=tuple(findings),
        summary=summary,
    )


def from_keyword_severity(keyword: str):
    from .types import FindingSeverity

    match keyword.lower():
        case "blocker":
            return FindingSeverity.BLOCKER
        case "critical":
            return FindingSeverity.CRITICAL
        case "major":
            return FindingSeverity.MAJOR
        case "minor":
            return FindingSeverity.MINOR
        case _:
            return FindingSeverity.SUGGESTION


class MultiPerspectiveReviewPipeline:
    """Orchestrates parallel evaluation across all three review perspectives."""

    def __init__(
        self,
        custom_handler: ReviewerHandler | None = None,
        perspectives: tuple[ReviewPerspective, ...] = (
            ReviewPerspective.CORRECTNESS,
            ReviewPerspective.TEST_COVERAGE,
            ReviewPerspective.SIMPLICITY,
        ),
    ) -> None:
        self._handler: ReviewerHandler = custom_handler or default_deterministic_reviewer
        self._perspectives = perspectives

    @property
    def perspectives(self) -> tuple[ReviewPerspective, ...]:
        return self._perspectives

    def run_parallel_review(
        self,
        diff: str,
        context: str | None = None,
        max_workers: int = 3,
    ) -> dict[ReviewPerspective, PerspectiveReviewReport]:
        """Dispatch reviews across perspectives concurrently."""
        reports: dict[ReviewPerspective, PerspectiveReviewReport] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._handler, p, diff, context): p for p in self._perspectives
            }
            for future in concurrent.futures.as_completed(futures):
                perspective = futures[future]
                try:
                    report = future.result()
                    reports[perspective] = report
                except Exception as err:
                    logger.error("Perspective reviewer '%s' failed: %s", perspective, err)
                    reports[perspective] = PerspectiveReviewReport(
                        perspective=perspective,
                        reviewer_name=f"{perspective.value}-reviewer",
                        approved=False,
                        findings=(),
                        summary=f"Reviewer encountered unhandled error: {err}",
                    )

        return reports

    @staticmethod
    def aggregate_findings(
        reports: dict[ReviewPerspective, PerspectiveReviewReport],
    ) -> tuple[ReviewFinding, ...]:
        """Flatten and return all findings across perspectives."""
        all_findings: list[ReviewFinding] = []
        for report in reports.values():
            all_findings.extend(report.findings)
        return tuple(all_findings)

    @staticmethod
    def has_blocking_issues(findings: tuple[ReviewFinding, ...]) -> bool:
        """Check whether any discovered finding blocks convergence/approval."""
        return any(f.severity.is_blocking for f in findings)
