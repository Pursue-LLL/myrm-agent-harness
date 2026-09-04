"""Matrix Eval Runner — cross-profile comparative evaluation.

[INPUT]
- runner::EvalRunner (POS: single-profile eval execution)
- protocols::AgentExecutor, EvalCase, EvalResult, EvalTurnResult

[OUTPUT]
- MatrixRunner: orchestrates eval across multiple executors sequentially
- MatrixResult: aggregated comparison with stable/regression classification
- MatrixCellResult: per-case-per-profile outcome
- GeneralizationGateVerdict: cross-model generalization gate outcome
- GeneralizationGateMetrics: structured multi-profile generalization assessment
- evaluate_generalization_gate: evaluates whether an agent variant generalizes across >=N models

[POS]
Enables comparing the same eval cases across different Agent Profiles
(e.g., different LLM models) to identify capability regressions before
switching. Implements Meta-Harness cross-model generalization gate.
Framework-only — no business-layer imports.
"""

from __future__ import annotations

import enum
import logging
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .protocols import EvalCase, EvalResult, EvalTurnResult, JudgeConfig
from .runner import EvalRunner

if TYPE_CHECKING:
    from .protocols import AgentExecutor, EvalManifest, MultiTurnEvalCase

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MatrixCellResult:
    """Outcome of a single case on a single profile."""

    profile_id: str
    case_index: int
    passed: bool | None
    assertion_details: str | None
    total_ms: float
    token_usage: dict[str, int] = field(default_factory=dict)
    cost: float = 0.0
    error: str | None = None
    # Trajectory disclosure: tool invocation count, engine limit that stopped
    # the run (if any), and decontamination blocks — so a matrix report shows
    # when a case was truncated or pollution-guarded rather than completed.
    tool_calls: int = 0
    limit_reached: str | None = None
    blocked_count: int = 0


class GeneralizationGateVerdict(enum.StrEnum):
    """Verdict for cross-model generalization gate."""

    PASSED = "passed"  # Generalizes across >=N models without severe regression
    PARTIAL_OVERFIT = "partial_overfit"  # High pass rate on single model but regresses on others
    GENERALIZATION_COLLAPSE = "generalization_collapse"  # Severe regression across multiple models
    INSUFFICIENT_PROFILES = "insufficient_profiles"  # Fewer than min_required_profiles evaluated


@dataclass(frozen=True, slots=True)
class GeneralizationGateMetrics:
    """Multi-profile generalization gate assessment details."""

    verdict: GeneralizationGateVerdict
    min_required_profiles: int
    evaluated_profile_count: int
    passed_profile_count: int
    regression_case_count: int
    stable_case_count: int
    mean_pass_rate: float
    pass_rate_spread: float
    per_profile_status: dict[str, dict[str, object]] = field(default_factory=dict)
    recommendation: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict.value,
            "min_required_profiles": self.min_required_profiles,
            "evaluated_profile_count": self.evaluated_profile_count,
            "passed_profile_count": self.passed_profile_count,
            "regression_case_count": self.regression_case_count,
            "stable_case_count": self.stable_case_count,
            "mean_pass_rate": round(self.mean_pass_rate, 4),
            "pass_rate_spread": round(self.pass_rate_spread, 4),
            "per_profile_status": self.per_profile_status,
            "recommendation": self.recommendation,
        }


@dataclass(slots=True)
class MatrixResult:
    """Aggregated matrix evaluation result across profiles."""

    profile_ids: list[str]
    cases: list[EvalCase]
    per_profile_results: dict[str, EvalResult] = field(default_factory=dict)
    total_ms: float = 0.0

    @property
    def stable_cases(self) -> list[int]:
        """Case indices that pass on ALL profiles (Skill stable boundary)."""
        stable: list[int] = []
        for i in range(len(self.cases)):
            if all(self._cell_passed(profile_id, i) for profile_id in self.profile_ids):
                stable.append(i)
        return stable

    @property
    def regression_cases(self) -> list[int]:
        """Case indices that pass on some profiles but fail on others."""
        regressions: list[int] = []
        for i in range(len(self.cases)):
            results = [self._cell_passed(profile_id, i) for profile_id in self.profile_ids]
            if any(r is True for r in results) and any(r is not True for r in results):
                regressions.append(i)
        return regressions

    def _cell_passed(self, profile_id: str, case_index: int) -> bool | None:
        result = self.per_profile_results.get(profile_id)
        if not result or case_index >= len(result.turn_results):
            return None
        return result.turn_results[case_index].assertion_passed

    def get_cell(self, profile_id: str, case_index: int) -> MatrixCellResult | None:
        """Get a specific cell from the matrix."""
        result = self.per_profile_results.get(profile_id)
        if not result or case_index >= len(result.turn_results):
            return None
        turn = result.turn_results[case_index]
        return MatrixCellResult(
            profile_id=profile_id,
            case_index=case_index,
            passed=turn.assertion_passed,
            assertion_details=turn.assertion_details,
            total_ms=turn.timings.total_ms,
            token_usage=turn.response.token_usage,
            cost=turn.response.cost,
            error=turn.error,
            tool_calls=len(turn.response.tools_called),
            limit_reached=turn.response.limit_reached,
            blocked_count=turn.response.blocked_count,
        )

    def to_dict(self) -> dict[str, object]:
        """Export as JSON-serializable dict."""
        matrix: list[dict[str, object]] = []
        for i, case in enumerate(self.cases):
            row: dict[str, object] = {"case_index": i, "message": case.message}
            cells: dict[str, object] = {}
            for pid in self.profile_ids:
                cell = self.get_cell(pid, i)
                if cell:
                    cells[pid] = {
                        "passed": cell.passed,
                        "total_ms": round(cell.total_ms, 2),
                        "token_usage": cell.token_usage,
                        "cost": round(cell.cost, 6),
                        "error": cell.error,
                        "tool_calls": cell.tool_calls,
                        "limit_reached": cell.limit_reached,
                        "blocked_count": cell.blocked_count,
                    }
            row["profiles"] = cells
            matrix.append(row)

        per_profile_summary: dict[str, object] = {}
        for pid in self.profile_ids:
            r = self.per_profile_results.get(pid)
            if r:
                per_profile_summary[pid] = {
                    "pass_count": r.pass_count,
                    "fail_count": r.fail_count,
                    "error_count": r.error_count,
                    "pass_rate": round(r.pass_rate, 4),
                    "total_tokens": r.total_tokens,
                    "total_cost": round(r.total_cost, 6),
                    "total_ms": round(r.total_ms, 2),
                    "total_tool_calls": sum(len(turn.response.tools_called) for turn in r.turn_results),
                    "limit_hits": sum(1 for turn in r.turn_results if turn.response.limit_reached is not None),
                    "blocked_count": sum(turn.response.blocked_count for turn in r.turn_results),
                }

        return {
            "profile_ids": self.profile_ids,
            "total_cases": len(self.cases),
            "stable_count": len(self.stable_cases),
            "regression_count": len(self.regression_cases),
            "stable_rate": round(len(self.stable_cases) / len(self.cases), 4) if self.cases else 0.0,
            "per_profile": per_profile_summary,
            "matrix": matrix,
            "generalization_gate": evaluate_generalization_gate(self).to_dict(),
            "total_ms": round(self.total_ms, 2),
        }


def evaluate_generalization_gate(
    matrix_result: MatrixResult,
    *,
    min_required_profiles: int = 2,
    pass_rate_threshold: float = 0.5,
    max_regression_rate: float = 0.25,
) -> GeneralizationGateMetrics:
    """Evaluate whether an agent variant generalizes across multiple model profiles.

    Implements Meta-Harness held-out generalization gate principle:
    To prevent single-model pathology-patch overfitting, an evolution or configuration
    must maintain acceptable performance across at least >=min_required_profiles without
    incurring severe cross-profile capability regressions.
    """
    profile_count = len(matrix_result.profile_ids)
    case_count = len(matrix_result.cases)
    stable_count = len(matrix_result.stable_cases)
    regression_count = len(matrix_result.regression_cases)

    if profile_count < min_required_profiles:
        return GeneralizationGateMetrics(
            verdict=GeneralizationGateVerdict.INSUFFICIENT_PROFILES,
            min_required_profiles=min_required_profiles,
            evaluated_profile_count=profile_count,
            passed_profile_count=0,
            regression_case_count=regression_count,
            stable_case_count=stable_count,
            mean_pass_rate=0.0,
            pass_rate_spread=0.0,
            per_profile_status={},
            recommendation=f"Evaluate at least {min_required_profiles} profiles to verify cross-model generalization.",
        )

    pass_rates: list[float] = []
    per_profile_status: dict[str, dict[str, object]] = {}
    passed_profiles = 0

    for pid in matrix_result.profile_ids:
        res = matrix_result.per_profile_results.get(pid)
        pr = res.pass_rate if res else 0.0
        pass_rates.append(pr)
        meets_threshold = pr >= pass_rate_threshold
        if meets_threshold:
            passed_profiles += 1
        per_profile_status[pid] = {
            "pass_rate": round(pr, 4),
            "passed_gate": meets_threshold,
        }

    mean_pr = sum(pass_rates) / len(pass_rates) if pass_rates else 0.0
    pr_spread = (max(pass_rates) - min(pass_rates)) if pass_rates else 0.0
    regression_rate = (regression_count / case_count) if case_count > 0 else 0.0

    if passed_profiles >= min_required_profiles and regression_rate <= max_regression_rate:
        verdict = GeneralizationGateVerdict.PASSED
        recommendation = (
            f"Cross-model generalization verified on {passed_profiles}/{profile_count} profiles. "
            "Safe to adopt globally."
        )
    elif passed_profiles == 0 or (mean_pr < 0.2 and regression_rate > 0.5):
        verdict = GeneralizationGateVerdict.GENERALIZATION_COLLAPSE
        recommendation = (
            "Severe capability collapse across evaluated models. "
            "Reject candidate change."
        )
    else:
        verdict = GeneralizationGateVerdict.PARTIAL_OVERFIT
        recommendation = (
            f"Overfitting detected (spread: {round(pr_spread * 100, 1)}%, "
            f"regression rate: {round(regression_rate * 100, 1)}%). "
            "Patch likely addresses single-model pathology rather than universal capability."
        )

    return GeneralizationGateMetrics(
        verdict=verdict,
        min_required_profiles=min_required_profiles,
        evaluated_profile_count=profile_count,
        passed_profile_count=passed_profiles,
        regression_case_count=regression_count,
        stable_case_count=stable_count,
        mean_pass_rate=mean_pr,
        pass_rate_spread=pr_spread,
        per_profile_status=per_profile_status,
        recommendation=recommendation,
    )


OnProfileStart = Callable[[str, int, int], None]
OnMatrixCaseComplete = Callable[[str, EvalTurnResult], None]


class MatrixRunner:
    """Executes eval cases across multiple AgentExecutor instances sequentially.

    Profiles are executed one at a time (sequential) to avoid API rate-limit
    pressure. Within each profile, cases run with configurable concurrency
    via the underlying EvalRunner.
    """

    def __init__(
        self,
        executors: dict[str, AgentExecutor],
        *,
        max_concurrency_per_profile: int = 3,
        on_profile_start: OnProfileStart | None = None,
        on_case_complete: OnMatrixCaseComplete | None = None,
        yielding_strategy: AbstractAsyncContextManager[None] | None = None,
        judge_config: JudgeConfig | None = None,
    ) -> None:
        self._executors = executors
        self._max_concurrency = max_concurrency_per_profile
        self._on_profile_start = on_profile_start
        self._on_case_complete = on_case_complete
        self._yielding_strategy = yielding_strategy
        self._judge_config = judge_config
        self._abort_requested = False
        self._active_runner: EvalRunner | None = None

    def abort(self) -> None:
        """Signal abort — propagates to the currently active EvalRunner."""
        self._abort_requested = True
        if self._active_runner:
            self._active_runner.abort()

    async def run(
        self,
        cases: list[EvalCase],
        *,
        manifest_builder: Callable[[str], EvalManifest | None] | None = None,
    ) -> MatrixResult:
        """Run all single-turn cases against each profile sequentially."""
        start = time.perf_counter()
        profile_ids = list(self._executors.keys())
        per_profile_results: dict[str, EvalResult] = {}

        for idx, (profile_id, executor) in enumerate(self._executors.items()):
            if self._abort_requested:
                break

            if self._on_profile_start:
                self._on_profile_start(profile_id, idx, len(self._executors))

            def _make_callback(pid: str) -> Callable[[EvalTurnResult], None] | None:
                if not self._on_case_complete:
                    return None

                def _cb(turn_result: EvalTurnResult) -> None:
                    self._on_case_complete(pid, turn_result)  # type: ignore[misc]

                return _cb

            runner = EvalRunner(
                executor,
                max_concurrency=self._max_concurrency,
                on_case_complete=_make_callback(profile_id),
                yielding_strategy=self._yielding_strategy,
                judge_config=self._judge_config,
            )
            self._active_runner = runner

            manifest = manifest_builder(profile_id) if manifest_builder else None
            result = await runner.run(cases, manifest=manifest)
            per_profile_results[profile_id] = result

        self._active_runner = None
        total_ms = (time.perf_counter() - start) * 1000

        return MatrixResult(
            profile_ids=profile_ids,
            cases=cases,
            per_profile_results=per_profile_results,
            total_ms=total_ms,
        )

    async def run_multi_turn(
        self,
        cases: list[MultiTurnEvalCase],
        *,
        manifest_builder: Callable[[str], EvalManifest | None] | None = None,
    ) -> MatrixResult:
        """Run multi-turn cases against each profile sequentially.

        Each MultiTurnEvalCase is treated as an atomic unit — turns within it
        share a session. Results are aggregated by turn across all sessions.
        """
        start = time.perf_counter()
        profile_ids = list(self._executors.keys())
        per_profile_results: dict[str, EvalResult] = {}

        flat_cases = [turn for mc in cases for turn in mc.turns]

        for idx, (profile_id, executor) in enumerate(self._executors.items()):
            if self._abort_requested:
                break

            if self._on_profile_start:
                self._on_profile_start(profile_id, idx, len(self._executors))

            def _make_callback(pid: str) -> Callable[[EvalTurnResult], None] | None:
                if not self._on_case_complete:
                    return None

                def _cb(turn_result: EvalTurnResult) -> None:
                    self._on_case_complete(pid, turn_result)  # type: ignore[misc]

                return _cb

            runner = EvalRunner(
                executor,
                max_concurrency=self._max_concurrency,
                on_case_complete=_make_callback(profile_id),
                yielding_strategy=self._yielding_strategy,
                judge_config=self._judge_config,
            )
            self._active_runner = runner

            manifest = manifest_builder(profile_id) if manifest_builder else None
            result = await runner.run_multi_turn(cases, manifest=manifest)
            per_profile_results[profile_id] = result

        self._active_runner = None
        total_ms = (time.perf_counter() - start) * 1000

        return MatrixResult(
            profile_ids=profile_ids,
            cases=flat_cases,
            per_profile_results=per_profile_results,
            total_ms=total_ms,
        )
