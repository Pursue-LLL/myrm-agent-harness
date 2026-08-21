"""Comprehensive test suite for Compaction Continuation Acceptance Metrics & A/B Harness."""

from __future__ import annotations

import pytest

from myrm_agent_harness.eval.compaction_ab import CompactionABEvaluator, CompactionABResult
from myrm_agent_harness.eval.compaction_assertions import (
    canonicalize_tool_name,
    evaluate_compaction_assertions,
)
from myrm_agent_harness.eval.protocols import (
    AgentResponse,
    CompactionAssertion,
    CompactionFidelityScore,
    EvalCase,
)
from myrm_agent_harness.eval.runner import EvalRunner


def test_canonicalize_tool_name() -> None:
    """Verify tool normalization handles aliases."""
    assert canonicalize_tool_name("file_read_tool") == "read_file"
    assert canonicalize_tool_name("READ_FILE_TOOL") == "read_file"
    assert canonicalize_tool_name("bash_code_execute_tool") == "bash"
    assert canonicalize_tool_name("web_search_tool") == "web_search"
    assert canonicalize_tool_name("custom_plugin_tool") == "custom_plugin_tool"


@pytest.mark.asyncio
async def test_evaluate_compaction_assertions_success() -> None:
    """Verify 5D compaction assertions pass when all constraints and artifacts are preserved."""
    assertion = CompactionAssertion(
        expected_constraints=("USD currency", "no estimation"),
        forbidden_claims=("task already completed",),
        required_artifacts=("reports/fin_2026.xlsx",),
        expected_tools=("read_file",),
        min_fidelity_score=0.85,
    )

    response = AgentResponse(
        answer="I will process the remaining cash flow data strictly using USD currency with no estimation. Output will be appended to reports/fin_2026.xlsx.",
        tools_called=["file_read_tool"],
    )

    scores: dict[str, float] = {}
    passed, details = await evaluate_compaction_assertions([assertion], response, scores_out=scores)

    assert passed is True
    assert scores["case_1_overall_fidelity"] >= 0.85
    assert scores["case_1_constraint_recall"] == 1.0
    assert scores["case_1_artifact_coverage"] == 1.0
    assert scores["case_1_state_accuracy"] == 1.0
    assert "All 5 dimensions satisfied" in details


@pytest.mark.asyncio
async def test_evaluate_compaction_assertions_forbidden_claim_failure() -> None:
    """Verify assertion fails when agent hallucinates a forbidden completed state."""
    assertion = CompactionAssertion(
        expected_constraints=("USD currency",),
        forbidden_claims=("all tasks are finished",),
        min_fidelity_score=0.80,
    )

    response = AgentResponse(
        answer="All tasks are finished. Here is the final summary in USD currency.",
        tools_called=[],
    )

    passed, details = await evaluate_compaction_assertions([assertion], response)
    assert passed is False
    assert "Violated forbidden claims" in details


@pytest.mark.asyncio
async def test_compaction_ab_evaluator_pareto_output() -> None:
    """Verify CompactionABEvaluator correctly calculates token savings and 5D comparative score."""
    evaluator = CompactionABEvaluator()

    baseline_resp = AgentResponse(
        answer="Reading raw dataset to verify revenue under USD currency for reports/fin_2026.xlsx.",
        tools_called=["file_read_tool"],
    )
    compacted_resp = AgentResponse(
        answer="Reading dataset to verify revenue strictly under USD currency for reports/fin_2026.xlsx.",
        tools_called=["read_file"],
    )

    assertion = CompactionAssertion(
        expected_constraints=("USD currency",),
        required_artifacts=("reports/fin_2026.xlsx",),
        expected_tools=("read_file",),
    )

    result = await evaluator.evaluate_continuation_ab(
        task_name="financial_report_continuation",
        baseline_response=baseline_resp,
        compacted_response=compacted_resp,
        assertions=[assertion],
        baseline_context_tokens=100000,
        compacted_context_tokens=25000,
    )

    assert result.passed is True
    assert result.token_savings_pct == 75.0
    assert result.fidelity_score.overall_fidelity >= 0.80

    res_dict = result.to_dict()
    assert res_dict["token_savings_pct"] == 75.0
    assert res_dict["passed"] is True
    assert "fidelity" in res_dict


@pytest.mark.asyncio
async def test_eval_runner_integration_with_compaction_assertion() -> None:
    """Verify EvalRunner automatically evaluates CompactionAssertion when present on EvalCase."""
    class DummyExecutor:
        async def create_session(self) -> str:
            return "dummy_session_id"

        async def execute(self, message: str, *, session_id: str | None = None) -> AgentResponse:
            return AgentResponse(
                answer="Analyzing reports/q3.csv strictly under USD currency constraint.",
                tools_called=["read_file"],
            )

    runner = EvalRunner(DummyExecutor())

    case = EvalCase(
        message="Continue step 2",
        compaction_assertions=[
            CompactionAssertion(
                expected_constraints=("USD currency",),
                required_artifacts=("reports/q3.csv",),
                expected_tools=("read_file",),
                min_fidelity_score=0.80,
            )
        ],
    )

    result = await runner.run([case])
    assert result.total_cases == 1
    assert result.pass_count == 1
    assert result.all_passed is True


@pytest.mark.asyncio
async def test_multi_compaction_assertions_aggregation() -> None:
    """Verify CompactionABEvaluator aggregates fidelity scores across multiple assertions."""
    evaluator = CompactionABEvaluator()

    baseline_resp = AgentResponse(
        answer="Step 1 in USD currency targeting dataset.csv. Step 2 in EUR targeting metrics.json.",
        tools_called=["read_file", "write_file"],
    )
    compacted_resp = AgentResponse(
        answer="Step 1 strictly in USD currency targeting dataset.csv. Step 2 in EUR targeting metrics.json.",
        tools_called=["read_file", "write_file"],
    )

    assertion1 = CompactionAssertion(
        expected_constraints=("USD currency",),
        required_artifacts=("dataset.csv",),
        expected_tools=("read_file",),
        min_fidelity_score=0.85,
    )
    assertion2 = CompactionAssertion(
        expected_constraints=("EUR",),
        required_artifacts=("metrics.json",),
        expected_tools=("write_file",),
        min_fidelity_score=0.85,
    )

    result = await evaluator.evaluate_continuation_ab(
        task_name="multi_step_continuation",
        baseline_response=baseline_resp,
        compacted_response=compacted_resp,
        assertions=[assertion1, assertion2],
        baseline_context_tokens=80000,
        compacted_context_tokens=20000,
    )

    assert result.passed is True
    assert result.token_savings_pct == 75.0
    assert result.fidelity_score.constraint_recall == 1.0
    assert result.fidelity_score.artifact_coverage == 1.0
    assert result.fidelity_score.overall_fidelity >= 0.85
