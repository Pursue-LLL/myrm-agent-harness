"""Unit tests for Component Ablation Leverage & Harness Edit Rules Engine."""

from __future__ import annotations

import pytest

from myrm_agent_harness.eval.ablation_rules import (
    AblationRecommendation,
    ComponentTier,
    derive_ablation_recommendations,
)
from myrm_agent_harness.eval.protocols import (
    AgentResponse,
    EvalCase,
    EvalResult,
    EvalTimings,
    EvalTurnResult,
)
from myrm_agent_harness.eval.trajectory_analysis import FailureMode


def test_component_tier_enum_values() -> None:
    assert ComponentTier.TOOL.value == "tool"
    assert ComponentTier.MIDDLEWARE.value == "middleware"
    assert ComponentTier.MEMORY.value == "memory"
    assert ComponentTier.PROMPT.value == "prompt"


def test_ablation_recommendation_to_dict() -> None:
    rec = AblationRecommendation(
        component=ComponentTier.MIDDLEWARE,
        priority=1,
        action_key="enable_argument_repair_middleware",
        title="Tool Argument Serialization Failure",
        reason="Model generated invalid parameters.",
        target_config_tab="capabilities",
        target_setting_key="tool_interceptor",
        affected_case_count=3,
        evidence_modes=["tool_argument_malformed"],
    )
    d = rec.to_dict()
    assert d["component"] == "middleware"
    assert d["priority"] == 1
    assert d["action_key"] == "enable_argument_repair_middleware"
    assert d["title"] == "Tool Argument Serialization Failure"
    assert d["target_config_tab"] == "capabilities"
    assert d["target_setting_key"] == "tool_interceptor"
    assert d["affected_case_count"] == 3
    assert d["evidence_modes"] == ["tool_argument_malformed"]


def test_derive_ablation_recommendations_empty() -> None:
    assert derive_ablation_recommendations({}) == []
    assert derive_ablation_recommendations({"tool_argument_malformed": 0}) == []


def test_derive_ablation_recommendations_known_modes_priority_order() -> None:
    failure_counts = {
        FailureMode.INTENT_MISUNDERSTANDING.value: 2,  # Prompt tier (Priority 4)
        FailureMode.TOOL_ARGUMENT_MALFORMED.value: 4,  # Middleware tier (Priority 1)
        FailureMode.TOOL_SELECTION_ERROR.value: 1,  # Tool tier (Priority 1)
        FailureMode.CONTEXT_OVERFLOW_OR_BUDGET.value: 3,  # Middleware tier (Priority 2)
    }

    recs = derive_ablation_recommendations(failure_counts)
    assert len(recs) == 4

    # Top items must have priority 1
    assert recs[0].priority == 1
    assert recs[1].priority == 1
    # Higher affected count comes first within the same priority
    assert recs[0].affected_case_count >= recs[1].affected_case_count
    assert recs[0].action_key == "enable_argument_repair_middleware"

    # Priority 2 comes next
    assert recs[2].priority == 2
    assert recs[2].action_key == "enable_context_compression"

    # Priority 4 (Prompt) comes last
    assert recs[3].priority == 4
    assert recs[3].component == ComponentTier.PROMPT
    assert recs[3].action_key == "tune_persona_objective"


def test_derive_ablation_recommendations_dedup_and_merge() -> None:
    # Both HARDCODED_TESTS and INTENT_MISUNDERSTANDING map to action_key "tune_persona_objective"
    failure_counts = {
        FailureMode.HARDCODED_TESTS.value: 2,
        FailureMode.INTENT_MISUNDERSTANDING.value: 3,
    }
    recs = derive_ablation_recommendations(failure_counts)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.action_key == "tune_persona_objective"
    assert rec.affected_case_count == 5
    assert set(rec.evidence_modes) == {
        FailureMode.HARDCODED_TESTS.value,
        FailureMode.INTENT_MISUNDERSTANDING.value,
    }


def test_derive_ablation_recommendations_fallback_for_unmapped_mode() -> None:
    # Unmapped mode should be caught by safety fallback to avoid measurement decay
    failure_counts = {
        "custom_third_party_failure_sig": 5,
    }
    recs = derive_ablation_recommendations(failure_counts)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.component == ComponentTier.MIDDLEWARE
    assert rec.action_key == "enable_error_recovery_middleware"
    assert rec.affected_case_count == 5
    assert "custom_third_party_failure_sig" in rec.evidence_modes


def test_eval_result_to_dict_includes_ablation_recommendations() -> None:
    failed_turn = EvalTurnResult(
        case=EvalCase(message="Read test file"),
        response=AgentResponse(
            answer="",
            tools_called=["broken_tool"],
            limit_reached="max_iterations",
        ),
        assertion_passed=False,
        timings=EvalTimings(),
        error="Execution timed out",
    )

    eval_result = EvalResult(
        turn_results=[failed_turn],
        total_ms=150.0,
    )

    data = eval_result.to_dict()
    assert "failure_analysis" in data
    assert "ablation_recommendations" in data
    recs = data["ablation_recommendations"]
    assert isinstance(recs, list)
    assert len(recs) > 0
    # Should recommend middleware/budget adjustments
    assert any(r["component"] == "middleware" for r in recs)
