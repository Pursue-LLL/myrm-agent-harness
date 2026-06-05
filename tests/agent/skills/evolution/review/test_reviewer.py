"""Tests for the skill review engine (reviewer.py).

Validates prompt template generation, rubric thresholds, and result parsing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.evolution.review.reviewer import (
    _REVIEW_PROMPT_TEMPLATE,
    SkillExtractionRubric,
    SkillReviewResult,
    review_trajectory_with_llm,
)


class TestSkillExtractionRubric:
    """Test the SkillExtractionRubric scoring model."""

    def _make_rubric(self, score: float = 1.0, **overrides) -> SkillExtractionRubric:
        fields = {
            "structure_score": score,
            "workflow_clarity_score": score,
            "failure_mode_score": score,
            "anti_pattern_score": score,
            "human_in_loop_score": score,
            "resource_integration_score": score,
            "anti_fluff_score": score,
            "anti_fragmentation_score": score,
            "sandbox_compatibility_score": score,
            "multi_agent_isolation_score": score,
            "reasoning": "Test",
            "result_type": "nothing",
        }
        fields.update(overrides)
        return SkillExtractionRubric(**fields)

    def test_total_score_calculation(self):
        rubric = self._make_rubric(
            score=1.0,
            reasoning="All perfect",
            result_type="skill_draft",
            skill_name="test-skill",
            skill_steps="Step 1",
        )
        assert abs(rubric.total_score - 1.0) < 1e-6

    def test_total_score_weighted_average(self):
        rubric = self._make_rubric(
            structure_score=0.8,
            workflow_clarity_score=0.6,
            failure_mode_score=0.4,
            anti_pattern_score=0.2,
            human_in_loop_score=0.5,
            resource_integration_score=0.7,
            anti_fluff_score=0.3,
            anti_fragmentation_score=0.9,
            sandbox_compatibility_score=0.1,
            multi_agent_isolation_score=0.6,
            reasoning="Mixed",
        )
        expected = (
            (0.8 * 0.05)
            + (0.6 * 0.15)
            + (0.4 * 0.15)
            + (0.2 * 0.10)
            + (0.5 * 0.05)
            + (0.7 * 0.05)
            + (0.3 * 0.10)
            + (0.9 * 0.10)
            + (0.1 * 0.15)
            + (0.6 * 0.10)
        )
        assert abs(rubric.total_score - expected) < 1e-6

    def test_total_score_zero(self):
        rubric = self._make_rubric(score=0.0, reasoning="Nothing useful")
        assert rubric.total_score == 0.0


class TestSkillReviewResult:
    """Test the SkillReviewResult data class."""

    def test_to_dict_no_value(self):
        result = SkillReviewResult(has_value=False)
        d = result.to_dict()
        assert d["has_value"] is False
        assert d["type"] is None

    def test_to_dict_with_skill_draft(self):
        result = SkillReviewResult(
            has_value=True,
            result_type="skill_draft",
            skill_name="code-review-workflow",
            skill_description="A code review process",
            trigger_condition="When user asks for review",
            skill_steps="Step 1: Read code\nStep 2: Review",
            user_id="user_1",
            agent_id="agent_1",
            chat_id="chat_1",
        )
        d = result.to_dict()
        assert d["has_value"] is True
        assert d["type"] == "skill_draft"
        assert d["skill_name"] == "code-review-workflow"
        assert d["user_id"] == "user_1"

    def test_to_dict_with_semantic_memory(self):
        result = SkillReviewResult(
            has_value=True,
            result_type="semantic_memory",
            content="User prefers TypeScript over JavaScript",
        )
        d = result.to_dict()
        assert d["type"] == "semantic_memory"
        assert d["content"] == "User prefers TypeScript over JavaScript"

    def test_to_dict_with_skill_patch(self):
        result = SkillReviewResult(
            has_value=True,
            result_type="skill_patch",
            skill_name="python-coding",
            patch_content="Add section about type hints",
        )
        d = result.to_dict()
        assert d["type"] == "skill_patch"
        assert d["skill_name"] == "python-coding"
        assert d["patch_content"] == "Add section about type hints"


class TestReviewPromptTemplate:
    """Test the prompt template contains required guidance rules."""

    def test_contains_do_not_capture_rule(self):
        assert "DO NOT CAPTURE" in _REVIEW_PROMPT_TEMPLATE

    def test_contains_environment_failure_exclusion(self):
        assert "environment failures" in _REVIEW_PROMPT_TEMPLATE.lower()

    def test_contains_anti_fragmentation_guidance(self):
        assert "generalizable" in _REVIEW_PROMPT_TEMPLATE.lower()

    def test_contains_sandbox_compatibility_guidance(self):
        assert "sandbox" in _REVIEW_PROMPT_TEMPLATE.lower()

    def test_contains_rubric_dimensions(self):
        assert "10-Dim" in _REVIEW_PROMPT_TEMPLATE

    def test_contains_naming_constraint(self):
        assert "NAMING CONSTRAINT" in _REVIEW_PROMPT_TEMPLATE
        assert "lowercase" in _REVIEW_PROMPT_TEMPLATE

    def test_contains_priority_order(self):
        assert "PRIORITY ORDER" in _REVIEW_PROMPT_TEMPLATE
        assert "currently-loaded skill" in _REVIEW_PROMPT_TEMPLATE
        assert "skill_patch" in _REVIEW_PROMPT_TEMPLATE

    def test_contains_all_format_placeholders(self):
        assert "{original_goal}" in _REVIEW_PROMPT_TEMPLATE
        assert "{active_skills}" in _REVIEW_PROMPT_TEMPLATE
        assert "{all_skills_catalog}" in _REVIEW_PROMPT_TEMPLATE
        assert "{trajectory_skeleton}" in _REVIEW_PROMPT_TEMPLATE


class TestReviewTrajectoryWithLLM:
    """Test the review_trajectory_with_llm function."""

    def _make_rubric(self, score: float = 0.9, **overrides) -> SkillExtractionRubric:
        """Create a rubric with all 10 dimensions set to `score`, then apply overrides."""
        fields = {
            "structure_score": score,
            "workflow_clarity_score": score,
            "failure_mode_score": score,
            "anti_pattern_score": score,
            "human_in_loop_score": score,
            "resource_integration_score": score,
            "anti_fluff_score": score,
            "anti_fragmentation_score": score,
            "sandbox_compatibility_score": score,
            "multi_agent_isolation_score": score,
            "reasoning": "Test",
            "result_type": "nothing",
        }
        fields.update(overrides)
        return SkillExtractionRubric(**fields)

    def _make_llm_mock(self, rubric_or_error: SkillExtractionRubric | Exception | None):
        """Create a properly mocked LLM that returns rubric on ainvoke."""
        llm = MagicMock()
        structured_llm = MagicMock()
        if isinstance(rubric_or_error, Exception):
            structured_llm.ainvoke = AsyncMock(side_effect=rubric_or_error)
        else:
            structured_llm.ainvoke = AsyncMock(return_value=rubric_or_error)
        llm.with_structured_output.return_value = structured_llm
        return llm, structured_llm

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_trajectory(self):
        llm = MagicMock()
        result = await review_trajectory_with_llm("", llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_no_value_when_llm_returns_none(self):
        llm, _ = self._make_llm_mock(None)
        result = await review_trajectory_with_llm("<User>: hello", llm)
        assert result is not None
        assert result.has_value is False

    @pytest.mark.asyncio
    async def test_returns_no_value_when_result_type_nothing(self):
        rubric = self._make_rubric(reasoning="Not worth it", result_type="nothing")
        llm, _ = self._make_llm_mock(rubric)
        result = await review_trajectory_with_llm("<User>: test", llm)
        assert result is not None
        assert result.has_value is False

    @pytest.mark.asyncio
    async def test_rejects_low_total_score(self):
        rubric = self._make_rubric(
            score=0.3,
            reasoning="Low quality",
            result_type="skill_draft",
            skill_name="test",
            skill_steps="Steps",
        )
        llm, _ = self._make_llm_mock(rubric)
        result = await review_trajectory_with_llm("<User>: test", llm)
        assert result is not None
        assert result.has_value is False

    @pytest.mark.asyncio
    async def test_rejects_low_anti_fragmentation_score(self):
        """Fragmented skills (fix-X, debug-Y naming) get rejected by threshold."""
        rubric = self._make_rubric(
            anti_fragmentation_score=0.5,
            reasoning="Fragmented naming",
            result_type="skill_draft",
            skill_name="fix-specific-bug-today",
            skill_steps="Steps",
        )
        llm, _ = self._make_llm_mock(rubric)
        result = await review_trajectory_with_llm("<User>: test", llm)
        assert result is not None
        assert result.has_value is False

    @pytest.mark.asyncio
    async def test_returns_skill_draft(self):
        rubric = self._make_rubric(
            reasoning="Good workflow",
            result_type="skill_draft",
            skill_name="database-migration",
            skill_description="Database migration workflow",
            trigger_condition="When user asks to migrate DB",
            skill_steps="Step 1: Backup\nStep 2: Migrate",
        )
        llm, _ = self._make_llm_mock(rubric)
        result = await review_trajectory_with_llm("<User>: test", llm)
        assert result is not None
        assert result.has_value is True
        assert result.result_type == "skill_draft"
        assert result.skill_name == "database-migration"

    @pytest.mark.asyncio
    async def test_returns_skill_patch(self):
        rubric = self._make_rubric(
            reasoning="Update existing skill",
            result_type="skill_patch",
            skill_name="python-coding",
            patch_content="Add: Always use type hints for function parameters",
        )
        llm, _ = self._make_llm_mock(rubric)
        result = await review_trajectory_with_llm("<User>: test", llm)
        assert result is not None
        assert result.has_value is True
        assert result.result_type == "skill_patch"
        assert result.skill_name == "python-coding"
        assert "type hints" in (result.patch_content or "")

    @pytest.mark.asyncio
    async def test_returns_semantic_memory(self):
        rubric = self._make_rubric(
            reasoning="User preference",
            result_type="semantic_memory",
            content="User prefers dark mode in all UIs",
        )
        llm, _ = self._make_llm_mock(rubric)
        result = await review_trajectory_with_llm("<User>: test", llm)
        assert result is not None
        assert result.has_value is True
        assert result.result_type == "semantic_memory"
        assert result.content == "User prefers dark mode in all UIs"

    @pytest.mark.asyncio
    async def test_rejects_empty_semantic_memory_content(self):
        rubric = self._make_rubric(
            reasoning="Something",
            result_type="semantic_memory",
            content="",
        )
        llm, _ = self._make_llm_mock(rubric)
        result = await review_trajectory_with_llm("<User>: test", llm)
        assert result is not None
        assert result.has_value is False

    @pytest.mark.asyncio
    async def test_rejects_skill_draft_missing_name(self):
        rubric = self._make_rubric(
            reasoning="Missing name",
            result_type="skill_draft",
            skill_name="",
            skill_steps="Steps here",
        )
        llm, _ = self._make_llm_mock(rubric)
        result = await review_trajectory_with_llm("<User>: test", llm)
        assert result is not None
        assert result.has_value is False

    @pytest.mark.asyncio
    async def test_rejects_skill_patch_missing_patch_content(self):
        rubric = self._make_rubric(
            reasoning="Missing patch",
            result_type="skill_patch",
            skill_name="some-skill",
            patch_content="",
        )
        llm, _ = self._make_llm_mock(rubric)
        result = await review_trajectory_with_llm("<User>: test", llm)
        assert result is not None
        assert result.has_value is False

    @pytest.mark.asyncio
    async def test_handles_llm_exception_gracefully(self):
        llm, _ = self._make_llm_mock(RuntimeError("API down"))
        result = await review_trajectory_with_llm("<User>: test", llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_nothing_in_error_message(self):
        """Partial JSON output with result_type=nothing should not raise."""
        llm, _ = self._make_llm_mock(
            ValueError('{"result_type": "nothing"} partial output')
        )
        result = await review_trajectory_with_llm("<User>: test", llm)
        assert result is not None
        assert result.has_value is False

    @pytest.mark.asyncio
    async def test_passes_active_skills_to_prompt(self):
        rubric = self._make_rubric(score=0.3, reasoning="Low")
        llm, structured_llm = self._make_llm_mock(rubric)

        await review_trajectory_with_llm(
            "<User>: hello",
            llm,
            active_skills=["python-coding", "debugging"],
            all_skills_catalog="python-coding — Write Python code",
            original_goal="Fix a bug",
        )

        call_args = structured_llm.ainvoke.call_args[0][0]
        assert "python-coding" in call_args
        assert "debugging" in call_args
        assert "Fix a bug" in call_args

    @pytest.mark.asyncio
    async def test_unknown_result_type_returns_no_value(self):
        """Unknown result_type triggers Pydantic validation error which is caught."""
        llm, _ = self._make_llm_mock(
            ValueError("result_type Input should be 'nothing', 'semantic_memory'...")
        )
        result = await review_trajectory_with_llm("<User>: test", llm)
        assert result is None
