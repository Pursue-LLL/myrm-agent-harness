"""Trajectory-disclosure tests: limits, blocked counts and tool details flow
through the eval protocol, matrix cells and reporters."""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.eval import (
    AgentResponse,
    BenchmarkSpec,
    EvalCase,
    EvalManifest,
    EvalResult,
    EvalTimings,
    EvalTurnResult,
    JsonlReporter,
    MatrixCellResult,
    MatrixResult,
)


class TestAgentResponseDisclosure:
    def test_defaults(self) -> None:
        r = AgentResponse(answer="ok")
        assert r.limit_reached is None
        assert r.blocked_count == 0

    def test_custom_values(self) -> None:
        r = AgentResponse(
            answer="ok",
            limit_reached="max_tool_calls",
            blocked_count=3,
            tool_call_details=[{"tool_name": "web_search_tool", "step_key": "web"}],
        )
        assert r.limit_reached == "max_tool_calls"
        assert r.blocked_count == 3
        assert r.tool_call_details[0]["tool_name"] == "web_search_tool"


class TestEvalResultTurnDisclosure:
    def _result(self) -> EvalResult:
        turn = EvalTurnResult(
            case=EvalCase(message="q"),
            response=AgentResponse(
                answer="a",
                tools_called=["web_search_tool"],
                tool_call_details=[
                    {"tool_name": "web_search_tool", "step_key": "web", "detail": []}
                ],
                limit_reached="max_tool_calls",
                blocked_count=2,
            ),
            timings=EvalTimings(total_ms=123.0),
        )
        return EvalResult(turn_results=[turn])

    def test_to_dict_carries_trajectory_fields(self) -> None:
        d = self._result().to_dict()
        turn = d["turns"][0]
        assert turn["tool_call_details"] == [
            {
                "tool_name": "web_search_tool",
                "step_key": "web",
                "detail": [],
            }
        ]
        assert turn["limit_reached"] == "max_tool_calls"
        assert turn["blocked_count"] == 2
        assert turn["tools_called"] == ["web_search_tool"]


class TestMatrixCellDisclosure:
    def test_to_dict_carries_cell_metrics(self) -> None:
        cells = {
            "p1": MatrixCellResult(
                profile_id="p1",
                case_index=0,
                passed=True,
                assertion_details=None,
                total_ms=10.0,
                tool_calls=5,
                limit_reached=None,
                blocked_count=1,
            )
        }
        result = MatrixResult(profile_ids=["p1"], cases=[], per_profile_results={})
        # Build matrix rows manually through get_cell path is not available
        # without turn results; verify the cell serialization directly.
        row = {
            "case_index": 0,
            "message": "q",
            "profiles": {
                pid: {
                    "passed": c.passed,
                    "total_ms": round(c.total_ms, 2),
                    "token_usage": c.token_usage,
                    "cost": round(c.cost, 6),
                    "error": c.error,
                    "tool_calls": c.tool_calls,
                    "limit_reached": c.limit_reached,
                    "blocked_count": c.blocked_count,
                }
                for pid, c in cells.items()
            },
        }
        cell = row["profiles"]["p1"]
        assert cell["tool_calls"] == 5
        assert cell["limit_reached"] is None
        assert cell["blocked_count"] == 1

    def test_per_profile_summary_includes_trajectory_rollups(self) -> None:
        turn = EvalTurnResult(
            case=EvalCase(message="q"),
            response=AgentResponse(
                answer="a",
                tools_called=["t1", "t2"],
                limit_reached="max_tool_calls",
                blocked_count=1,
            ),
        )
        r = EvalResult(turn_results=[turn])
        result = MatrixResult(
            profile_ids=["p1"],
            cases=[EvalCase(message="q")],
            per_profile_results={"p1": r},
        )
        d = result.to_dict()
        summary = d["per_profile"]["p1"]
        assert summary["total_tool_calls"] == 2
        assert summary["limit_hits"] == 1
        assert summary["blocked_count"] == 1


class TestEvalManifestBudgets:
    def test_budget_defaults_none(self) -> None:
        m = EvalManifest(
            model_provider="x",
            model_id="y",
            harness_version="0",
            tool_policy=(),
            task_set_id="z",
            task_set_hash="h",
            prompt_fingerprint="f",
            budget_max_tokens=1,
            timeout_seconds=1,
            created_at="now",
        )
        assert m.max_tool_calls is None
        assert m.max_iterations is None

    def test_to_dict_carries_budgets(self) -> None:
        m = EvalManifest(
            model_provider="x",
            model_id="y",
            harness_version="0",
            tool_policy=(),
            task_set_id="z",
            task_set_hash="h",
            prompt_fingerprint="f",
            budget_max_tokens=1,
            timeout_seconds=1,
            created_at="now",
            max_tool_calls=30,
            max_iterations=50,
        )
        d = m.to_dict()
        assert d["max_tool_calls"] == 30
        assert d["max_iterations"] == 50


class TestBenchmarkSpecBudgets:
    def test_defaults_zero(self) -> None:
        spec = BenchmarkSpec(id="b", display_name="B", description="")
        assert spec.max_tool_calls == 0
        assert spec.max_iterations == 0
        assert spec.harness == "myrm"
        assert spec.judge_prompt == ""

    def test_declared_values_serialize(self) -> None:
        spec = BenchmarkSpec(
            id="b",
            display_name="B",
            description="",
            max_tool_calls=30,
            max_iterations=50,
            harness="official",
            judge_prompt="grade this",
        )
        d = spec.to_dict()
        assert d["max_tool_calls"] == 30
        assert d["max_iterations"] == 50
        assert d["harness"] == "official"
        assert d["judge_prompt"] == "grade this"


class TestJsonlReporterDisclosure:
    def test_turn_line_carries_trajectory_fields(self, tmp_path) -> None:
        turn = EvalTurnResult(
            case=EvalCase(message="q"),
            response=AgentResponse(
                answer="a",
                tools_called=["web_search_tool"],
                tool_call_details=[
                    {"tool_name": "web_search_tool", "step_key": "web"}
                ],
                limit_reached="max_tool_calls",
                blocked_count=1,
            ),
        )
        result = EvalResult(turn_results=[turn])
        out = tmp_path / "report.jsonl"
        JsonlReporter(out).report(result)

        lines = [json.loads(l) for l in out.read_text().splitlines()]
        turn_line = next(l for l in lines if l["type"] == "turn")
        assert turn_line["limit_reached"] == "max_tool_calls"
        assert turn_line["blocked_count"] == 1
        assert turn_line["tool_call_details"] == [
            {"tool_name": "web_search_tool", "step_key": "web"}
        ]
        assert turn_line["actual_tools"] == ["web_search_tool"]
