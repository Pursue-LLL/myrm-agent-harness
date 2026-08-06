"""Unit tests for workflow template validation helpers."""

from myrm_agent_harness.agent.dynamic_workflow.template_validation import (
    apply_template_args,
    can_skip_plan_confirm,
    compute_script_hash,
    extract_required_agent_types,
    extract_template_placeholders,
    script_all_spawns_readonly,
    validate_orchestration_script,
)

_VALID_SCRIPT = """
import myrm_tools
myrm_tools.spawn_subagent(task_id="t1", agent_type="generalPurpose", task_description="hello", readonly=True)
"""


def test_validate_orchestration_script_accepts_spawn_call() -> None:
    ok, error = validate_orchestration_script(_VALID_SCRIPT)
    assert ok is True
    assert error is None


def test_validate_orchestration_script_rejects_empty() -> None:
    ok, error = validate_orchestration_script("   ")
    assert ok is False
    assert error == "Script is empty."


def test_validate_orchestration_script_rejects_subprocess() -> None:
    script = _VALID_SCRIPT + "\nimport subprocess"
    ok, error = validate_orchestration_script(script)
    assert ok is False
    assert error is not None


def test_extract_required_agent_types_preserves_order() -> None:
    script = """
myrm_tools.spawn_subagent(agent_type="explore", task_id="a", task_description="x")
myrm_tools.spawn_subagent(agent_type="generalPurpose", task_id="b", task_description="y")
myrm_tools.spawn_subagent(agent_type="explore", task_id="c", task_description="z")
"""
    assert extract_required_agent_types(script) == ["explore", "generalPurpose"]


def test_apply_template_args_replaces_placeholders() -> None:
    script = 'print("{topic}")'
    assert apply_template_args(script, {"topic": "docs"}) == 'print("docs")'


def test_extract_template_placeholders_preserves_order() -> None:
    script = 'a="{topic}"; b="{focus_area}"; c="{topic}"'
    assert extract_template_placeholders(script) == ("topic", "focus_area")


def test_compute_script_hash_is_stable() -> None:
    assert compute_script_hash("abc") == compute_script_hash("abc")
    assert compute_script_hash("abc") != compute_script_hash("abcd")


def test_script_all_spawns_readonly_requires_all_readonly() -> None:
    readonly_script = _VALID_SCRIPT
    mixed_script = """
myrm_tools.spawn_subagent(task_id="t1", agent_type="generalPurpose", task_description="hello")
"""
    assert script_all_spawns_readonly(readonly_script) is True
    assert script_all_spawns_readonly(mixed_script) is False


def test_can_skip_plan_confirm_requires_trust_and_readonly() -> None:
    assert (
        can_skip_plan_confirm(
            script_code=_VALID_SCRIPT,
            trust_latch=True,
            estimated_cost_usd=0.5,
        )
        is True
    )
    assert (
        can_skip_plan_confirm(
            script_code=_VALID_SCRIPT,
            trust_latch=False,
            estimated_cost_usd=0.5,
        )
        is False
    )
    assert (
        can_skip_plan_confirm(
            script_code=_VALID_SCRIPT,
            trust_latch=True,
            estimated_cost_usd=2.0,
        )
        is False
    )
