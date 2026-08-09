"""Tests for Eval Reporters."""

import json
from pathlib import Path

from myrm_agent_harness.eval.protocols import (
    AgentResponse,
    EvalCase,
    EvalManifest,
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
                scores={"pass_rate": 0.5, "tests_passed": 1.0, "tests_total": 2.0},
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
    assert turn2["scores"] == {"pass_rate": 0.5, "tests_passed": 1.0, "tests_total": 2.0}

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
                scores={"pass_rate": 0.5, "tests_passed": 1.0, "tests_total": 2.0},
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
    assert "**Scores**: `pass_rate: 0.5, tests_passed: 1, tests_total: 2`" in content


def _make_manifest() -> EvalManifest:
    return EvalManifest(
        model_provider="openai",
        model_id="gpt-4o-2024-08-06",
        thinking_effort="medium",
        harness_version="0.1.0rc2",
        tool_policy=("web_search", "code_exec"),
        task_set_id="default",
        task_set_hash="abc123def456",
        prompt_fingerprint="sha256:deadbeef1234",
        budget_max_tokens=4096,
        timeout_seconds=120,
        created_at="2026-07-25T14:00:00+00:00",
    )


def test_jsonl_reporter_with_manifest(tmp_path: Path):
    report_path = tmp_path / "report_manifest.jsonl"
    reporter = JsonlReporter(report_path)

    manifest = _make_manifest()
    result = EvalResult(
        turn_results=[
            EvalTurnResult(
                case=EvalCase(message="test"),
                response=AgentResponse(answer="ok"),
                assertion_passed=True,
                timings=EvalTimings(total_ms=50),
            ),
        ],
        total_ms=50,
        manifest=manifest,
    )

    reporter.report(result)

    with report_path.open("r") as f:
        lines = f.readlines()

    summary = json.loads(lines[0])
    assert summary["type"] == "summary"
    assert "manifest" in summary
    assert summary["manifest"]["model_provider"] == "openai"
    assert summary["manifest"]["model_id"] == "gpt-4o-2024-08-06"
    assert summary["manifest"]["tool_policy"] == ["web_search", "code_exec"]
    assert summary["manifest"]["prompt_fingerprint"] == "sha256:deadbeef1234"


def test_jsonl_reporter_without_manifest_no_key(tmp_path: Path):
    report_path = tmp_path / "report_no_manifest.jsonl"
    reporter = JsonlReporter(report_path)

    result = EvalResult(
        turn_results=[
            EvalTurnResult(
                case=EvalCase(message="test"),
                response=AgentResponse(answer="ok"),
                assertion_passed=True,
                timings=EvalTimings(total_ms=50),
            ),
        ],
        total_ms=50,
    )

    reporter.report(result)

    with report_path.open("r") as f:
        lines = f.readlines()

    summary = json.loads(lines[0])
    assert "manifest" not in summary


def test_markdown_reporter_with_manifest(tmp_path: Path):
    report_path = tmp_path / "report_manifest.md"
    reporter = MarkdownReporter(report_path)

    manifest = _make_manifest()
    result = EvalResult(
        turn_results=[
            EvalTurnResult(
                case=EvalCase(message="test"),
                response=AgentResponse(answer="ok"),
                assertion_passed=True,
                timings=EvalTimings(total_ms=50),
            ),
        ],
        total_ms=50,
        manifest=manifest,
    )

    reporter.report(result)

    content = report_path.read_text()
    assert "## Environment" in content
    assert "openai/gpt-4o-2024-08-06" in content
    assert "0.1.0rc2" in content
    assert "web_search, code_exec" in content


def test_reporters_include_avg_pass_rate_tokens_cost(tmp_path: Path):
    """avg_pass_rate + token/cost lines surface in both reporters."""
    turn = EvalTurnResult(
        case=EvalCase(message="suite case", expected_tools=["tool"]),
        response=AgentResponse(
            answer="ok",
            tools_called=["tool"],
            token_usage={"total_tokens": 1200, "prompt_tokens": 800},
            cost=0.025,
        ),
        assertion_passed=False,
        assertion_details="2/3 tests passed",
        timings=EvalTimings(total_ms=100),
        scores={"pass_rate": 0.6667, "tests_passed": 2.0, "tests_total": 3.0},
    )
    result = EvalResult(turn_results=[turn], total_ms=100)

    jsonl_path = tmp_path / "avg.jsonl"
    JsonlReporter(jsonl_path).report(result)
    summary = json.loads(jsonl_path.read_text().splitlines()[0])
    assert summary["avg_pass_rate"] == 0.6667
    assert summary["avg_total_tokens"] == 1200

    md_path = tmp_path / "avg.md"
    MarkdownReporter(md_path).report(result)
    md = md_path.read_text()
    assert "- **Avg Test Pass Rate**: 66.7%" in md
    assert "**Total Tokens**: 1,200 (avg 1,200/case)" in md
    assert "**Total Cost**: $0.0250" in md
