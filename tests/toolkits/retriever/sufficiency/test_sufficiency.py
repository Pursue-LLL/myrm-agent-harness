"""Unit tests for the Retrieval Sufficiency Guard (RSG).

Covers:
- types.py: SufficiencyVerdict, SufficiencyConfig dataclass behavior
- prompts.py: JSON Schema structure and template formatting
- evaluator.py: _truncate_snippets, _parse_verdict, evaluate_sufficiency
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.retriever.sufficiency import (
    SufficiencyConfig,
    SufficiencyVerdict,
    evaluate_sufficiency,
)
from myrm_agent_harness.toolkits.retriever.sufficiency.evaluator import (
    _FALLBACK_SUFFICIENT,
    _parse_verdict,
    _truncate_snippets,
)
from myrm_agent_harness.toolkits.retriever.sufficiency.prompts import (
    SUFFICIENCY_EVAL_SYSTEM,
    SUFFICIENCY_EVAL_USER_TEMPLATE,
    SUFFICIENCY_JSON_SCHEMA,
)


class TestSufficiencyVerdict:
    """Test SufficiencyVerdict dataclass."""

    def test_defaults(self):
        v = SufficiencyVerdict(is_sufficient=True)
        assert v.is_sufficient is True
        assert v.confidence == 1.0
        assert v.missing_aspects == ()
        assert v.suggested_queries == ()
        assert v.negative_constraint_violations == ()

    def test_full_construction(self):
        v = SufficiencyVerdict(
            is_sufficient=False,
            confidence=0.85,
            missing_aspects=("pricing info",),
            suggested_queries=("product pricing 2024",),
            negative_constraint_violations=("mentions competitor X",),
        )
        assert v.is_sufficient is False
        assert v.confidence == 0.85
        assert len(v.missing_aspects) == 1
        assert len(v.suggested_queries) == 1
        assert len(v.negative_constraint_violations) == 1

    def test_immutability(self):
        v = SufficiencyVerdict(is_sufficient=True)
        with pytest.raises(AttributeError):
            v.is_sufficient = False  # type: ignore[misc]


class TestSufficiencyConfig:
    """Test SufficiencyConfig dataclass."""

    def test_defaults(self):
        c = SufficiencyConfig()
        assert c.enabled is False
        assert c.confidence_threshold == 0.6
        assert c.max_iterations == 3
        assert c.max_snippets_for_eval == 4000

    def test_custom_values(self):
        c = SufficiencyConfig(enabled=True, confidence_threshold=0.8, max_iterations=5, max_snippets_for_eval=8000)
        assert c.enabled is True
        assert c.confidence_threshold == 0.8
        assert c.max_iterations == 5
        assert c.max_snippets_for_eval == 8000

    def test_immutability(self):
        c = SufficiencyConfig(enabled=True)
        with pytest.raises(AttributeError):
            c.enabled = False  # type: ignore[misc]


class TestPrompts:
    """Test prompt templates and JSON schema."""

    def test_json_schema_structure(self):
        assert SUFFICIENCY_JSON_SCHEMA["type"] == "object"
        props = SUFFICIENCY_JSON_SCHEMA["properties"]
        assert "is_sufficient" in props
        assert "confidence" in props
        assert "missing_aspects" in props
        assert "suggested_queries" in props
        assert "negative_constraint_violations" in props
        assert SUFFICIENCY_JSON_SCHEMA["additionalProperties"] is False

    def test_required_fields(self):
        required = SUFFICIENCY_JSON_SCHEMA["required"]
        assert set(required) == {
            "is_sufficient",
            "confidence",
            "missing_aspects",
            "suggested_queries",
            "negative_constraint_violations",
        }

    def test_user_template_formatting(self):
        formatted = SUFFICIENCY_EVAL_USER_TEMPLATE.format(
            query="What is Python?",
            snippets="Python is a programming language.",
        )
        assert "What is Python?" in formatted
        assert "Python is a programming language." in formatted

    def test_system_prompt_contains_negative_constraint_keywords(self):
        assert "except" in SUFFICIENCY_EVAL_SYSTEM
        assert "excluding" in SUFFICIENCY_EVAL_SYSTEM
        assert "除了" in SUFFICIENCY_EVAL_SYSTEM
        assert "不包括" in SUFFICIENCY_EVAL_SYSTEM
        assert "排除" in SUFFICIENCY_EVAL_SYSTEM


class TestTruncateSnippets:
    """Test _truncate_snippets utility."""

    def test_short_text_unchanged(self):
        text = "short text"
        result = _truncate_snippets(text, 1000)
        assert result == text

    def test_exact_boundary(self):
        text = "x" * 100
        result = _truncate_snippets(text, 100)
        assert result == text

    def test_truncation(self):
        text = "a" * 200
        result = _truncate_snippets(text, 50)
        assert result.startswith("a" * 50)
        assert "[... truncated for evaluation ...]" in result
        assert len(result) < 200


class TestParseVerdict:
    """Test _parse_verdict JSON parsing logic."""

    def setup_method(self):
        self.config = SufficiencyConfig(enabled=True, confidence_threshold=0.6)

    def test_valid_sufficient_json(self):
        raw = json.dumps({
            "is_sufficient": True,
            "confidence": 0.95,
            "missing_aspects": [],
            "suggested_queries": [],
            "negative_constraint_violations": [],
        })
        v = _parse_verdict(raw, self.config)
        assert v.is_sufficient is True
        assert v.confidence == 0.95

    def test_valid_insufficient_json(self):
        raw = json.dumps({
            "is_sufficient": False,
            "confidence": 0.8,
            "missing_aspects": ["pricing data"],
            "suggested_queries": ["product pricing 2024"],
            "negative_constraint_violations": ["mentions competitor"],
        })
        v = _parse_verdict(raw, self.config)
        assert v.is_sufficient is False
        assert v.missing_aspects == ("pricing data",)
        assert v.suggested_queries == ("product pricing 2024",)
        assert v.negative_constraint_violations == ("mentions competitor",)

    def test_low_confidence_discarded(self):
        raw = json.dumps({
            "is_sufficient": False,
            "confidence": 0.3,
            "missing_aspects": ["something"],
            "suggested_queries": [],
            "negative_constraint_violations": [],
        })
        v = _parse_verdict(raw, self.config)
        assert v.is_sufficient is True
        assert v.confidence == 0.0

    def test_invalid_json_returns_fallback(self):
        v = _parse_verdict("this is not json", self.config)
        assert v is _FALLBACK_SUFFICIENT

    def test_markdown_code_block_stripping(self):
        inner = json.dumps({
            "is_sufficient": True,
            "confidence": 0.9,
            "missing_aspects": [],
            "suggested_queries": [],
            "negative_constraint_violations": [],
        })
        raw = f"```json\n{inner}\n```"
        v = _parse_verdict(raw, self.config)
        assert v.is_sufficient is True
        assert v.confidence == 0.9

    def test_missing_confidence_defaults_zero(self):
        raw = json.dumps({
            "is_sufficient": False,
            "missing_aspects": ["x"],
            "suggested_queries": [],
            "negative_constraint_violations": [],
        })
        v = _parse_verdict(raw, self.config)
        assert v is _FALLBACK_SUFFICIENT


class TestEvaluateSufficiency:
    """Test evaluate_sufficiency async function."""

    @pytest.fixture
    def mock_llm_config(self):
        config = MagicMock()
        config.model = "gpt-4o-mini"
        config.api_key = "sk-test"
        config.base_url = None
        config.model_kwargs = None
        return config

    @pytest.mark.asyncio
    async def test_disabled_config_returns_fallback(self, mock_llm_config):
        config = SufficiencyConfig(enabled=False)
        result = await evaluate_sufficiency("test query", "some snippets", mock_llm_config, config)
        assert result.is_sufficient is True
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_none_config_returns_fallback(self, mock_llm_config):
        result = await evaluate_sufficiency("test query", "some snippets", mock_llm_config, None)
        assert result.is_sufficient is True
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_empty_snippets_returns_insufficient(self, mock_llm_config):
        config = SufficiencyConfig(enabled=True)
        result = await evaluate_sufficiency("test query", "", mock_llm_config, config)
        assert result.is_sufficient is False
        assert result.confidence == 1.0
        assert "No results retrieved." in result.missing_aspects

    @pytest.mark.asyncio
    async def test_whitespace_only_snippets_returns_insufficient(self, mock_llm_config):
        config = SufficiencyConfig(enabled=True)
        result = await evaluate_sufficiency("test query", "   \n  ", mock_llm_config, config)
        assert result.is_sufficient is False

    @pytest.mark.asyncio
    async def test_successful_evaluation(self, mock_llm_config):
        config = SufficiencyConfig(enabled=True)
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "is_sufficient": False,
            "confidence": 0.85,
            "missing_aspects": ["pricing info"],
            "suggested_queries": ["product pricing"],
            "negative_constraint_violations": [],
        })

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = mock_response

        with patch(
            "myrm_agent_harness.toolkits.retriever.sufficiency.evaluator._build_eval_model",
            return_value=mock_model,
        ):
            result = await evaluate_sufficiency("find products except X", "some content", mock_llm_config, config)

        assert result.is_sufficient is False
        assert result.confidence == 0.85
        assert result.missing_aspects == ("pricing info",)
        mock_model.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_exception_returns_failopen(self, mock_llm_config):
        config = SufficiencyConfig(enabled=True)

        with patch(
            "myrm_agent_harness.toolkits.retriever.sufficiency.evaluator._build_eval_model",
            side_effect=RuntimeError("LLM connection failed"),
        ):
            result = await evaluate_sufficiency("test query", "some content", mock_llm_config, config)

        assert result.is_sufficient is True
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_negative_constraint_detection(self, mock_llm_config):
        config = SufficiencyConfig(enabled=True)
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "is_sufficient": False,
            "confidence": 0.9,
            "missing_aspects": [],
            "suggested_queries": [],
            "negative_constraint_violations": ["contains recommendation for competitor X"],
        })

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = mock_response

        with patch(
            "myrm_agent_harness.toolkits.retriever.sufficiency.evaluator._build_eval_model",
            return_value=mock_model,
        ):
            result = await evaluate_sufficiency(
                "recommend AI tools except X",
                "Here is X, it's great...",
                mock_llm_config,
                config,
            )

        assert result.is_sufficient is False
        assert "competitor X" in result.negative_constraint_violations[0]

    @pytest.mark.asyncio
    async def test_truncation_applied_to_long_snippets(self, mock_llm_config):
        config = SufficiencyConfig(enabled=True, max_snippets_for_eval=100)
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "is_sufficient": True,
            "confidence": 0.9,
            "missing_aspects": [],
            "suggested_queries": [],
            "negative_constraint_violations": [],
        })

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = mock_response

        long_snippets = "a" * 5000

        with patch(
            "myrm_agent_harness.toolkits.retriever.sufficiency.evaluator._build_eval_model",
            return_value=mock_model,
        ):
            result = await evaluate_sufficiency("test", long_snippets, mock_llm_config, config)

        assert result.is_sufficient is True
        call_args = mock_model.ainvoke.call_args[0][0]
        user_msg_content = call_args[1].content
        assert "[... truncated for evaluation ...]" in user_msg_content

    @pytest.mark.asyncio
    async def test_response_without_content_attr(self, mock_llm_config):
        """Edge case: LLM response object has no .content attribute — falls back to str()."""
        config = SufficiencyConfig(enabled=True)

        class NoContentResponse:
            def __str__(self):
                return json.dumps({
                    "is_sufficient": True,
                    "confidence": 0.7,
                    "missing_aspects": [],
                    "suggested_queries": [],
                    "negative_constraint_violations": [],
                })

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = NoContentResponse()

        with patch(
            "myrm_agent_harness.toolkits.retriever.sufficiency.evaluator._build_eval_model",
            return_value=mock_model,
        ):
            result = await evaluate_sufficiency("test", "content", mock_llm_config, config)

        assert result.is_sufficient is True
        assert result.confidence == 0.7

    @pytest.mark.asyncio
    async def test_ainvoke_timeout_returns_failopen(self, mock_llm_config):
        """Edge case: LLM ainvoke raises TimeoutError."""
        config = SufficiencyConfig(enabled=True)

        mock_model = AsyncMock()
        mock_model.ainvoke.side_effect = TimeoutError("Request timed out")

        with patch(
            "myrm_agent_harness.toolkits.retriever.sufficiency.evaluator._build_eval_model",
            return_value=mock_model,
        ):
            result = await evaluate_sufficiency("test", "content", mock_llm_config, config)

        assert result.is_sufficient is True
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_sufficient_result_does_not_add_guidance(self, mock_llm_config):
        """When verdict is sufficient, no guidance should be returned."""
        config = SufficiencyConfig(enabled=True)
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "is_sufficient": True,
            "confidence": 0.95,
            "missing_aspects": [],
            "suggested_queries": [],
            "negative_constraint_violations": [],
        })

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = mock_response

        with patch(
            "myrm_agent_harness.toolkits.retriever.sufficiency.evaluator._build_eval_model",
            return_value=mock_model,
        ):
            result = await evaluate_sufficiency("test", "content", mock_llm_config, config)

        assert result.is_sufficient is True
        assert result.missing_aspects == ()
        assert result.suggested_queries == ()
        assert result.negative_constraint_violations == ()


class TestParseVerdictEdgeCases:
    """Additional edge cases for _parse_verdict."""

    def setup_method(self):
        self.config = SufficiencyConfig(enabled=True, confidence_threshold=0.6)

    def test_extra_whitespace_around_json(self):
        raw = "   \n  " + json.dumps({
            "is_sufficient": True,
            "confidence": 0.8,
            "missing_aspects": [],
            "suggested_queries": [],
            "negative_constraint_violations": [],
        }) + "  \n  "
        v = _parse_verdict(raw, self.config)
        assert v.is_sufficient is True

    def test_partial_json_returns_fallback(self):
        v = _parse_verdict('{"is_sufficient": true, "confidence":', self.config)
        assert v is _FALLBACK_SUFFICIENT

    def test_empty_string_returns_fallback(self):
        v = _parse_verdict("", self.config)
        assert v is _FALLBACK_SUFFICIENT

    def test_confidence_at_exact_threshold(self):
        raw = json.dumps({
            "is_sufficient": False,
            "confidence": 0.6,
            "missing_aspects": ["data"],
            "suggested_queries": ["query"],
            "negative_constraint_violations": [],
        })
        v = _parse_verdict(raw, self.config)
        assert v.is_sufficient is False
        assert v.confidence == 0.6

    def test_confidence_just_below_threshold(self):
        raw = json.dumps({
            "is_sufficient": False,
            "confidence": 0.59,
            "missing_aspects": ["data"],
            "suggested_queries": [],
            "negative_constraint_violations": [],
        })
        v = _parse_verdict(raw, self.config)
        assert v is _FALLBACK_SUFFICIENT
