"""Eval Runner — executes eval cases against an AgentExecutor.

[INPUT]
- protocol::AgentExecutor, (POS: Protocol contract. Framework provides FileEventLogBackend; business layer may extend with SQLite / PostgreSQL implementations.)
- assertions::ToolAssertion, (POS: Provides pass/fail verification of agent tool calls, output text, sandbox states, and subjective semantic evaluations via lightweight LLMs.)

[OUTPUT]
- EvalRunner: main eval runner with single-turn, multi-turn, and concurrent support

[POS]
Orchestrates eval execution. Supports concurrent case execution via asyncio.Semaphore,
optional progress callbacks, and graceful error handling (single case failure does not
abort the entire run). Framework-only — no business-layer imports.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from .assertions import (
    ToolAssertion,
    evaluate_sandbox_assertions,
    evaluate_semantic_assertions,
    evaluate_state_assertions,
    evaluate_tool_assertions,
)
from .protocols import (
    AgentResponse,
    EvalCase,
    EvalResult,
    EvalTimings,
    EvalTurnResult,
    MultiTurnEvalCase,
)

if TYPE_CHECKING:
    from .protocols import AgentExecutor

logger = logging.getLogger(__name__)


class EvalRunner:
    """Executes eval cases against an AgentExecutor implementation.

    Features:
    - Single-turn and multi-turn eval
    - Concurrent execution with configurable concurrency limit
    - Progress callback for real-time monitoring
    - Graceful error handling per case
    """

    def __init__(
        self,
        executor: AgentExecutor,
        *,
        max_concurrency: int = 1,
        on_case_complete: Callable[[EvalTurnResult], None] | None = None,
        yielding_strategy: AbstractAsyncContextManager[None] | None = None,
    ) -> None:
        self._executor = executor
        self._max_concurrency = max(1, max_concurrency)
        self._on_case_complete = on_case_complete
        self._yielding_strategy = yielding_strategy
        self._abort_requested = False

    def abort(self) -> None:
        """Signal the runner to abort evaluation gracefully."""
        self._abort_requested = True

    async def run(
        self,
        cases: list[EvalCase],
    ) -> EvalResult:
        """Run single-turn eval cases, optionally concurrently."""
        start = time.perf_counter()
        semaphore = self._yielding_strategy or asyncio.Semaphore(self._max_concurrency)

        async def _run_one(case: EvalCase) -> EvalTurnResult | None:
            if self._abort_requested:
                return None
            async with semaphore:
                if self._abort_requested:
                    return None
                return await self._execute_single(case)

        raw_results = await asyncio.gather(
            *[_run_one(c) for c in cases],
            return_exceptions=False,
        )
        turn_results = [r for r in raw_results if r is not None]

        total_ms = (time.perf_counter() - start) * 1000
        return EvalResult(turn_results=list(turn_results), total_ms=total_ms)

    async def run_multi_turn(
        self,
        cases: list[MultiTurnEvalCase],
    ) -> EvalResult:
        """Run multi-turn eval cases, optionally concurrently.

        Each MultiTurnEvalCase creates one session; turns execute sequentially
        within a session, but different sessions can run concurrently.
        """
        start = time.perf_counter()
        semaphore = self._yielding_strategy or asyncio.Semaphore(self._max_concurrency)

        async def _run_one_multi(mt_case: MultiTurnEvalCase) -> list[EvalTurnResult]:
            async with semaphore:
                return await self._execute_multi_turn(mt_case)

        nested_results = await asyncio.gather(
            *[_run_one_multi(c) for c in cases],
            return_exceptions=False,
        )

        all_results: list[EvalTurnResult] = []
        for session_results in nested_results:
            all_results.extend(session_results)

        total_ms = (time.perf_counter() - start) * 1000
        return EvalResult(turn_results=all_results, total_ms=total_ms)

    async def _execute_single(
        self,
        case: EvalCase,
        *,
        session_id: str | None = None,
    ) -> EvalTurnResult:
        """Execute a single eval case and return the result."""
        turn_start = time.perf_counter()

        try:
            sid = session_id or await self._executor.create_session()
            response = await self._executor.execute(case.message, session_id=sid)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            logger.warning("Eval case failed: %s — %s", case.message[:60], exc)
            result = EvalTurnResult(
                case=case,
                response=AgentResponse(answer=""),
                error=str(exc),
                timings=EvalTimings(total_ms=(time.perf_counter() - turn_start) * 1000),
            )
            self._notify(result)
            return result

        assertion = (
            ToolAssertion(
                expected_tools=case.expected_tools,
                require_all=case.require_all,
            )
            if case.expected_tools
            else None
        )

        passed, details = evaluate_tool_assertions(response.tools_called, assertion)

        if passed is not False and case.sandbox_assertions:
            # Pass sid to get the sandbox executor for this specific session
            sandbox_executor = getattr(self._executor, "get_sandbox_executor", lambda session_id: None)(session_id=sid)
            sb_passed, sb_details = await evaluate_sandbox_assertions(case.sandbox_assertions, sandbox_executor)
            if sb_passed is not None:
                passed = sb_passed if passed is None else (passed and sb_passed)
                if sb_details:
                    details = f"{details} | {sb_details}" if details else sb_details

        if passed is not False and getattr(case, "state_assertions", None):
            state_passed, state_details = evaluate_state_assertions(case.state_assertions, response.answer)
            if state_passed is not None:
                passed = state_passed if passed is None else (passed and state_passed)
                if state_details:
                    details = f"{details} | {state_details}" if details else state_details

        if passed is not False and getattr(case, "semantic_assertions", None):
            sem_passed, sem_details = await evaluate_semantic_assertions(case.semantic_assertions, response.answer)
            if sem_passed is not None:
                passed = sem_passed if passed is None else (passed and sem_passed)
                if sem_details:
                    details = f"{details} | {sem_details}" if details else sem_details

        timings = EvalTimings(
            total_ms=(time.perf_counter() - turn_start) * 1000,
            extra=response.extra_timings,
        )

        result = EvalTurnResult(
            case=case,
            response=response,
            assertion_passed=passed,
            assertion_details=details,
            timings=timings,
        )

        self._notify(result)
        return result

    async def _execute_multi_turn(
        self,
        mt_case: MultiTurnEvalCase,
    ) -> list[EvalTurnResult]:
        """Execute a multi-turn case — turns are sequential within a session."""
        session_id = await self._executor.create_session()
        results: list[EvalTurnResult] = []

        for turn in mt_case.turns:
            result = await self._execute_single(turn, session_id=session_id)
            results.append(result)

            if result.error is not None:
                logger.warning(
                    "Multi-turn session %s aborted at turn %d due to error",
                    session_id,
                    len(results),
                )
                break

        return results

    def _notify(self, result: EvalTurnResult) -> None:
        if self._on_case_complete is not None:
            try:
                self._on_case_complete(result)
            except Exception:
                logger.warning("on_case_complete callback raised", exc_info=True)
