"""Unit tests for pattern discovery strategy schema/prompt alignment.

Protects the real-LLM happy path from regressions: the LLM output fields
must map onto ``DiscoveredPattern`` (alias tolerance) and the system prompt
must teach the exact field names.
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.strategies.pattern_discovery import (
    _PROFILE_KEY_MEMORY_SET_HASH,
    _SYSTEM_PROMPT,
    DiscoveredPattern,
    PatternDurability,
    run_pattern_discovery,
)
from myrm_agent_harness.toolkits.memory.types import SemanticMemory


class TestDiscoveredPatternAliasTolerance:
    """LLM natural-language aliases must map onto schema field names."""

    @pytest.mark.parametrize(
        ("raw", "expected_title", "expected_evidence", "expected_suggestion"),
        [
            (
                {
                    "title": "morning review",
                    "description": "starts with reviews",
                    "evidence_summary": "seen across sessions",
                    "actionable_suggestion": "block deep work",
                },
                "morning review",
                "seen across sessions",
                "block deep work",
            ),
            (
                {
                    "category": "morning review",
                    "description": "starts with reviews",
                    "evidence": "seen across sessions",
                    "suggestion": "block deep work",
                },
                "morning review",
                "seen across sessions",
                "block deep work",
            ),
        ],
    )
    def test_aliases_map_to_fields(
        self,
        raw: dict[str, object],
        expected_title: str,
        expected_evidence: str,
        expected_suggestion: str,
    ) -> None:
        pattern = DiscoveredPattern.model_validate(raw)
        assert pattern.title == expected_title
        assert pattern.evidence_summary == expected_evidence
        assert pattern.actionable_suggestion == expected_suggestion

    def test_defaults_apply(self) -> None:
        pattern = DiscoveredPattern(
            title="t",
            description="d",
            evidence_summary="e",
        )
        assert pattern.durability == PatternDurability.EMERGING
        assert pattern.confidence == pytest.approx(0.7)
        assert pattern.actionable_suggestion == ""


class TestSystemPromptFieldAlignment:
    """The system prompt must teach the exact schema field names."""

    _REQUIRED_FIELDS = (
        '"title"',
        '"description"',
        '"evidence_summary"',
        '"durability"',
        '"confidence"',
        '"actionable_suggestion"',
    )

    @pytest.mark.parametrize("field", _REQUIRED_FIELDS)
    def test_prompt_teaches_field_name(self, field: str) -> None:
        assert field in _SYSTEM_PROMPT

    def test_prompt_warns_against_wrong_field_names(self) -> None:
        assert "not category" in _SYSTEM_PROMPT
        assert "not evidence" in _SYSTEM_PROMPT
        assert "not suggestion" in _SYSTEM_PROMPT


class TestRunPatternDiscoveryGate:
    """Maturity gate short-circuits before any LLM call."""

    def _immature_manager(self) -> AsyncMock:
        manager = AsyncMock()
        manager.has_relational = True
        manager.has_vector = True
        manager.count_memories = AsyncMock(return_value=5)
        return manager

    async def test_skips_when_not_enough_memories(self) -> None:
        llm = AsyncMock()
        report = await run_pattern_discovery(self._immature_manager(), llm)

        assert report.skipped is True
        assert "mature" in report.skip_reason
        llm.assert_not_called()


class TestMemorySetHashSkip:
    """Memory set unchanged short-circuits the LLM call."""

    async def test_skips_when_hash_unchanged(self) -> None:
        mem = SemanticMemory(content="some memory")

        async def _list(*_args: object, **_kwargs: object) -> list[SemanticMemory]:
            return [mem]

        async def _get_profile(key: str) -> object:
            if key == _PROFILE_KEY_MEMORY_SET_HASH:
                # Two lists (SEMANTIC + EPISODIC) each return [mem].
                duplicated = sorted([mem.id, mem.id])
                return hashlib.sha256("|".join(duplicated).encode()).hexdigest()[:16]
            return "5"

        manager = AsyncMock()
        manager.has_relational = True
        manager.has_vector = True
        manager.has_graph = False
        manager.count_memories = AsyncMock(return_value=60)
        manager.list_memories = _list
        manager.get_profile_attribute = _get_profile
        manager.set_profile_attribute = AsyncMock()
        manager.search = AsyncMock(return_value=[])

        llm = AsyncMock()
        report = await run_pattern_discovery(manager, llm)

        assert report.skipped is True
        assert "unchanged" in report.skip_reason
        llm.assert_not_called()
