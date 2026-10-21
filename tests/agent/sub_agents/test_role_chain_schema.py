"""Tests for subagent role chain presets and prompt guidance compiler."""

from myrm_agent_harness.agent.sub_agents.role_chain_schema import (
    BUILTIN_ROLE_CHAIN_PRESETS,
    IMPLEMENT_REVIEW_FIX_PRESET,
    WATCHDOG_GUARD_PRESET,
    compile_role_chain_guidance,
    get_role_chain_preset,
)
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig


def test_builtin_role_chain_presets_integrity():
    assert len(BUILTIN_ROLE_CHAIN_PRESETS) == 4
    assert "implement_review_fix" in BUILTIN_ROLE_CHAIN_PRESETS
    assert "clarify_scout_worker" in BUILTIN_ROLE_CHAIN_PRESETS
    assert "watchdog_guard" in BUILTIN_ROLE_CHAIN_PRESETS
    assert "editorial_publish" in BUILTIN_ROLE_CHAIN_PRESETS


def test_implement_review_fix_preset_structure():
    preset = IMPLEMENT_REVIEW_FIX_PRESET
    assert preset.preset_id == "implement_review_fix"
    assert preset.max_review_rounds == 3
    assert preset.is_review_loop is True
    assert preset.stage_ids == ("implementer", "reviewer", "fixer")
    assert preset.stages[1].suggested_model == "deepseek-chat"
    assert preset.stages[1].is_verifier is True


def test_watchdog_guard_preset_structure():
    preset = WATCHDOG_GUARD_PRESET
    assert preset.preset_id == "watchdog_guard"
    assert preset.stage_ids == ("watchdog", "adversarial_reviewer")
    assert all(stage.is_verifier for stage in preset.stages)


def test_get_role_chain_preset():
    assert get_role_chain_preset("implement_review_fix") is IMPLEMENT_REVIEW_FIX_PRESET
    assert get_role_chain_preset("unknown_preset") is None


def test_compile_role_chain_guidance_builtin_loop():
    guidance = compile_role_chain_guidance("implement_review_fix", max_review_rounds=3)
    assert "Active Subagent Role Chain Protocol: Implement -> Review -> Fix Chain" in guidance
    assert "[Implementer]" in guidance
    assert "[Reviewer]" in guidance
    assert "[Fixer]" in guidance
    assert "delegate_task_tool" in guidance
    assert "Review Loop Ceiling" in guidance
    assert "at most **3** rounds" in guidance


def test_compile_role_chain_guidance_custom_chain():
    guidance = compile_role_chain_guidance(("step_a", "step_b"), max_review_rounds=2)
    assert "Active Subagent Role Chain Protocol: Custom Chain" in guidance
    assert "step_a -> step_b" in guidance
    assert "Maximum review rounds capped at 2." in guidance


def test_subagent_config_role_chain_fields():
    config = SubagentConfig(
        system_prompt="You are a child agent.",
        role_chain=("implementer", "reviewer", "fixer"),
        max_review_rounds=3,
        model_override="deepseek-chat",
    )
    assert config.role_chain == ("implementer", "reviewer", "fixer")
    assert config.max_review_rounds == 3
    assert config.model_override == "deepseek-chat"
