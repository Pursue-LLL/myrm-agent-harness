"""Tests for eval protocol types."""

from __future__ import annotations

import pytest

from myrm_agent_harness.eval.protocols import (
    AgentExecutor,
    AgentResponse,
    EvalCase,
    EvalResult,
    EvalTimings,
    EvalTurnResult,
    MultiTurnEvalCase,
)


class TestEvalCaseFrozen:
    """EvalCase is frozen — immutable after creation."""

    def test_cannot_modify_message(self) -> None:
        case = EvalCase(message="hello")
        with pytest.raises(AttributeError):
            case.message = "world"  # type: ignore[misc]

    def test_cannot_modify_expected_tools(self) -> None:
        case = EvalCase(message="hello", expected_tools=["t"])
        with pytest.raises(AttributeError):
            case.expected_tools = []  # type: ignore[misc]

    def test_defaults(self) -> None:
        case = EvalCase(message="hello")
        assert case.expected_tools == []
        assert case.require_all is False
        assert case.metadata == {}


class TestMultiTurnEvalCase:
    def test_frozen(self) -> None:
        mt = MultiTurnEvalCase(turns=[EvalCase(message="a")])
        with pytest.raises(AttributeError):
            mt.turns = []  # type: ignore[misc]

    def test_metadata_default(self) -> None:
        mt = MultiTurnEvalCase(turns=[])
        assert mt.metadata == {}


class TestEvalTimings:
    def test_defaults(self) -> None:
        t = EvalTimings()
        assert t.total_ms == 0.0
        assert t.extra == {}

    def test_extra_field(self) -> None:
        t = EvalTimings(total_ms=100.0, extra={"llm_ms": 50.0})
        assert t.extra["llm_ms"] == 50.0


class TestAgentResponse:
    def test_defaults(self) -> None:
        r = AgentResponse(answer="hello")
        assert r.tools_called == []
        assert r.tool_call_details == []
        assert r.extra_timings == {}


class TestEvalResult:
    def test_empty_result(self) -> None:
        r = EvalResult()
        assert r.total_cases == 0
        assert r.pass_count == 0
        assert r.fail_count == 0
        assert r.error_count == 0
        assert r.skip_count == 0
        assert r.pass_rate == 0.0
        assert r.all_passed is True

    def test_all_passed_with_errors_is_false(self) -> None:
        r = EvalResult(
            turn_results=[
                EvalTurnResult(
                    case=EvalCase(message="test"),
                    response=AgentResponse(answer=""),
                    error="boom",
                )
            ]
        )
        assert r.all_passed is False


class TestAgentExecutorProtocol:
    def test_runtime_checkable(self) -> None:
        class GoodExecutor:
            async def execute(self, message: str, *, session_id: str | None = None) -> AgentResponse:
                return AgentResponse(answer="ok")

            async def create_session(self) -> str:
                return "s-1"

            def get_sandbox_executor(self):
                return None

        assert isinstance(GoodExecutor(), AgentExecutor)

    def test_non_conforming_rejected(self) -> None:
        class BadExecutor:
            pass

        assert not isinstance(BadExecutor(), AgentExecutor)
