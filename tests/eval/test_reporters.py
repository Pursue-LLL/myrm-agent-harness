"""Tests for Eval Reporters."""

import json
from pathlib import Path

from myrm_agent_harness.eval.protocols import (
    AgentResponse,
    EvalCase,
    EvalResult,
    EvalTimings,
    EvalTurnResult,
)
from myrm_agent_harness.eval.reporters import JsonlReporter, MarkdownReporter


def test_jsonl_reporter(tmp_path: Path):
    report_path = tmp_path / "report.jsonl"
    reporter = JsonlReporter(report_path)

    result = EvalResult(
        turn_results=[
            EvalTurnResult(
                case=EvalCase(message="test1", expected_tools=["tool1"]),
                response=AgentResponse(answer="ok", tools_called=["tool1"]),
                assertion_passed=True,
                assertion_details="Passed",
                timings=EvalTimings(total_ms=100),
            ),
            EvalTurnResult(
                case=EvalCase(message="test2", expected_tools=["tool2"]),
                response=AgentResponse(answer="fail", tools_called=["tool3"]),
                assertion_passed=False,
                assertion_details="Failed",
                timings=EvalTimings(total_ms=200),
                error="Some error",
            ),
        ],
        total_ms=300,
    )

    reporter.report(result)

    assert report_path.exists()

    with report_path.open("r") as f:
        lines = f.readlines()

    assert len(lines) == 3

    summary = json.loads(lines[0])
    assert summary["type"] == "summary"
    assert summary["total_cases"] == 2
    assert summary["pass_count"] == 1
    assert summary["fail_count"] == 1

    turn1 = json.loads(lines[1])
    assert turn1["type"] == "turn"
    assert turn1["case"]["message"] == "test1"
    assert turn1["passed"] is True
    assert turn1["time_secs"] == 0.1
    assert turn1["usage"] == {}
    assert turn1["details"] == "Passed"
    assert turn1["actual_tools"] == ["tool1"]

    turn2 = json.loads(lines[2])
    assert turn2["type"] == "turn"
    assert turn2["case"]["message"] == "test2"
    assert turn2["passed"] is False
    assert turn2["error"] == "Some error"
    assert turn2["time_secs"] == 0.2

    # Verify summary aggregates
    assert summary["avg_time_secs"] == 0.15
    assert summary["avg_total_tokens"] == 0


def test_markdown_reporter(tmp_path: Path):
    report_path = tmp_path / "report.md"
    reporter = MarkdownReporter(report_path)

    result = EvalResult(
        turn_results=[
            EvalTurnResult(
                case=EvalCase(message="test1", expected_tools=["tool1"]),
                response=AgentResponse(answer="ok", tools_called=["tool1"]),
                assertion_passed=True,
                assertion_details="Passed",
                timings=EvalTimings(total_ms=100),
            ),
            EvalTurnResult(
                case=EvalCase(message="test2", expected_tools=["tool2"]),
                response=AgentResponse(answer="fail", tools_called=["tool3"]),
                assertion_passed=False,
                assertion_details="Failed",
                timings=EvalTimings(total_ms=200),
                error="Some error",
            ),
        ],
        total_ms=300,
    )

    reporter.report(result)

    assert report_path.exists()

    content = report_path.read_text()

    assert "# Evaluation Report" in content
    assert "**Total Cases**: 2" in content
    assert "**Passed**: 1" in content
    assert "**Failed**: 1" in content
    assert " PASS" in content
    assert " ERROR" in content
    assert "Some error" in content
