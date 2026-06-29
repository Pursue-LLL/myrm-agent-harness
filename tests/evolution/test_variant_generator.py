"""Tests for VariantGenerator — concurrent LLM-based skill variant generation.

Covers: prompt assembly (FIX, evidence-based, description-only, preference),
concurrent generation, fallback behavior, content extraction.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionType,
    SkillEvidenceGroup,
    SkillLineage,
    SkillRecord,
)
from myrm_agent_harness.agent.skills.evolution.pipeline.variant_generator import (
    VariantGenerator,
)


@pytest.fixture
def mock_skill() -> SkillRecord:
    return SkillRecord(
        skill_id="test-001",
        name="test-skill",
        description="A test skill for unit tests.",
        content="---\nname: test-skill\n---\n# Test\n## Instructions\n1. Do X\n2. Do Y",
        path="/skills/test-skill.md",
        lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED, parent_id=None),
        traps=[
            {"description": "Never delete user data", "severity": "critical", "occurrence_count": 3},
            {"description": "Check file exists first", "severity": "high", "occurrence_count": 2},
        ],
    )


@pytest.fixture
def mock_evidence() -> SkillEvidenceGroup:
    return SkillEvidenceGroup(
        skill_id="test-001",
        skill_name="test-skill",
        success_cases=[
            MagicMock(task_context="Deploy to staging", error_message=None),
        ],
        failure_cases=[
            MagicMock(task_context="Deploy to prod", error_message="Permission denied: /etc/nginx"),
        ],
        common_error_patterns=["Permission denied"],
    )


class TestVariantGeneratorNoLLM:
    """Behavior when no LLM configured."""

    @pytest.mark.asyncio
    async def test_no_llm_returns_original(self, mock_skill: SkillRecord) -> None:
        gen = VariantGenerator(llm=None)
        results = await gen.generate_variants(mock_skill, "error", "trace")
        assert results == [mock_skill.content]

    @pytest.mark.asyncio
    async def test_no_llm_evidence_returns_original(self, mock_skill: SkillRecord, mock_evidence: SkillEvidenceGroup) -> None:
        gen = VariantGenerator(llm=None)
        results = await gen.generate_variants_from_evidence(mock_skill, mock_evidence)
        assert results == [mock_skill.content]

    @pytest.mark.asyncio
    async def test_no_llm_description_returns_original(self, mock_skill: SkillRecord) -> None:
        gen = VariantGenerator(llm=None)
        results = await gen.generate_description_variants(mock_skill)
        assert results == [mock_skill.description]


class TestVariantGeneratorWithMockLLM:
    """Variant generation with mocked LLM."""

    @pytest.fixture
    def mock_llm(self) -> MagicMock:
        llm = MagicMock()
        response = MagicMock()
        response.content = "---\nname: test-skill\n---\n# Improved Test\n## Instructions\n1. Do X safely\n2. Do Y"
        llm.ainvoke = AsyncMock(return_value=response)
        return llm

    @pytest.mark.asyncio
    async def test_generates_multiple_variants(self, mock_llm: MagicMock, mock_skill: SkillRecord) -> None:
        gen = VariantGenerator(llm=mock_llm)
        results = await gen.generate_variants(mock_skill, "error occurred", "trace data", num_variants=3)
        assert len(results) == 3
        assert all(r.strip() for r in results)

    @pytest.mark.asyncio
    async def test_evidence_based_generation(
        self, mock_llm: MagicMock, mock_skill: SkillRecord, mock_evidence: SkillEvidenceGroup
    ) -> None:
        gen = VariantGenerator(llm=mock_llm)
        results = await gen.generate_variants_from_evidence(mock_skill, mock_evidence, num_variants=2)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_description_generation(self, mock_llm: MagicMock, mock_skill: SkillRecord) -> None:
        gen = VariantGenerator(llm=mock_llm)
        results = await gen.generate_description_variants(mock_skill, num_variants=2)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_all_failures_return_original(self, mock_skill: SkillRecord) -> None:
        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=Exception("LLM timeout"))
        gen = VariantGenerator(llm=llm)
        results = await gen.generate_variants(mock_skill, "error", "trace", num_variants=2)
        assert results == [mock_skill.content]


class TestPromptAssembly:
    """Verify prompt structure contains required components."""

    @pytest.fixture
    def generator(self) -> VariantGenerator:
        return VariantGenerator(llm=MagicMock())

    def test_fix_prompt_contains_required_sections(self, generator: VariantGenerator, mock_skill: SkillRecord) -> None:
        prompt = generator._build_variant_prompt(mock_skill, "TypeError in line 5", "stack trace here")
        assert "Editing Principles" in prompt
        assert "Hard Constraints" in prompt
        assert "Conservative Editing" in prompt
        assert "Failure Attribution" in prompt
        assert "TypeError in line 5" in prompt
        assert "stack trace here" in prompt
        assert mock_skill.name in prompt

    def test_preference_prompt_uses_preference_module(self, generator: VariantGenerator, mock_skill: SkillRecord) -> None:
        prompt = generator._build_variant_prompt(mock_skill, "[PREFERENCE]太啰嗦了", "")
        assert "User Preference Embedding" in prompt
        assert "Failure Attribution" not in prompt
        assert "太啰嗦了" in prompt

    def test_evidence_prompt_includes_cases(
        self, generator: VariantGenerator, mock_skill: SkillRecord, mock_evidence: SkillEvidenceGroup
    ) -> None:
        prompt = generator._build_evidence_prompt(mock_skill, mock_evidence)
        assert "WORKING SCENARIOS" in prompt
        assert "FAILING SCENARIOS" in prompt
        assert "Permission denied" in prompt
        assert "Deploy to staging" in prompt

    def test_traps_injected_into_prompt(self, generator: VariantGenerator, mock_skill: SkillRecord) -> None:
        prompt = generator._build_variant_prompt(mock_skill, "error", "trace")
        assert "Known Traps" in prompt
        assert "Never delete user data" in prompt

    def test_constraints_injected(self, generator: VariantGenerator, mock_skill: SkillRecord) -> None:
        prompt = generator._build_variant_prompt(mock_skill, "error", "trace", constraints="Must preserve API port 8080")
        assert "Historical Constraints" in prompt
        assert "Must preserve API port 8080" in prompt


class TestContentExtraction:
    """Verify markdown fence removal logic."""

    def test_removes_markdown_fences(self) -> None:
        raw = "```markdown\n# Skill\nContent here\n```"
        assert VariantGenerator._extract_content(raw) == "# Skill\nContent here"

    def test_preserves_edit_summary(self) -> None:
        raw = "# Skill\n---EDIT_SUMMARY---\n{\"notes\": \"changed X\"}"
        assert "---EDIT_SUMMARY---" in VariantGenerator._extract_content(raw)

    def test_plain_text_unchanged(self) -> None:
        raw = "# Skill\nContent"
        assert VariantGenerator._extract_content(raw) == "# Skill\nContent"
