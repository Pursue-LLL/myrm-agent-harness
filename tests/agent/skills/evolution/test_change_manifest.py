"""Tests for the falsifiable change prediction manifest of evolution proposals."""

from myrm_agent_harness.agent.skills.evolution.core.change_manifest import build_change_manifest
from myrm_agent_harness.agent.skills.evolution.core.types import EvolutionType

_CASES = [{"sandbox_assertions": [{"type": "code_contains", "target": "required_token"}]}]
_BASELINE = "---\nname: a\n---\nplain body"
_IMPROVED = "---\nname: a\n---\nrequired_token present"


def _build(*, eval_cases, evolution_type=EvolutionType.FIX.value, reasoning="", original=_BASELINE, proposed=_IMPROVED):
    return build_change_manifest(
        eval_cases=eval_cases,
        skill_name="a",
        skill_id="skill-a",
        evolution_type=evolution_type,
        reasoning=reasoning,
        original_content=original,
        proposed_content=proposed,
    )


def test_no_eval_cases_yields_no_manifest():
    assert _build(eval_cases=[]) is None
    assert _build(eval_cases=None) is None


def test_description_only_evolution_yields_no_manifest():
    assert _build(eval_cases=_CASES, evolution_type=EvolutionType.OPTIMIZE_DESCRIPTION.value) is None


def test_improving_proposal_predicts_pass_rate_increase():
    manifest = _build(eval_cases=_CASES, reasoning="add the required token")

    assert manifest is not None
    assert manifest["target_component"] == "skills/a"
    assert manifest["rationale"] == "add the required token"
    pass_rate = next(p for p in manifest["predictions"] if p["metric_name"] == "pass_rate")
    assert pass_rate["baseline_value"] == 0.0
    assert pass_rate["target_value"] == 1.0
    assert manifest["search_pass_rate"] == 1.0
    assert manifest["test_pass_rate"] is None


def test_regressing_proposal_never_predicts_a_lower_target():
    manifest = _build(eval_cases=_CASES, original=_IMPROVED, proposed=_BASELINE)

    assert manifest is not None
    pass_rate = next(p for p in manifest["predictions"] if p["metric_name"] == "pass_rate")
    assert pass_rate["target_value"] == pass_rate["baseline_value"] == 1.0
    assert manifest["search_pass_rate"] == 0.0


def test_missing_reasoning_falls_back_to_default_rationale():
    manifest = _build(eval_cases=_CASES)

    assert manifest is not None
    assert manifest["rationale"] == "Self-evolution enhancement"
