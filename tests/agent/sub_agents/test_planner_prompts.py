"""Test planner prompt content integrity.

Validates that planner system prompt and tool description contain
all required elements from the Prompt Optimization (#3/#5).
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.planner.prompts import PLANNER_SYSTEM_PROMPT


class TestPlannerSystemPrompt:
    """Validate Explore-First Principle content in planner system prompt."""

    def test_contains_explore_first_section(self):
        assert "## Explore-First Principle" in PLANNER_SYSTEM_PROMPT

    def test_distinguishes_discoverable_vs_preferences(self):
        assert "Discoverable facts" in PLANNER_SYSTEM_PROMPT
        assert "Preferences" in PLANNER_SYSTEM_PROMPT

    def test_exploration_step_guidance(self):
        assert "exploration steps" in PLANNER_SYSTEM_PROMPT
        assert "expected_output" in PLANNER_SYSTEM_PROMPT
        assert "dependency" in PLANNER_SYSTEM_PROMPT.lower()

    def test_pending_issues_mentioned(self):
        assert "pending_issues" in PLANNER_SYSTEM_PROMPT

    def test_planning_principles_include_explore(self):
        assert "Explore First" in PLANNER_SYSTEM_PROMPT


class TestPlannerToolDescription:
    """Validate planner_tool source docstring contains scenario guidance.

    The tool is dynamically created via a factory, so we inspect the source
    file directly instead of importing the tool (which requires runtime config).
    """

    @pytest.fixture()
    def _source(self) -> str:
        import importlib
        import inspect

        mod = importlib.import_module("myrm_agent_harness.agent.sub_agents.planner.planner_agent_tools")
        return inspect.getsource(mod)

    def test_should_plan_scenarios(self, _source: str):
        assert "SHOULD plan" in _source
        assert "Multi-file" in _source
        assert "Architectural" in _source

    def test_should_not_plan_scenarios(self, _source: str):
        assert "Should NOT plan" in _source
        assert "Single-file" in _source

    def test_good_bad_examples(self, _source: str):
        assert "GOOD:" in _source
        assert "BAD:" in _source


class TestClearExpectationsACConstraints:
    """Validate AC verifiability constraints in planning principles."""

    def test_contains_good_examples(self):
        assert 'Good: "API endpoint returns JSON' in PLANNER_SYSTEM_PROMPT
        assert 'Good: "File src/config.ts exists' in PLANNER_SYSTEM_PROMPT
        assert 'Good: "Dashboard renders 3 charts' in PLANNER_SYSTEM_PROMPT
        assert 'Good: "Analysis report contains' in PLANNER_SYSTEM_PROMPT

    def test_contains_bad_examples(self):
        assert 'Bad: "Code works correctly"' in PLANNER_SYSTEM_PROMPT
        assert 'Bad: "Good performance"' in PLANNER_SYSTEM_PROMPT
        assert 'Bad: "Clean implementation"' in PLANNER_SYSTEM_PROMPT
        assert 'Bad: "Task completed successfully"' in PLANNER_SYSTEM_PROMPT

    def test_contains_verifiability_rule(self):
        assert "TOO VAGUE" in PLANNER_SYSTEM_PROMPT
        assert "observable" in PLANNER_SYSTEM_PROMPT
        assert "rewrite it with concrete observable criteria" in PLANNER_SYSTEM_PROMPT

    def test_clear_expectations_is_principle_4(self):
        assert "4. **Clear Expectations**" in PLANNER_SYSTEM_PROMPT


class TestRiskLevelPromptGuidance:
    """Validate risk_level guidance exists in planner system prompt."""

    def test_risk_level_field_mentioned(self):
        assert "risk_level" in PLANNER_SYSTEM_PROMPT

    def test_risk_level_values_documented(self):
        assert '"high"' in PLANNER_SYSTEM_PROMPT
        assert '"medium"' in PLANNER_SYSTEM_PROMPT
        assert '"low"' in PLANNER_SYSTEM_PROMPT

    def test_risk_level_criteria_documented(self):
        assert "hard to undo" in PLANNER_SYSTEM_PROMPT
        assert "destructive" in PLANNER_SYSTEM_PROMPT
        assert "reversible" in PLANNER_SYSTEM_PROMPT


class TestGetPlannerSystemPrompt:
    """Validate get_planner_system_prompt factory."""

    def test_returns_default_when_no_custom(self):
        from myrm_agent_harness.agent.sub_agents.planner.prompts import get_planner_system_prompt

        result = get_planner_system_prompt()
        assert result is PLANNER_SYSTEM_PROMPT

    def test_returns_custom_when_provided(self):
        from myrm_agent_harness.agent.sub_agents.planner.prompts import get_planner_system_prompt

        custom = "My custom prompt"
        result = get_planner_system_prompt(custom)
        assert result == custom

    def test_returns_default_when_none_explicit(self):
        from myrm_agent_harness.agent.sub_agents.planner.prompts import get_planner_system_prompt

        result = get_planner_system_prompt(None)
        assert result is PLANNER_SYSTEM_PROMPT


class TestGetUpdatePlanPrompt:
    """Validate get_update_plan_prompt factory."""

    def test_default_template_formatting(self):
        from myrm_agent_harness.agent.sub_agents.planner.prompts import get_update_plan_prompt

        result = get_update_plan_prompt(current_plan='{"steps": []}', completed_step_id="step_1", feedback="All good")
        assert '{"steps": []}' in result
        assert "step_1" in result
        assert "All good" in result

    def test_none_values_replaced(self):
        from myrm_agent_harness.agent.sub_agents.planner.prompts import get_update_plan_prompt

        result = get_update_plan_prompt(current_plan="{}")
        assert "None" in result

    def test_custom_template(self):
        from myrm_agent_harness.agent.sub_agents.planner.prompts import get_update_plan_prompt

        custom = "Plan: {current_plan} | Step: {completed_step_id} | FB: {feedback}"
        result = get_update_plan_prompt(
            current_plan="plan_data", completed_step_id="s2", feedback="done", custom_prompt=custom
        )
        assert result == "Plan: plan_data | Step: s2 | FB: done"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
