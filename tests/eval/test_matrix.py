"""Tests for cross-profile matrix evaluation (matrix.py).

Covers ``MatrixResult`` aggregation (stable/regression classification,
``get_cell``, ``to_dict``) and ``MatrixRunner`` orchestration (sequential
profiles, callbacks, manifest builder, abort, multi-turn flattening).
"""

import pytest

from myrm_agent_harness.eval.matrix import MatrixResult, MatrixRunner
from myrm_agent_harness.eval.protocols import (
    AgentResponse,
    EvalCase,
    EvalManifest,
    EvalResult,
    EvalTimings,
    EvalTurnResult,
    MultiTurnEvalCase,
)


def _case(message: str) -> EvalCase:
    return EvalCase(message=message)


def _turn(case: EvalCase, passed: bool | None = None) -> EvalTurnResult:
    return EvalTurnResult(
        case=case,
        response=AgentResponse(
            answer="ok", token_usage={"total_tokens": 12}, cost=0.01
        ),
        assertion_passed=passed,
        timings=EvalTimings(total_ms=10.0),
    )


def _result(turns: list[EvalTurnResult]) -> EvalResult:
    return EvalResult(turn_results=turns)


class FakeExecutor:
    """Minimal AgentExecutor protocol implementation for MatrixRunner tests."""

    async def execute(
        self, message: str, *, session_id: str | None = None
    ) -> AgentResponse:
        return AgentResponse(answer=f"reply:{message}")

    async def create_session(self) -> str:
        return "session-1"

    def get_sandbox_executor(self, session_id: str | None = None) -> object:
        return None


class _FakeEvalRunner:
    """Patches ``matrix.EvalRunner`` to avoid real case execution."""

    def __init__(self, executor: object, **kwargs: object) -> None:
        self.executor = executor
        self.kwargs = kwargs

    async def run(
        self, cases: list[EvalCase], manifest: EvalManifest | None = None
    ) -> EvalResult:
        return _result([_turn(case, True) for case in cases])

    async def run_multi_turn(
        self, cases: list[MultiTurnEvalCase], manifest: EvalManifest | None = None
    ) -> EvalResult:
        return _result([_turn(turn, True) for mc in cases for turn in mc.turns])

    def abort(self) -> None:
        pass


def _manifest(profile_id: str) -> EvalManifest:
    return EvalManifest(
        model_provider="provider",
        model_id="model",
        harness_version="0.1",
        tool_policy=(),
        task_set_id="task",
        task_set_hash="hash",
        prompt_fingerprint="fingerprint",
        budget_max_tokens=1000,
        timeout_seconds=60,
        created_at="now",
        profile_id=profile_id,
    )


class _CallbackEvalRunner(_FakeEvalRunner):
    """Fake runner that forwards ``on_case_complete`` to the caller."""

    async def run(
        self, cases: list[EvalCase], manifest: EvalManifest | None = None
    ) -> EvalResult:
        events.append(("run", manifest.profile_id if manifest else None))
        callback = self.kwargs.get("on_case_complete")
        if callback:
            callback(_turn(cases[0], True))  # type: ignore[call-arg]
        return await super().run(cases, manifest)

    async def run_multi_turn(
        self, cases: list[MultiTurnEvalCase], manifest: EvalManifest | None = None
    ) -> EvalResult:
        callback = self.kwargs.get("on_case_complete")
        if callback:
            callback(_turn(cases[0].turns[0], True))  # type: ignore[call-arg]
        return await super().run_multi_turn(cases, manifest)


class _RecordingRunner(_FakeEvalRunner):
    """Fake runner that records whether ``abort`` was propagated."""

    def __init__(self, executor: object, **kwargs: object) -> None:
        super().__init__(executor, **kwargs)
        self.aborted = False

    def abort(self) -> None:
        self.aborted = True


events: list[tuple[str, object]] = []


class TestMatrixResult:
    """Aggregation semantics: stable vs regression classification."""

    def test_stable_cases_require_all_profiles_passing(self) -> None:
        cases = [_case("c0"), _case("c1"), _case("c2")]
        result = MatrixResult(
            profile_ids=["a", "b"],
            cases=cases,
            per_profile_results={
                "a": _result(
                    [
                        _turn(cases[0], True),
                        _turn(cases[1], True),
                        _turn(cases[2], False),
                    ]
                ),
                "b": _result(
                    [
                        _turn(cases[0], True),
                        _turn(cases[1], False),
                        _turn(cases[2], False),
                    ]
                ),
            },
        )
        assert result.stable_cases == [0]
        assert result.regression_cases == [1]

    def test_all_failing_is_not_regression(self) -> None:
        cases = [_case("c0")]
        result = MatrixResult(
            profile_ids=["a", "b"],
            cases=cases,
            per_profile_results={
                "a": _result([_turn(cases[0], False)]),
                "b": _result([_turn(cases[0], False)]),
            },
        )
        assert result.stable_cases == []
        assert result.regression_cases == []

    def test_get_cell_out_of_range_and_unknown_profile(self) -> None:
        cases = [_case("c0")]
        result = MatrixResult(
            profile_ids=["a"],
            cases=cases,
            per_profile_results={"a": _result([_turn(cases[0], True)])},
        )
        cell = result.get_cell("a", 0)
        assert cell is not None
        assert cell.passed is True
        assert cell.total_ms == 10.0
        assert cell.token_usage == {"total_tokens": 12}
        assert result.get_cell("a", 5) is None
        assert result.get_cell("missing", 0) is None

    def test_to_dict_shape(self) -> None:
        cases = [_case("c0")]
        result = MatrixResult(
            profile_ids=["a"],
            cases=cases,
            per_profile_results={"a": _result([_turn(cases[0], True)])},
            total_ms=25.0,
        )
        data = result.to_dict()
        assert data["profile_ids"] == ["a"]
        assert data["total_cases"] == 1
        assert data["stable_count"] == 1
        assert data["regression_count"] == 0
        assert data["stable_rate"] == 1.0
        assert len(data["matrix"]) == 1
        assert data["matrix"][0]["profiles"]["a"]["passed"] is True
        assert data["per_profile"]["a"]["pass_rate"] == 1.0
        assert data["total_ms"] == 25.0

    def test_to_dict_empty_cases_stable_rate_zero(self) -> None:
        result = MatrixResult(profile_ids=["a"], cases=[])
        data = result.to_dict()
        assert data["stable_rate"] == 0.0
        assert result.stable_cases == []
        assert result.regression_cases == []

    def test_stable_cases_tolerate_short_profile_results(self) -> None:
        """A profile result with fewer turns than cases yields None cells."""
        cases = [_case("c0"), _case("c1")]
        result = MatrixResult(
            profile_ids=["a", "b"],
            cases=cases,
            per_profile_results={
                "a": _result([_turn(cases[0], True)]),
                "b": _result([_turn(cases[0], True), _turn(cases[1], True)]),
            },
        )
        # case 1 lacks a cell on profile "a"; the None cell counts as
        # "not passed", so the case is a cross-profile regression (per
        # current MatrixResult semantics) rather than stable.
        assert result.stable_cases == [0]
        assert result.regression_cases == [1]


class TestMatrixRunner:
    """Sequential profile orchestration with callbacks and abort."""

    @pytest.mark.asyncio
    async def test_run_sequential_profiles(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "myrm_agent_harness.eval.matrix.EvalRunner", _FakeEvalRunner
        )
        runner = MatrixRunner({"a": FakeExecutor(), "b": FakeExecutor()})
        result = await runner.run([_case("hello")])
        assert result.profile_ids == ["a", "b"]
        assert list(result.per_profile_results) == ["a", "b"]
        assert result.stable_cases == [0]

    @pytest.mark.asyncio
    async def test_run_callbacks_and_manifest_builder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events.clear()
        monkeypatch.setattr(
            "myrm_agent_harness.eval.matrix.EvalRunner", _CallbackEvalRunner
        )
        runner = MatrixRunner(
            {"a": FakeExecutor(), "b": FakeExecutor()},
            on_profile_start=lambda pid, idx, total: events.append(("start", pid)),
            on_case_complete=lambda pid, turn: events.append(("case", pid)),
        )
        await runner.run([_case("c")], manifest_builder=_manifest)
        assert ("start", "a") in events
        assert ("run", "a") in events
        assert ("case", "a") in events
        assert ("run", "b") in events

    @pytest.mark.asyncio
    async def test_abort_before_run_yields_no_results(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "myrm_agent_harness.eval.matrix.EvalRunner", _FakeEvalRunner
        )
        runner = MatrixRunner({"a": FakeExecutor()})
        runner.abort()
        result = await runner.run([_case("c")])
        assert result.per_profile_results == {}

    def test_abort_propagates_to_active_runner(self) -> None:
        runner = MatrixRunner({"a": FakeExecutor()})
        active = _RecordingRunner(FakeExecutor())
        runner._active_runner = active  # type: ignore[attr-defined]
        runner.abort()
        assert runner._abort_requested is True  # type: ignore[attr-defined]
        assert active.aborted is True

    @pytest.mark.asyncio
    async def test_run_multi_turn_with_callback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        events.clear()
        monkeypatch.setattr(
            "myrm_agent_harness.eval.matrix.EvalRunner", _CallbackEvalRunner
        )
        runner = MatrixRunner(
            {"a": FakeExecutor()},
            on_case_complete=lambda pid, turn: events.append(("case", pid)),
        )
        multi = MultiTurnEvalCase(turns=[_case("t0"), _case("t1")])
        result = await runner.run_multi_turn([multi], manifest_builder=_manifest)
        assert [case.message for case in result.cases] == ["t0", "t1"]
        assert ("case", "a") in events
        assert result.stable_cases == [0, 1]

    @pytest.mark.asyncio
    async def test_run_multi_turn_flattens_cases(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "myrm_agent_harness.eval.matrix.EvalRunner", _FakeEvalRunner
        )
        runner = MatrixRunner({"a": FakeExecutor()})
        multi = MultiTurnEvalCase(turns=[_case("t0"), _case("t1")])
        result = await runner.run_multi_turn([multi], manifest_builder=_manifest)
        assert [case.message for case in result.cases] == ["t0", "t1"]
        assert result.stable_cases == [0, 1]
