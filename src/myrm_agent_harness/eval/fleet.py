"""Fleet Evaluation Runner — Parallel Multi-Attempt Variance Estimation & Resume Engine.

[INPUT]
- protocols::AgentExecutor, EvalCase, MultiTurnEvalCase, EvalTurnResult, EvalResult, EvalManifest, JudgeConfig (POS: eval types)
- runner::EvalRunner (POS: single/multi-turn eval orchestrator)

[OUTPUT]
- FleetVarianceMetrics: statistical variance, std_dev, and pass@k metrics
- FleetEvalResult: multi-attempt evaluation results container
- FleetEvalRunner: runner orchestrating n_attempts and checkpoint resume
- calculate_fleet_variance(): statistical aggregator across evaluation attempts

[POS]
Orchestrates fleet-scale evaluation across multiple stochastic attempts (n_attempts=3).
Computes sample variance, standard deviation (±σ), and Pass@k metrics to eliminate
single-run flakiness in LLM benchmark reporting, while supporting seamless job resume.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .protocols import (
    EvalCase,
    EvalManifest,
    EvalResult,
    EvalTurnResult,
    JudgeConfig,
    MultiTurnEvalCase,
)
from .runner import EvalRunner

if TYPE_CHECKING:
    from .protocols import AgentExecutor

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FleetVarianceMetrics:
    """Statistical variance and confidence metrics across multiple evaluation attempts."""

    n_attempts: int = 1
    mean_pass_rate: float = 0.0
    std_dev: float = 0.0
    margin_of_error_95: float = 0.0
    pass_at_1: float = 0.0
    pass_at_k: float = 0.0
    attempt_pass_rates: tuple[float, ...] = ()
    difficulty_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "n_attempts": self.n_attempts,
            "mean_pass_rate": round(self.mean_pass_rate, 4),
            "std_dev": round(self.std_dev, 4),
            "margin_of_error_95": round(self.margin_of_error_95, 4),
            "pass_at_1": round(self.pass_at_1, 4),
            "pass_at_k": round(self.pass_at_k, 4),
            "attempt_pass_rates": list(self.attempt_pass_rates),
            "difficulty_breakdown": self.difficulty_breakdown,
        }


def calculate_fleet_variance(
    attempt_results: list[EvalResult],
    *,
    cases: list[MultiTurnEvalCase] | list[EvalCase] | None = None,
) -> FleetVarianceMetrics:
    """Compute statistical variance, standard deviation, and Pass@k across evaluation attempts."""
    if not attempt_results:
        return FleetVarianceMetrics()

    n = len(attempt_results)
    rates = [r.pass_rate for r in attempt_results]
    mean_rate = sum(rates) / n if n > 0 else 0.0

    if n > 1:
        variance = sum((r - mean_rate) ** 2 for r in rates) / (n - 1)
        std_dev = math.sqrt(variance)
        # 95% Confidence Interval half-width ~ 1.96 * (std_dev / sqrt(n))
        margin_of_error = 1.96 * (std_dev / math.sqrt(n))
    else:
        std_dev = 0.0
        margin_of_error = 0.0

    pass_at_1 = mean_rate

    # Compute task-level Pass@k: fraction of tasks where at least one attempt succeeded
    pass_at_k = mean_rate
    if n > 1 and cases:
        total_tasks = len(cases)
        passed_tasks = 0
        for task_idx in range(total_tasks):
            task_passed_any = False
            for attempt in attempt_results:
                if task_idx < len(attempt.turn_results):
                    if attempt.turn_results[task_idx].assertion_passed is True:
                        task_passed_any = True
                        break
            if task_passed_any:
                passed_tasks += 1
        pass_at_k = (passed_tasks / total_tasks) if total_tasks > 0 else 0.0

    # Difficulty breakdown if metadata carries difficulty tier (easy/medium/hard)
    difficulty_map: dict[str, list[bool]] = {}
    if cases:
        for idx, c in enumerate(cases):
            meta = c.metadata if hasattr(c, "metadata") else {}
            diff = str(meta.get("difficulty", meta.get("tier", "standard"))).lower()
            if diff not in difficulty_map:
                difficulty_map[diff] = []
            for attempt in attempt_results:
                if idx < len(attempt.turn_results):
                    passed = attempt.turn_results[idx].assertion_passed is True
                    difficulty_map[diff].append(passed)

    diff_breakdown: dict[str, dict[str, float]] = {}
    for diff_name, outcomes in difficulty_map.items():
        if outcomes:
            p_count = sum(1 for o in outcomes if o)
            diff_breakdown[diff_name] = {
                "total_runs": float(len(outcomes)),
                "pass_rate": round(p_count / len(outcomes), 4),
            }

    return FleetVarianceMetrics(
        n_attempts=n,
        mean_pass_rate=mean_rate,
        std_dev=std_dev,
        margin_of_error_95=margin_of_error,
        pass_at_1=pass_at_1,
        pass_at_k=pass_at_k,
        attempt_pass_rates=tuple(round(r, 4) for r in rates),
        difficulty_breakdown=diff_breakdown,
    )


@dataclass(slots=True)
class FleetEvalResult:
    """Consolidated result container for multi-attempt fleet evaluation."""

    primary_result: EvalResult
    attempt_results: list[EvalResult] = field(default_factory=list)
    variance_metrics: FleetVarianceMetrics = field(default_factory=FleetVarianceMetrics)
    resumed_cases_count: int = 0
    total_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        res = self.primary_result.to_dict()
        res["variance_metrics"] = self.variance_metrics.to_dict()
        res["resumed_cases_count"] = self.resumed_cases_count
        res["total_attempts"] = len(self.attempt_results)
        return res

    def summary(self) -> str:
        var = self.variance_metrics
        std_str = f" ±{var.std_dev:.1%}" if var.n_attempts > 1 else ""
        return (
            f"Fleet Eval ({var.n_attempts} attempts): "
            f"Pass Rate = {var.mean_pass_rate:.1%}{std_str} (Pass@{var.n_attempts} = {var.pass_at_k:.1%}), "
            f"Resumed {self.resumed_cases_count} cases, {self.total_ms:.0f}ms"
        )


class FleetEvalRunner:
    """Fleet-scale evaluation orchestrator with multi-attempt variance estimation and resume support."""

    def __init__(
        self,
        executor: AgentExecutor,
        *,
        n_attempts: int = 1,
        max_concurrency: int = 1,
        on_case_complete: Callable[[EvalTurnResult], None] | None = None,
        yielding_strategy: AbstractAsyncContextManager[None] | None = None,
        judge_config: JudgeConfig | None = None,
    ) -> None:
        self._executor = executor
        self._n_attempts = max(1, n_attempts)
        self._max_concurrency = max(1, max_concurrency)
        self._on_case_complete = on_case_complete
        self._yielding_strategy = yielding_strategy
        self._judge_config = judge_config
        self._abort_requested = False
        self._active_runner: EvalRunner | None = None

    def abort(self) -> None:
        """Signal the fleet runner to abort all evaluation attempts gracefully."""
        self._abort_requested = True
        if self._active_runner:
            self._active_runner.abort()

    def _get_case_key(self, case: EvalCase | MultiTurnEvalCase) -> str:
        """Generate a deterministic deduplication key for a test case."""
        if isinstance(case, MultiTurnEvalCase):
            task_id = case.metadata.get("wb_bench_task_id") or case.metadata.get("task_id")
            if task_id:
                return str(task_id)
            first_msg = case.turns[0].message if case.turns else ""
            return first_msg.strip()
        task_id = case.metadata.get("wb_bench_task_id") or case.metadata.get("task_id")
        if task_id:
            return str(task_id)
        return case.message.strip()

    async def run_multi_turn_fleet(
        self,
        cases: list[MultiTurnEvalCase],
        *,
        manifest: EvalManifest | None = None,
        resume_turn_results: list[EvalTurnResult] | None = None,
        difficulty_filter: str | None = None,
    ) -> FleetEvalResult:
        """Execute multi-turn cases across n_attempts with optional resume from prior results."""
        start_time = time.perf_counter()

        # 1. Filter by difficulty shard if specified
        target_cases = cases
        if difficulty_filter and difficulty_filter.lower() != "all":
            filt = difficulty_filter.lower()
            target_cases = [
                c
                for c in cases
                if str(c.metadata.get("difficulty", c.metadata.get("tier", ""))).lower() == filt
            ]
            if not target_cases:
                target_cases = cases

        # 2. Extract completed case keys for checkpoint resume
        completed_map: dict[str, EvalTurnResult] = {}
        if resume_turn_results:
            for r in resume_turn_results:
                if r.assertion_passed is True:
                    k_meta = r.case.metadata.get("wb_bench_task_id") or r.case.metadata.get("task_id")
                    if k_meta:
                        completed_map[str(k_meta)] = r
                    if r.case.message:
                        completed_map[r.case.message.strip()] = r

        resumed_count = 0
        cases_to_run: list[MultiTurnEvalCase] = []
        prefilled_results: list[EvalTurnResult] = []

        for c in target_cases:
            ckey = self._get_case_key(c)
            first_msg = c.turns[0].message.strip() if c.turns else ""
            matched_res = completed_map.get(ckey) or (completed_map.get(first_msg) if first_msg else None)
            if matched_res is not None:
                resumed_count += 1
                prefilled_results.append(matched_res)
            else:
                cases_to_run.append(c)

        attempt_results: list[EvalResult] = []

        # 3. Execute N attempts
        for attempt_idx in range(self._n_attempts):
            if self._abort_requested:
                break

            runner = EvalRunner(
                self._executor,
                max_concurrency=self._max_concurrency,
                on_case_complete=self._on_case_complete,
                yielding_strategy=self._yielding_strategy,
                judge_config=self._judge_config,
            )
            self._active_runner = runner

            if cases_to_run:
                run_res = await runner.run_multi_turn(cases_to_run, manifest=manifest)
                combined_turns = list(prefilled_results) + list(run_res.turn_results)
                eval_res = EvalResult(
                    turn_results=combined_turns,
                    total_ms=run_res.total_ms,
                    manifest=manifest,
                )
            else:
                eval_res = EvalResult(
                    turn_results=list(prefilled_results),
                    total_ms=0.0,
                    manifest=manifest,
                )

            attempt_results.append(eval_res)

        total_ms = (time.perf_counter() - start_time) * 1000
        primary = attempt_results[0] if attempt_results else EvalResult(manifest=manifest)
        variance_metrics = calculate_fleet_variance(attempt_results, cases=target_cases)

        return FleetEvalResult(
            primary_result=primary,
            attempt_results=attempt_results,
            variance_metrics=variance_metrics,
            resumed_cases_count=resumed_count,
            total_ms=total_ms,
        )
