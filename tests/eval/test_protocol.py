"""Tests for eval protocol types."""

from __future__ import annotations

import pytest

from myrm_agent_harness.eval.protocols import (
    AgentExecutor,
    AgentResponse,
    EvalCase,
    EvalManifest,
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


class TestEvalManifest:
    """EvalManifest — frozen environment snapshot for reproducibility."""

    def _make_manifest(self) -> EvalManifest:
        return EvalManifest(
            model_provider="openai",
            model_id="gpt-4o-2024-08-06",
            thinking_effort="medium",
            harness_version="0.1.0rc2",
            tool_policy=("web_search", "code_exec"),
            task_set_id="default",
            task_set_hash="abc123def456",
            prompt_fingerprint="sha256:deadbeef",
            budget_max_tokens=4096,
            timeout_seconds=120,
            created_at="2026-07-25T14:00:00+00:00",
        )

    def test_frozen(self) -> None:
        m = self._make_manifest()
        with pytest.raises(AttributeError):
            m.model_id = "other"  # type: ignore[misc]

    def test_defaults_profile_and_benchmark(self) -> None:
        m = self._make_manifest()
        assert m.profile_id == "default"
        assert m.benchmark_mode is False

    def test_custom_profile_and_benchmark(self) -> None:
        m = EvalManifest(
            model_provider="openai",
            model_id="gpt-4o",
            harness_version="0.1.0",
            tool_policy=(),
            task_set_id="ds-1",
            task_set_hash="abc",
            prompt_fingerprint="sha256:00",
            budget_max_tokens=2048,
            timeout_seconds=60,
            created_at="2026-08-01T00:00:00+00:00",
            profile_id="my-agent",
            benchmark_mode=True,
        )
        assert m.profile_id == "my-agent"
        assert m.benchmark_mode is True

    def test_to_dict_structure(self) -> None:
        m = self._make_manifest()
        d = m.to_dict()
        assert d["model_provider"] == "openai"
        assert d["model_id"] == "gpt-4o-2024-08-06"
        assert d["thinking_effort"] == "medium"
        assert d["harness_version"] == "0.1.0rc2"
        assert d["tool_policy"] == ["web_search", "code_exec"]
        assert d["task_set_id"] == "default"
        assert d["task_set_hash"] == "abc123def456"
        assert d["prompt_fingerprint"] == "sha256:deadbeef"
        assert d["budget_max_tokens"] == 4096
        assert d["timeout_seconds"] == 120
        assert d["created_at"] == "2026-07-25T14:00:00+00:00"
        assert d["profile_id"] == "default"
        assert d["benchmark_mode"] is False

    def test_to_dict_with_custom_profile(self) -> None:
        m = EvalManifest(
            model_provider="anthropic",
            model_id="claude-4",
            harness_version="0.2.0",
            tool_policy=("web_search",),
            task_set_id="ds-2",
            task_set_hash="def",
            prompt_fingerprint="sha256:ff",
            budget_max_tokens=8192,
            timeout_seconds=300,
            created_at="2026-08-01T12:00:00+00:00",
            profile_id="research-agent",
            benchmark_mode=True,
        )
        d = m.to_dict()
        assert d["profile_id"] == "research-agent"
        assert d["benchmark_mode"] is True

    def test_eval_result_manifest_none_by_default(self) -> None:
        r = EvalResult()
        assert r.manifest is None

    def test_eval_result_with_manifest(self) -> None:
        m = self._make_manifest()
        r = EvalResult(manifest=m)
        assert r.manifest is m

    def test_eval_result_to_dict_includes_manifest(self) -> None:
        m = self._make_manifest()
        r = EvalResult(
            turn_results=[
                EvalTurnResult(
                    case=EvalCase(message="test"),
                    response=AgentResponse(answer="ok"),
                    assertion_passed=True,
                )
            ],
            manifest=m,
        )
        d = r.to_dict()
        assert "manifest" in d
        assert d["manifest"]["model_id"] == "gpt-4o-2024-08-06"

    def test_eval_result_to_dict_no_manifest_key_when_none(self) -> None:
        r = EvalResult(
            turn_results=[
                EvalTurnResult(
                    case=EvalCase(message="test"),
                    response=AgentResponse(answer="ok"),
                )
            ],
        )
        d = r.to_dict()
        assert "manifest" not in d
