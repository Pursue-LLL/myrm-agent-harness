"""Tests for skill version promotion gate."""

from myrm_agent_harness.agent.skills.evolution.core.promotion_gate import (
    PromotionReasonCode,
    evaluate_promotion_gate,
)


def test_gate_allows_when_no_eval_cases_and_not_required():
    verdict = evaluate_promotion_gate(
        eval_cases=[],
        baseline_content="---\nname: a\n---\nkeep",
        candidate_content="---\nname: a\n---\nkeep improved",
        skill_name="a",
        skill_id="skill-a",
    )
    assert verdict.allowed is True
    assert verdict.reason_code == PromotionReasonCode.ALLOWED


def test_gate_blocks_when_eval_cases_required():
    verdict = evaluate_promotion_gate(
        eval_cases=[],
        baseline_content="---\nname: a\n---\nx",
        candidate_content="---\nname: a\n---\ny",
        skill_name="a",
        skill_id="skill-a",
        require_eval_cases=True,
    )
    assert verdict.allowed is False
    assert verdict.reason_code == PromotionReasonCode.NO_EVAL_CASES


def test_gate_blocks_regression_on_code_contains():
    cases = [{"sandbox_assertions": [{"type": "code_contains", "target": "required_token"}]}]
    baseline = "---\nname: a\n---\nrequired_token here"
    candidate = "---\nname: a\n---\nremoved"
    verdict = evaluate_promotion_gate(
        eval_cases=cases,
        baseline_content=baseline,
        candidate_content=candidate,
        skill_name="a",
        skill_id="skill-a",
    )
    assert verdict.allowed is False
    assert verdict.reason_code == PromotionReasonCode.REGRESSION
