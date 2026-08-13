"""Tests for the semantic assertion exact-match pre-pass (deterministic short-circuit)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.eval.assertions import (
    _exact_match_prepass,
    evaluate_semantic_assertions,
)
from myrm_agent_harness.eval.protocols import SemanticAssertion


class TestExactMatchPrepass:
    def test_identical_answers_match(self) -> None:
        assert _exact_match_prepass("42", "42") is True

    def test_case_and_space_insensitive(self) -> None:
        assert _exact_match_prepass("Berlin, Germany", "berlin germany") is True

    def test_punctuation_insensitive(self) -> None:
        # Percent signs / trailing marks are stripped on both sides.
        assert _exact_match_prepass("42%", "42") is True

    def test_different_answers_do_not_match(self) -> None:
        assert _exact_match_prepass("Paris", "Berlin") is False

    def test_empty_output_never_matches(self) -> None:
        assert _exact_match_prepass("42", "") is False
        assert _exact_match_prepass("", "42") is False

    def test_blank_expected_never_matches(self) -> None:
        assert _exact_match_prepass("   ", "42") is False


class TestSemanticAssertionShortCircuit:
    async def _run(self, expected: str, actual: str) -> tuple[bool | None, str | None]:
        assertion = SemanticAssertion(
            type="llm_judge", expected=expected, threshold=1.0
        )
        # acompletion is never reached on an exact match; if the code calls it,
        # the AsyncMock raises and the test fails loudly.
        with patch(
            "litellm.acompletion",
            new_callable=AsyncMock,
        ) as mock_completion:
            result = await evaluate_semantic_assertions([assertion], actual)
            assert mock_completion.await_count == 0
        return result

    def _judge_response(self, content: str) -> object:
        """Build a litellm-compatible completion object whose text is ``content``."""
        message = type("M", (), {"content": content})()
        choice = type("C", (), {"message": message})()
        return type("R", (), {"choices": [choice]})()

    @pytest.mark.asyncio
    async def test_exact_match_passes_without_llm(self) -> None:
        passed, _details = await self._run("42", "42")
        assert passed is True

    @pytest.mark.asyncio
    async def test_normalized_match_passes_without_llm(self) -> None:
        passed, _details = await self._run("Berlin, Germany", "berlin germany")
        assert passed is True

    @pytest.mark.asyncio
    async def test_scoring_threshold_bypasses_shortcut(self) -> None:
        """Soft-scoring (threshold < 1.0) must not short-circuit on exact match."""
        assertion = SemanticAssertion(type="llm_judge", expected="0.75", threshold=0.7)
        with patch(
            "litellm.acompletion",
            new_callable=AsyncMock,
            return_value=self._judge_response("0.9"),
        ) as mock_completion:
            passed, _ = await evaluate_semantic_assertions([assertion], "0.75")
            assert passed is True
            assert mock_completion.await_count == 1

    @pytest.mark.asyncio
    async def test_non_match_still_calls_llm(self) -> None:
        assertion = SemanticAssertion(type="llm_judge", expected="Paris", threshold=1.0)
        with patch(
            "litellm.acompletion",
            new_callable=AsyncMock,
            return_value=self._judge_response("FAIL: wrong city"),
        ) as mock_completion:
            passed, details = await evaluate_semantic_assertions([assertion], "Berlin")
            assert passed is False
            assert "FAIL" in details
            assert mock_completion.await_count == 1
