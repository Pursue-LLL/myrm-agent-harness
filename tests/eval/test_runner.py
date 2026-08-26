"""Tests for EvalRunner."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.eval.protocols import (
    AgentResponse,
    EvalCase,
    EvalTurnResult,
    MultiTurnEvalCase,
)
from myrm_agent_harness.eval.runner import EvalRunner


class MockExecutor:
    """Mock AgentExecutor for testing."""

    def __init__(
        self,
        responses: dict[str, AgentResponse] | None = None,
        *,
        default_response: AgentResponse | None = None,
        fail_on: set[str] | None = None,
    ) -> None:
        self._responses = responses or {}
        self._default = default_response or AgentResponse(answer="ok")
        self._fail_on = fail_on or set()
        self._call_log: list[tuple[str, str | None]] = []
        self._session_counter = 0

    async def execute(
        self, message: str, *, session_id: str | None = None
    ) -> AgentResponse:
        self._call_log.append((message, session_id))
        if message in self._fail_on:
            msg = f"Simulated failure for: {message}"
            raise RuntimeError(msg)
        return self._responses.get(message, self._default)

    async def create_session(self) -> str:
        self._session_counter += 1
        return f"session-{self._session_counter}"


class TestEvalRunnerSingleTurn:
    """Tests for single-turn eval execution."""

    @pytest.mark.asyncio
    async def test_basic_pass(self) -> None:
        executor = MockExecutor(
            responses={
                "Search for Python": AgentResponse(
                    answer="Here are results",
                    tools_called=["web_search"],
                )
            }
        )
        runner = EvalRunner(executor)
        result = await runner.run(
            [
                EvalCase(
                    message="Search for Python",
                    expected_tools=["web_search"],
                )
            ]
        )

        assert result.total_cases == 1
        assert result.pass_count == 1
        assert result.all_passed is True
        assert result.total_ms > 0

    @pytest.mark.asyncio
    async def test_basic_fail(self) -> None:
        executor = MockExecutor(
            default_response=AgentResponse(
                answer="I don't know",
                tools_called=["chat"],
            )
        )
        runner = EvalRunner(executor)
        result = await runner.run(
            [
                EvalCase(
                    message="Search for Python",
                    expected_tools=["web_search"],
                )
            ]
        )

        assert result.fail_count == 1
        assert result.all_passed is False

    @pytest.mark.asyncio
    async def test_no_assertions_skip(self) -> None:
        executor = MockExecutor()
        runner = EvalRunner(executor)
        result = await runner.run([EvalCase(message="Hello")])

        assert result.skip_count == 1
        assert result.pass_count == 0
        assert result.fail_count == 0
        assert result.all_passed is True

    @pytest.mark.asyncio
    async def test_error_handling(self) -> None:
        executor = MockExecutor(fail_on={"bad message"})
        runner = EvalRunner(executor)
        result = await runner.run(
            [
                EvalCase(message="bad message", expected_tools=["web_search"]),
                EvalCase(message="good message"),
            ]
        )

        assert result.error_count == 1
        assert result.turn_results[0].error is not None
        assert result.turn_results[1].error is None

    @pytest.mark.asyncio
    async def test_concurrent_execution(self) -> None:
        call_times: list[float] = []

        class SlowExecutor:
            def __init__(self) -> None:
                self._counter = 0

            async def execute(
                self, message: str, *, session_id: str | None = None
            ) -> AgentResponse:
                import time

                start = time.perf_counter()
                await asyncio.sleep(0.05)
                call_times.append(time.perf_counter() - start)
                return AgentResponse(answer="ok", tools_called=["tool"])

            async def create_session(self) -> str:
                self._counter += 1
                return f"s-{self._counter}"

        runner = EvalRunner(SlowExecutor(), max_concurrency=5)
        cases = [
            EvalCase(message=f"msg-{i}", expected_tools=["tool"]) for i in range(5)
        ]
        result = await runner.run(cases)

        assert result.pass_count == 5
        assert result.total_ms < 300

    @pytest.mark.asyncio
    async def test_progress_callback(self) -> None:
        completed: list[EvalTurnResult] = []
        executor = MockExecutor(
            default_response=AgentResponse(answer="ok", tools_called=["tool"])
        )
        runner = EvalRunner(executor, on_case_complete=completed.append)

        await runner.run(
            [
                EvalCase(message="a", expected_tools=["tool"]),
                EvalCase(message="b", expected_tools=["tool"]),
            ]
        )

        assert len(completed) == 2


class TestEvalRunnerMultiTurn:
    """Tests for multi-turn eval execution."""

    @pytest.mark.asyncio
    async def test_multi_turn_basic(self) -> None:
        executor = MockExecutor(
            responses={
                "Hello": AgentResponse(answer="Hi", tools_called=[]),
                "Search X": AgentResponse(
                    answer="Found X", tools_called=["web_search"]
                ),
            }
        )
        runner = EvalRunner(executor)
        result = await runner.run_multi_turn(
            [
                MultiTurnEvalCase(
                    turns=[
                        EvalCase(message="Hello"),
                        EvalCase(message="Search X", expected_tools=["web_search"]),
                    ]
                )
            ]
        )

        assert result.total_cases == 2
        assert result.pass_count == 1
        assert result.skip_count == 1

    @pytest.mark.asyncio
    async def test_multi_turn_same_session(self) -> None:
        executor = MockExecutor()
        runner = EvalRunner(executor)
        await runner.run_multi_turn(
            [
                MultiTurnEvalCase(
                    turns=[
                        EvalCase(message="msg1"),
                        EvalCase(message="msg2"),
                    ]
                )
            ]
        )

        session_ids = [sid for _, sid in executor._call_log]
        assert session_ids[0] == session_ids[1]
        assert session_ids[0] is not None

    @pytest.mark.asyncio
    async def test_multi_turn_error_aborts_session(self) -> None:
        executor = MockExecutor(fail_on={"fail_msg"})
        runner = EvalRunner(executor)
        result = await runner.run_multi_turn(
            [
                MultiTurnEvalCase(
                    turns=[
                        EvalCase(message="fail_msg"),
                        EvalCase(message="should_not_run"),
                    ]
                )
            ]
        )

        assert result.total_cases == 1
        assert result.error_count == 1


class TestEvalResult:
    """Tests for EvalResult reporting."""

    @pytest.mark.asyncio
    async def test_to_dict(self) -> None:
        executor = MockExecutor(
            default_response=AgentResponse(answer="ok", tools_called=["t"])
        )
        runner = EvalRunner(executor)
        result = await runner.run([EvalCase(message="test", expected_tools=["t"])])

        d = result.to_dict()
        assert d["total_cases"] == 1
        assert d["pass_count"] == 1
        assert d["all_passed"] is True
        assert isinstance(d["turns"], list)

    @pytest.mark.asyncio
    async def test_to_json(self) -> None:
        import json

        executor = MockExecutor()
        runner = EvalRunner(executor)
        result = await runner.run([EvalCase(message="test")])

        j = result.to_json()
        parsed = json.loads(j)
        assert "total_cases" in parsed

    @pytest.mark.asyncio
    async def test_summary(self) -> None:
        executor = MockExecutor(
            default_response=AgentResponse(answer="ok", tools_called=["t"])
        )
        runner = EvalRunner(executor)
        result = await runner.run([EvalCase(message="test", expected_tools=["t"])])

        s = result.summary()
        assert "1/1 passed" in s
        assert "100%" in s

    @pytest.mark.asyncio
    async def test_pass_rate_no_assertions(self) -> None:
        executor = MockExecutor()
        runner = EvalRunner(executor)
        result = await runner.run([EvalCase(message="test")])

        assert result.pass_rate == 0.0


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_empty_cases_list(self) -> None:
        executor = MockExecutor()
        runner = EvalRunner(executor)
        result = await runner.run([])

        assert result.total_cases == 0
        assert result.all_passed is True
        assert result.pass_rate == 0.0

    @pytest.mark.asyncio
    async def test_empty_multi_turn_list(self) -> None:
        executor = MockExecutor()
        runner = EvalRunner(executor)
        result = await runner.run_multi_turn([])

        assert result.total_cases == 0

    @pytest.mark.asyncio
    async def test_max_concurrency_negative_clamped(self) -> None:
        """Negative max_concurrency should be clamped to 1."""
        executor = MockExecutor(
            default_response=AgentResponse(answer="ok", tools_called=["t"])
        )
        runner = EvalRunner(executor, max_concurrency=-5)
        result = await runner.run([EvalCase(message="test", expected_tools=["t"])])
        assert result.pass_count == 1

    @pytest.mark.asyncio
    async def test_max_concurrency_zero_clamped(self) -> None:
        executor = MockExecutor(
            default_response=AgentResponse(answer="ok", tools_called=["t"])
        )
        runner = EvalRunner(executor, max_concurrency=0)
        result = await runner.run([EvalCase(message="test", expected_tools=["t"])])
        assert result.pass_count == 1

    @pytest.mark.asyncio
    async def test_create_session_failure(self) -> None:
        """create_session raising should be captured as error."""

        class FailSessionExecutor:
            async def execute(
                self, message: str, *, session_id: str | None = None
            ) -> AgentResponse:
                return AgentResponse(answer="ok")

            async def create_session(self) -> str:
                raise ConnectionError("DB unavailable")

        runner = EvalRunner(FailSessionExecutor())
        result = await runner.run([EvalCase(message="test", expected_tools=["t"])])

        assert result.error_count == 1
        assert "DB unavailable" in (result.turn_results[0].error or "")

    @pytest.mark.asyncio
    async def test_mixed_pass_fail_skip_error(self) -> None:
        executor = MockExecutor(
            responses={
                "pass": AgentResponse(answer="ok", tools_called=["t"]),
                "fail": AgentResponse(answer="nope", tools_called=["wrong"]),
                "skip": AgentResponse(answer="hi"),
            },
            fail_on={"error"},
        )
        runner = EvalRunner(executor)
        result = await runner.run(
            [
                EvalCase(message="pass", expected_tools=["t"]),
                EvalCase(message="fail", expected_tools=["t"]),
                EvalCase(message="skip"),
                EvalCase(message="error", expected_tools=["t"]),
            ]
        )

        assert result.pass_count == 1
        assert result.fail_count == 1
        assert result.skip_count == 1
        assert result.error_count == 1
        assert result.total_cases == 4
        assert result.all_passed is False

    @pytest.mark.asyncio
    async def test_all_failed(self) -> None:
        executor = MockExecutor(
            default_response=AgentResponse(answer="nope", tools_called=["wrong"])
        )
        runner = EvalRunner(executor)
        result = await runner.run(
            [
                EvalCase(message="a", expected_tools=["t"]),
                EvalCase(message="b", expected_tools=["t"]),
            ]
        )

        assert result.fail_count == 2
        assert result.pass_rate == 0.0
        assert result.all_passed is False

    @pytest.mark.asyncio
    async def test_progress_callback_error_does_not_abort(self) -> None:
        """on_case_complete raising should not abort the run."""

        def bad_callback(result: EvalTurnResult) -> None:
            raise ValueError("callback error")

        executor = MockExecutor(
            default_response=AgentResponse(answer="ok", tools_called=["t"])
        )
        runner = EvalRunner(executor, on_case_complete=bad_callback)
        result = await runner.run(
            [
                EvalCase(message="a", expected_tools=["t"]),
                EvalCase(message="b", expected_tools=["t"]),
            ]
        )

        assert result.pass_count == 2

    @pytest.mark.asyncio
    async def test_multi_turn_concurrent_multiple_sessions(self) -> None:
        """Multiple multi-turn sessions should run concurrently."""
        executor = MockExecutor(
            default_response=AgentResponse(answer="ok", tools_called=["t"])
        )
        runner = EvalRunner(executor, max_concurrency=3)
        cases = [
            MultiTurnEvalCase(
                turns=[
                    EvalCase(message=f"s{i}-t1", expected_tools=["t"]),
                    EvalCase(message=f"s{i}-t2", expected_tools=["t"]),
                ]
            )
            for i in range(3)
        ]
        result = await runner.run_multi_turn(cases)

        assert result.total_cases == 6
        assert result.pass_count == 6

    @pytest.mark.asyncio
    async def test_multi_turn_on_turn_fail_continue(self) -> None:
        """Default 'continue' runs all turns even after assertion failure."""
        executor = MockExecutor(
            responses={
                "t1": AgentResponse(answer="ok", tools_called=["t"]),
                "t2": AgentResponse(answer="bad", tools_called=["wrong"]),
                "t3": AgentResponse(answer="ok", tools_called=["t"]),
            }
        )
        runner = EvalRunner(executor)
        result = await runner.run_multi_turn(
            [
                MultiTurnEvalCase(
                    turns=[
                        EvalCase(message="t1", expected_tools=["t"]),
                        EvalCase(message="t2", expected_tools=["t"]),
                        EvalCase(message="t3", expected_tools=["t"]),
                    ],
                    on_turn_fail="continue",
                )
            ]
        )

        assert result.total_cases == 3
        assert result.pass_count == 2
        assert result.fail_count == 1

    @pytest.mark.asyncio
    async def test_multi_turn_on_turn_fail_skip_remaining(self) -> None:
        """'skip_remaining' emits skipped placeholders for unexecuted turns."""
        executor = MockExecutor(
            responses={
                "t1": AgentResponse(answer="ok", tools_called=["t"]),
                "t2": AgentResponse(answer="bad", tools_called=["wrong"]),
                "t3": AgentResponse(answer="ok", tools_called=["t"]),
            }
        )
        runner = EvalRunner(executor)
        result = await runner.run_multi_turn(
            [
                MultiTurnEvalCase(
                    turns=[
                        EvalCase(message="t1", expected_tools=["t"]),
                        EvalCase(message="t2", expected_tools=["t"]),
                        EvalCase(message="t3", expected_tools=["t"]),
                    ],
                    on_turn_fail="skip_remaining",
                )
            ]
        )

        assert result.total_cases == 3
        assert result.pass_count == 1
        assert result.fail_count == 1
        assert result.skip_count == 1
        assert (
            result.turn_results[2].assertion_details
            == "skipped: prior turn assertion failed"
        )

    @pytest.mark.asyncio
    async def test_multi_turn_on_turn_fail_abort(self) -> None:
        """'abort' stops immediately without emitting skipped turns."""
        executor = MockExecutor(
            responses={
                "t1": AgentResponse(answer="ok", tools_called=["t"]),
                "t2": AgentResponse(answer="bad", tools_called=["wrong"]),
                "t3": AgentResponse(answer="ok", tools_called=["t"]),
            }
        )
        runner = EvalRunner(executor)
        result = await runner.run_multi_turn(
            [
                MultiTurnEvalCase(
                    turns=[
                        EvalCase(message="t1", expected_tools=["t"]),
                        EvalCase(message="t2", expected_tools=["t"]),
                        EvalCase(message="t3", expected_tools=["t"]),
                    ],
                    on_turn_fail="abort",
                )
            ]
        )

        assert result.total_cases == 2
        assert result.pass_count == 1
        assert result.fail_count == 1

    @pytest.mark.asyncio
    async def test_multi_turn_on_turn_fail_first_turn_fails(self) -> None:
        """Abort on first turn failure skips all subsequent turns."""
        executor = MockExecutor(
            responses={
                "t1": AgentResponse(answer="bad", tools_called=["wrong"]),
                "t2": AgentResponse(answer="ok", tools_called=["t"]),
            }
        )
        runner = EvalRunner(executor)
        result = await runner.run_multi_turn(
            [
                MultiTurnEvalCase(
                    turns=[
                        EvalCase(message="t1", expected_tools=["t"]),
                        EvalCase(message="t2", expected_tools=["t"]),
                    ],
                    on_turn_fail="abort",
                )
            ]
        )

        assert result.total_cases == 1
        assert result.fail_count == 1

    @pytest.mark.asyncio
    async def test_multi_turn_error_aborts_regardless_of_strategy(self) -> None:
        """Execution errors always abort, even with on_turn_fail='continue'."""
        executor = MockExecutor(fail_on={"t2"})
        runner = EvalRunner(executor)
        result = await runner.run_multi_turn(
            [
                MultiTurnEvalCase(
                    turns=[
                        EvalCase(message="t1"),
                        EvalCase(message="t2"),
                        EvalCase(message="t3"),
                    ],
                    on_turn_fail="continue",
                )
            ]
        )

        assert result.total_cases == 2
        assert result.error_count == 1

    @pytest.mark.asyncio
    async def test_multi_turn_all_pass_with_abort_strategy(self) -> None:
        """All turns pass — abort strategy has no effect."""
        executor = MockExecutor(
            default_response=AgentResponse(answer="ok", tools_called=["t"])
        )
        runner = EvalRunner(executor)
        result = await runner.run_multi_turn(
            [
                MultiTurnEvalCase(
                    turns=[
                        EvalCase(message="t1", expected_tools=["t"]),
                        EvalCase(message="t2", expected_tools=["t"]),
                    ],
                    on_turn_fail="abort",
                )
            ]
        )

        assert result.total_cases == 2
        assert result.pass_count == 2

    @pytest.mark.asyncio
    async def test_multi_turn_skip_remaining_progress_callback(self) -> None:
        """Skipped turns should trigger the progress callback."""
        completed: list[EvalTurnResult] = []
        executor = MockExecutor(
            responses={
                "t1": AgentResponse(answer="bad", tools_called=["wrong"]),
                "t2": AgentResponse(answer="ok", tools_called=["t"]),
            }
        )
        runner = EvalRunner(executor, on_case_complete=completed.append)
        await runner.run_multi_turn(
            [
                MultiTurnEvalCase(
                    turns=[
                        EvalCase(message="t1", expected_tools=["t"]),
                        EvalCase(message="t2", expected_tools=["t"]),
                    ],
                    on_turn_fail="skip_remaining",
                )
            ]
        )

        assert len(completed) == 2
        assert completed[1].assertion_details == "skipped: prior turn assertion failed"

    @pytest.mark.asyncio
    async def test_multi_turn_middle_pass_last_fail(self) -> None:
        executor = MockExecutor(
            responses={
                "ok": AgentResponse(answer="ok", tools_called=["t"]),
                "bad": AgentResponse(answer="nope", tools_called=["wrong"]),
            }
        )
        runner = EvalRunner(executor)
        result = await runner.run_multi_turn(
            [
                MultiTurnEvalCase(
                    turns=[
                        EvalCase(message="ok", expected_tools=["t"]),
                        EvalCase(message="bad", expected_tools=["t"]),
                    ]
                )
            ]
        )

        assert result.pass_count == 1
        assert result.fail_count == 1

    @pytest.mark.asyncio
    async def test_require_all_integration(self) -> None:
        """require_all=True flows through runner correctly."""
        executor = MockExecutor(
            responses={
                "both": AgentResponse(
                    answer="ok", tools_called=["web_search", "code_exec"]
                ),
            }
        )
        runner = EvalRunner(executor)
        result = await runner.run(
            [
                EvalCase(
                    message="both",
                    expected_tools=["web_search", "code_exec"],
                    require_all=True,
                )
            ]
        )
        assert result.pass_count == 1

    @pytest.mark.asyncio
    async def test_to_dict_all_fields(self) -> None:
        """Verify to_dict contains all expected fields."""
        executor = MockExecutor(
            default_response=AgentResponse(answer="ok", tools_called=["t"])
        )
        runner = EvalRunner(executor)
        result = await runner.run([EvalCase(message="test", expected_tools=["t"])])

        d = result.to_dict()
        required_keys = {
            "total_cases",
            "pass_count",
            "fail_count",
            "error_count",
            "skip_count",
            "pass_rate",
            "all_passed",
            "total_ms",
            "total_tokens",
            "total_cost",
            "turns",
        }
        assert required_keys == set(d.keys())

        turn = d["turns"][0]
        turn_keys = {
            "message",
            "expected_tools",
            "sandbox_assertions",
            "state_assertions",
            "semantic_assertions",
            "retrieval_assertions",
            "compaction_assertions",
            "tools_called",
            "tool_call_details",
            "retrieved_hits",
            "limit_reached",
            "blocked_count",
            "assertion_passed",
            "assertion_details",
            "post_episode_passed",
            "canary_verified",
            "contamination_audit",
            "scores",
            "total_ms",
            "token_usage",
            "cost",
            "error",
        }
        assert turn_keys == set(turn.keys())

    @pytest.mark.asyncio
    async def test_timings_recorded(self) -> None:
        executor = MockExecutor()
        runner = EvalRunner(executor)
        result = await runner.run([EvalCase(message="test")])

        assert result.total_ms > 0
        assert result.turn_results[0].timings.total_ms > 0

    @pytest.mark.asyncio
    async def test_extra_timings_propagated(self) -> None:
        """AgentResponse.extra_timings should appear in EvalTimings.extra."""
        executor = MockExecutor(
            default_response=AgentResponse(
                answer="ok",
                tools_called=["t"],
                extra_timings={"llm_first_token_ms": 150.0},
            )
        )
        runner = EvalRunner(executor)
        result = await runner.run([EvalCase(message="test", expected_tools=["t"])])

        assert result.turn_results[0].timings.extra["llm_first_token_ms"] == 150.0

    @pytest.mark.asyncio
    async def test_multi_turn_abort_skips_all_sessions(self) -> None:
        """abort() should prevent multi-turn sessions from executing."""
        call_count = 0

        class CountingExecutor:
            async def create_session(self) -> str:
                return "s"

            async def execute(
                self, message: str, *, session_id: str | None = None
            ) -> AgentResponse:
                nonlocal call_count
                call_count += 1
                return AgentResponse(answer="ok", tools_called=["t"])

        executor = CountingExecutor()
        runner = EvalRunner(executor, max_concurrency=1)
        runner.abort()

        result = await runner.run_multi_turn(
            [
                MultiTurnEvalCase(
                    turns=[
                        EvalCase(message="t1", expected_tools=["t"]),
                        EvalCase(message="t2", expected_tools=["t"]),
                    ]
                ),
                MultiTurnEvalCase(
                    turns=[
                        EvalCase(message="t3", expected_tools=["t"]),
                    ]
                ),
            ]
        )

        assert result.total_cases == 0
        assert call_count == 0


@pytest.mark.asyncio
async def test_run_abort_before_start() -> None:
    """Aborting before run() starts yields zero cases (semaphore-inner guard)."""
    executor = MockExecutor(
        default_response=AgentResponse(answer="ok", tools_called=["t"])
    )
    runner = EvalRunner(executor)
    runner.abort()
    result = await runner.run(
        [
            EvalCase(message="a", expected_tools=["t"]),
            EvalCase(message="b", expected_tools=["t"]),
        ]
    )
    assert result.total_cases == 0


@pytest.mark.asyncio
async def test_sandbox_and_state_assertions_execute(tmp_path, monkeypatch) -> None:
    """Sandbox + state assertions run inside the runner and feed scores."""
    from myrm_agent_harness.eval.protocols import SandboxAssertion, StateAssertion
    from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
    from myrm_agent_harness.toolkits.code_execution.executors.local import LocalExecutor

    def _fake(**_kwargs):
        from myrm_agent_harness.toolkits.code_execution.sandbox.providers.null import (
            NullProvider,
        )
        from myrm_agent_harness.toolkits.code_execution.sandbox.sandbox_types import (
            SandboxStatus,
        )

        return (
            NullProvider(),
            SandboxStatus(enabled=False, provider_name="null", reason="test"),
        )

    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detect_sandbox_provider",
        _fake,
    )
    monkeypatch.setattr(
        "myrm_agent_harness.toolkits.code_execution.sandbox.detector.detect_sandbox_provider",
        _fake,
    )

    target = tmp_path / "hello.txt"
    target.write_text("hello world")
    sandbox = LocalExecutor(ExecutionConfig())
    sandbox.bind_workspace(str(tmp_path))

    class SandboxCapableExecutor(MockExecutor):
        def get_sandbox_executor(
            self, *, session_id: str | None = None
        ) -> LocalExecutor:
            return sandbox

    runner = EvalRunner(
        SandboxCapableExecutor(
            default_response=AgentResponse(answer="ok", tools_called=["t"])
        )
    )
    result = await runner.run(
        [
            EvalCase(
                message="test",
                expected_tools=["t"],
                sandbox_assertions=[
                    SandboxAssertion(type="file_exists", target=str(target))
                ],
                state_assertions=[StateAssertion(type="contains", expected="ok")],
            )
        ]
    )
    assert result.pass_count == 1
