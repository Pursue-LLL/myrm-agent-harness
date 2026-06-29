"""Tests for StructuredExtractor — skill extraction from conversation trajectories.

Covers: SkillCaptureResult validation, confidence parsing,
form routing, structured LLM path and JSON fallback path.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.skills.evolution.pipeline.structured_extractor import (
    SkillCaptureResult,
    StructuredExtractor,
)


class TestSkillCaptureResultValidation:
    """Pydantic model validation for SkillCaptureResult."""

    def test_valid_result(self) -> None:
        result = SkillCaptureResult(
            is_general=True,
            confidence=0.95,
            safety_analysis="No destructive commands detected.",
            name="nginx-502-fix",
            content="---\nname: nginx-502-fix\n---\n# Fix",
            recommended_form="skill",
            form_reasoning="Reusable fix pattern.",
        )
        assert result.is_general is True
        assert result.confidence == 0.95
        assert result.recommended_form == "skill"

    def test_cron_job_form(self) -> None:
        result = SkillCaptureResult(
            is_general=True,
            confidence=0.8,
            safety_analysis="Safe periodic task.",
            name="daily-backup",
            content="---\nname: daily-backup\n---\n# Backup",
            recommended_form="cron_job",
            schedule_hint="every weekday at 9am",
            form_reasoning="Repeated daily task.",
        )
        assert result.recommended_form == "cron_job"
        assert result.schedule_hint == "every weekday at 9am"

    def test_skip_form(self) -> None:
        result = SkillCaptureResult(
            is_general=False,
            confidence=0.2,
            safety_analysis="N/A",
            name="one-off-task",
            content="trivial",
            recommended_form="skip",
            form_reasoning="Too trivial to capture.",
        )
        assert result.recommended_form == "skip"


class TestConfidenceParsing:
    """Confidence field validator handles various LLM outputs."""

    @pytest.mark.parametrize(
        ("input_val", "expected"),
        [
            (0.9, 0.9),
            (1.0, 1.0),
            (0.0, 0.0),
            ("high", 1.0),
            ("very high", 1.0),
            ("certain", 1.0),
            ("medium", 0.5),
            ("moderate", 0.5),
            ("low", 0.1),
            ("very low", 0.1),
            ("uncertain", 0.1),
            ("0.75", 0.75),
            ("garbage", 0.8),  # fallback
        ],
    )
    def test_confidence_parsing(self, input_val: float | str, expected: float) -> None:
        result = SkillCaptureResult(
            is_general=True,
            confidence=input_val,
            safety_analysis="safe",
            name="test",
            content="test",
        )
        assert result.confidence == expected


class TestStructuredExtractor:
    """Integration tests with mocked LLM."""

    @pytest.fixture
    def mock_llm(self) -> MagicMock:
        llm = MagicMock()
        return llm

    @pytest.mark.asyncio
    async def test_structured_output_path(self, mock_llm: MagicMock) -> None:
        """Happy path: LLM returns structured Pydantic object."""
        expected = SkillCaptureResult(
            is_general=True,
            confidence=0.9,
            safety_analysis="Safe",
            name="test-skill",
            content="---\nname: test-skill\n---\n# Test",
            recommended_form="skill",
            form_reasoning="Good skill.",
        )

        structured_llm = MagicMock()
        structured_llm.ainvoke = AsyncMock(return_value=expected)
        mock_llm.with_structured_output = MagicMock(return_value=structured_llm)

        extractor = StructuredExtractor(llm=mock_llm)
        result = await extractor.extract_from_trajectory("User: help\nAssistant: done")

        assert result is not None
        assert result.name == "test-skill"
        assert result.is_general is True
        mock_llm.with_structured_output.assert_called_once_with(SkillCaptureResult)

    @pytest.mark.asyncio
    async def test_fallback_json_path(self, mock_llm: MagicMock) -> None:
        """Fallback: structured output fails, raw JSON parsed from response."""
        mock_llm.with_structured_output = MagicMock(side_effect=Exception("Not supported"))

        raw_json = json.dumps(
            {
                "is_general": True,
                "confidence": 0.85,
                "safety_analysis": "Safe",
                "name": "fallback-skill",
                "content": "---\nname: fallback-skill\n---\n# Fallback",
                "recommended_form": "skill",
                "form_reasoning": "Fallback worked.",
            }
        )
        raw_response = MagicMock()
        raw_response.content = f"Here is the result:\n{raw_json}"
        mock_llm.ainvoke = AsyncMock(return_value=raw_response)

        extractor = StructuredExtractor(llm=mock_llm)
        result = await extractor.extract_from_trajectory("User: complex task\nAssistant: steps...")

        assert result is not None
        assert result.name == "fallback-skill"
        assert result.confidence == 0.85

    @pytest.mark.asyncio
    async def test_total_failure_returns_none(self, mock_llm: MagicMock) -> None:
        """Both paths fail → returns None gracefully."""
        mock_llm.with_structured_output = MagicMock(side_effect=Exception("Fail"))
        raw_response = MagicMock()
        raw_response.content = "I couldn't extract anything meaningful"
        mock_llm.ainvoke = AsyncMock(return_value=raw_response)

        extractor = StructuredExtractor(llm=mock_llm)
        result = await extractor.extract_from_trajectory("casual chat")

        assert result is None
