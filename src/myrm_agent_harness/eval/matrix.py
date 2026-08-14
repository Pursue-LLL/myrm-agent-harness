"""Matrix Eval Runner — cross-profile comparative evaluation.

[INPUT]
- runner::EvalRunner (POS: single-profile eval execution)
- protocols::AgentExecutor, EvalCase, EvalResult, EvalTurnResult

[OUTPUT]
- MatrixRunner: orchestrates eval across multiple executors sequentially
- MatrixResult: aggregated comparison with stable/regression classification
- MatrixCellResult: per-case-per-profile outcome

[POS]
Enables comparing the same eval cases across different Agent Profiles
(e.g., different LLM models) to identify capability regressions before
switching. Framework-only — no business-layer imports.
"""

from __future__ import annotations

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
            "total_ms": round(self.total_ms, 2),
        }


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
