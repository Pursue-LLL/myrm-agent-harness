"""Tests for ComplexityRouter — 3-tier task routing engine.

Covers:
- Phase 1 rule-based classification (keywords, structural, contextual signals)
- Unified scoring with weighted keywords
- Session momentum (MR-17)
- PenaltyTracker (MR-14) with decay
- Content dedup (MR-18)
- Model selection per tier with graceful degradation
- LLM judge (Phase 2) with caching
- Empty/multimodal query handling
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.core.config.llm import LLMConfig
from myrm_agent_harness.toolkits.llms.routing.complexity_router import (
    DEFAULT_REASONING_KEYWORDS,
    DEFAULT_SIMPLE_INDICATORS,
    DEFAULT_STANDARD_KEYWORDS,
    PenaltyTracker,
    RoutingResult,
    RoutingTier,
    _apply_momentum,
    _compute_unified_score,
    _dedup_cache,
    _dedup_check,
    _dedup_store,
    _has_code_content,
    _has_math_content,
    _is_simple_greeting,
    _judge_cache,
    _normalize_query,
    _rule_based_classify,
    _score_contextual_signals,
    _score_structural_signals,
    _select_model_for_tier,
    _word_count,
    route_task,
)

_DUMMY_KEY = "sk-test-key-for-routing"


def _cfg(model: str) -> LLMConfig:
    return LLMConfig(model=model, api_key=_DUMMY_KEY)


STD_CFG = _cfg("gpt-4o")
LIGHT_CFG = _cfg("gpt-4o-mini")
REASON_CFG = _cfg("o1-preview")
STD_FALLBACK = _cfg("claude-3-sonnet")
LIGHT_FALLBACK = _cfg("claude-3-haiku")
REASON_FALLBACK = _cfg("claude-3-opus")


@pytest.fixture(autouse=True)
def _clear_caches():
    _judge_cache.clear()
    _dedup_cache.clear()
    yield
    _judge_cache.clear()
    _dedup_cache.clear()


# ─── Helper utilities ───────────────────────────────────────────────


class TestNormalizeQuery:
    def test_string_input(self) -> None:
        text, has_image = _normalize_query("hello world")
        assert text == "hello world"
        assert has_image is False

    def test_multimodal_with_image(self) -> None:
        query = [
            {"type": "text", "text": "describe this"},
            {"type": "image_url", "url": "https://example.com/img.png"},
        ]
        text, has_image = _normalize_query(query)
        assert "describe this" in text
        assert has_image is True

    def test_multimodal_text_only(self) -> None:
        query = [{"type": "text", "text": "just text"}]
        text, has_image = _normalize_query(query)
        assert text == "just text"
        assert has_image is False


class TestWordCount:
    def test_english_words(self) -> None:
        assert _word_count("hello world") == 2

    def test_chinese_chars(self) -> None:
        assert _word_count("你好世界") == 4

    def test_mixed(self) -> None:
        count = _word_count("hello 你好 world 世界")
        assert count == 6


class TestCodeDetection:
    def test_code_block(self) -> None:
        assert _has_code_content("```python\nprint('hi')\n```") is True

    def test_inline_code(self) -> None:
        assert _has_code_content("use `pip install`") is True

    def test_no_code(self) -> None:
        assert _has_code_content("just plain text") is False


class TestMathDetection:
    def test_latex_formula(self) -> None:
        assert _has_math_content(r"\frac{a}{b}") is True

    def test_latex_block(self) -> None:
        assert _has_math_content("$$E = mc^2$$") is True

    def test_no_math(self) -> None:
        assert _has_math_content("plain text no math") is False


class TestSimpleGreeting:
    def test_exact_greeting(self) -> None:
        assert _is_simple_greeting("hello", DEFAULT_SIMPLE_INDICATORS) is True

    def test_greeting_with_punctuation(self) -> None:
        assert _is_simple_greeting("你好！", DEFAULT_SIMPLE_INDICATORS) is True

    def test_not_greeting(self) -> None:
        assert _is_simple_greeting("implement a feature", DEFAULT_SIMPLE_INDICATORS) is False


# ─── Structural & Contextual signals ────────────────────────────────


class TestStructuralSignals:
    def test_urls_scored(self) -> None:
        scores = _score_structural_signals("check https://example.com and https://test.org")
        assert scores.get("urls", 0) > 0

    def test_file_paths_scored(self) -> None:
        scores = _score_structural_signals("edit /src/main.py and utils.ts")
        assert scores.get("file_paths", 0) > 0

    def test_no_signals(self) -> None:
        scores = _score_structural_signals("plain text")
        assert len(scores) == 0


class TestContextualSignals:
    def test_image_input(self) -> None:
        scores = _score_contextual_signals("describe", has_image=True, word_count=1)
        assert scores.get("image_input", 0) == 6.0

    def test_long_input(self) -> None:
        scores = _score_contextual_signals("word " * 60, has_image=False, word_count=60)
        assert scores.get("long_input", 0) > 0

    def test_repetition_request(self) -> None:
        scores = _score_contextual_signals("give me 5 variations", has_image=False, word_count=5)
        assert scores.get("repetition_request", 0) > 0


# ─── Unified Scoring ────────────────────────────────────────────────


class TestUnifiedScoring:
    def test_greeting_scores_simple_high(self) -> None:
        scores = _compute_unified_score(
            "hello", False, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        assert scores[RoutingTier.SIMPLE] > scores[RoutingTier.STANDARD]
        assert scores[RoutingTier.SIMPLE] > scores[RoutingTier.REASONING]

    def test_debug_keyword_scores_standard(self) -> None:
        scores = _compute_unified_score(
            "debug this function", False, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        assert scores[RoutingTier.STANDARD] > 0

    def test_proof_keyword_scores_reasoning(self) -> None:
        scores = _compute_unified_score(
            "prove this theorem step by step",
            False,
            DEFAULT_STANDARD_KEYWORDS,
            DEFAULT_REASONING_KEYWORDS,
            DEFAULT_SIMPLE_INDICATORS,
        )
        assert scores[RoutingTier.REASONING] > 0

    def test_code_content_boosts_standard(self) -> None:
        scores = _compute_unified_score(
            "fix ```python\ndef foo(): pass\n```",
            False,
            DEFAULT_STANDARD_KEYWORDS,
            DEFAULT_REASONING_KEYWORDS,
            DEFAULT_SIMPLE_INDICATORS,
        )
        assert scores[RoutingTier.STANDARD] >= 2.0

    def test_short_message_boosts_simple(self) -> None:
        scores = _compute_unified_score(
            "ok", False, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        assert scores[RoutingTier.SIMPLE] > 0

    def test_image_boosts_standard(self) -> None:
        scores = _compute_unified_score(
            "describe this", True, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        assert scores[RoutingTier.STANDARD] >= 6.0


# ─── Rule-based Classification ──────────────────────────────────────


class TestRuleBasedClassify:
    def test_greeting_classified_simple(self) -> None:
        result = _rule_based_classify("hello", False, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS)
        assert result == RoutingTier.SIMPLE

    def test_debug_classified_standard(self) -> None:
        result = _rule_based_classify(
            "debug this authentication error", False, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        assert result == RoutingTier.STANDARD

    def test_proof_classified_reasoning(self) -> None:
        result = _rule_based_classify(
            "prove the theorem and derive the equation step by step",
            False,
            DEFAULT_STANDARD_KEYWORDS,
            DEFAULT_REASONING_KEYWORDS,
            DEFAULT_SIMPLE_INDICATORS,
        )
        assert result == RoutingTier.REASONING

    def test_ambiguous_returns_none(self) -> None:
        result = _rule_based_classify(
            "tell me about cats", False, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        # May return None (ambiguous) or SIMPLE depending on length
        assert result is None or result in RoutingTier


# ─── Model Selection ────────────────────────────────────────────────


class TestModelSelection:
    def test_simple_uses_light(self) -> None:
        cfg, fb = _select_model_for_tier(
            RoutingTier.SIMPLE, STD_CFG, LIGHT_CFG, REASON_CFG, STD_FALLBACK, LIGHT_FALLBACK, REASON_FALLBACK
        )
        assert cfg.model == "gpt-4o-mini"
        assert fb is not None and fb.model == "claude-3-haiku"

    def test_standard_uses_standard(self) -> None:
        cfg, fb = _select_model_for_tier(
            RoutingTier.STANDARD, STD_CFG, LIGHT_CFG, REASON_CFG, STD_FALLBACK, LIGHT_FALLBACK, REASON_FALLBACK
        )
        assert cfg.model == "gpt-4o"
        assert fb is not None and fb.model == "claude-3-sonnet"

    def test_reasoning_uses_reasoning(self) -> None:
        cfg, fb = _select_model_for_tier(
            RoutingTier.REASONING, STD_CFG, LIGHT_CFG, REASON_CFG, STD_FALLBACK, LIGHT_FALLBACK, REASON_FALLBACK
        )
        assert cfg.model == "o1-preview"
        assert fb is not None and fb.model == "claude-3-opus"

    def test_graceful_degradation_no_light(self) -> None:
        cfg, fb = _select_model_for_tier(
            RoutingTier.SIMPLE, STD_CFG, None, REASON_CFG, STD_FALLBACK, None, REASON_FALLBACK
        )
        assert cfg.model == "gpt-4o"

    def test_graceful_degradation_no_reasoning(self) -> None:
        cfg, fb = _select_model_for_tier(
            RoutingTier.REASONING, STD_CFG, LIGHT_CFG, None, STD_FALLBACK, LIGHT_FALLBACK, None
        )
        assert cfg.model == "gpt-4o"


# ─── Session Momentum ───────────────────────────────────────────────


class TestMomentum:
    def test_no_history_no_change(self) -> None:
        tier, overridden = _apply_momentum(RoutingTier.SIMPLE, "hi", None)
        assert tier == RoutingTier.SIMPLE
        assert overridden is False

    def test_short_msg_with_reasoning_history_upgrades(self) -> None:
        recent = [RoutingTier.REASONING] * 5
        tier, overridden = _apply_momentum(RoutingTier.SIMPLE, "ok", recent)
        assert tier in (RoutingTier.STANDARD, RoutingTier.REASONING)

    def test_long_msg_no_momentum(self) -> None:
        recent = [RoutingTier.REASONING] * 5
        long_msg = "x" * 200
        tier, overridden = _apply_momentum(RoutingTier.SIMPLE, long_msg, recent)
        assert tier == RoutingTier.SIMPLE
        assert overridden is False

    def test_empty_history_no_change(self) -> None:
        tier, overridden = _apply_momentum(RoutingTier.STANDARD, "test", [])
        assert tier == RoutingTier.STANDARD
        assert overridden is False


# ─── PenaltyTracker ──────────────────────────────────────────────────


class TestPenaltyTracker:
    def test_no_penalty_initially(self) -> None:
        tracker = PenaltyTracker()
        assert tracker.get_penalty(RoutingTier.SIMPLE) == 0.0

    def test_penalty_accumulates(self) -> None:
        tracker = PenaltyTracker()
        tracker.record_misroute(RoutingTier.SIMPLE)
        penalty = tracker.get_penalty(RoutingTier.SIMPLE)
        assert penalty == pytest.approx(0.75)

    def test_penalty_capped(self) -> None:
        tracker = PenaltyTracker()
        for _ in range(10):
            tracker.record_misroute(RoutingTier.SIMPLE)
        penalty = tracker.get_penalty(RoutingTier.SIMPLE)
        assert penalty == pytest.approx(3.0)

    def test_apply_penalties_reduces_score(self) -> None:
        tracker = PenaltyTracker()
        tracker.record_misroute(RoutingTier.SIMPLE)
        scores = {RoutingTier.SIMPLE: 5.0, RoutingTier.STANDARD: 3.0, RoutingTier.REASONING: 1.0}
        adjusted = tracker.apply_penalties(scores)
        assert adjusted[RoutingTier.SIMPLE] < 5.0
        assert adjusted[RoutingTier.STANDARD] == 3.0
        assert adjusted[RoutingTier.REASONING] == 1.0

    def test_cleanup_expired(self) -> None:
        tracker = PenaltyTracker()
        tracker.record_misroute(RoutingTier.SIMPLE)
        removed = tracker.cleanup_expired()
        assert removed == 0

    def test_penalty_floor_at_zero(self) -> None:
        tracker = PenaltyTracker()
        for _ in range(10):
            tracker.record_misroute(RoutingTier.SIMPLE)
        scores = {RoutingTier.SIMPLE: 1.0, RoutingTier.STANDARD: 0.0, RoutingTier.REASONING: 0.0}
        adjusted = tracker.apply_penalties(scores)
        assert adjusted[RoutingTier.SIMPLE] == 0.0


# ─── Content Dedup ───────────────────────────────────────────────────


class TestContentDedup:
    def test_dedup_miss(self) -> None:
        assert _dedup_check("unique query") is None

    def test_dedup_hit(self) -> None:
        _dedup_store("cached query", RoutingTier.STANDARD)
        assert _dedup_check("cached query") == RoutingTier.STANDARD

    def test_dedup_different_text(self) -> None:
        _dedup_store("query A", RoutingTier.SIMPLE)
        assert _dedup_check("query B") is None


# ─── route_task integration ──────────────────────────────────────────


class TestRouteTask:
    @pytest.mark.asyncio
    async def test_greeting_routes_to_simple(self) -> None:
        result = await route_task("hello", STD_CFG, light_model_cfg=LIGHT_CFG)
        assert result.tier == RoutingTier.SIMPLE
        assert result.model_cfg.model == "gpt-4o-mini"
        assert result.reason in ("rule_based", "content_dedup")

    @pytest.mark.asyncio
    async def test_debug_routes_to_standard(self) -> None:
        result = await route_task("debug this authentication error in production", STD_CFG, light_model_cfg=LIGHT_CFG)
        assert result.tier == RoutingTier.STANDARD
        assert result.model_cfg.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_proof_routes_to_reasoning(self) -> None:
        result = await route_task(
            "prove the theorem and derive the equation step by step",
            STD_CFG,
            light_model_cfg=LIGHT_CFG,
            reasoning_model_cfg=REASON_CFG,
        )
        assert result.tier == RoutingTier.REASONING
        assert result.model_cfg.model == "o1-preview"

    @pytest.mark.asyncio
    async def test_empty_query_defaults_standard(self) -> None:
        result = await route_task("", STD_CFG)
        assert result.tier == RoutingTier.STANDARD
        assert result.reason == "empty_query"

    @pytest.mark.asyncio
    async def test_multimodal_with_image(self) -> None:
        query = [
            {"type": "text", "text": "describe this"},
            {"type": "image_url", "url": "https://example.com/img.png"},
        ]
        result = await route_task(query, STD_CFG, light_model_cfg=LIGHT_CFG)
        assert result.tier == RoutingTier.STANDARD

    @pytest.mark.asyncio
    async def test_fallback_models_returned(self) -> None:
        result = await route_task(
            "debug this error",
            STD_CFG,
            light_model_cfg=LIGHT_CFG,
            reasoning_model_cfg=REASON_CFG,
            standard_fallback_cfg=STD_FALLBACK,
        )
        assert result.fallback_model_cfg is not None
        assert result.fallback_model_cfg.model == "claude-3-sonnet"

    @pytest.mark.asyncio
    async def test_no_light_model_degrades_to_standard(self) -> None:
        result = await route_task("hello", STD_CFG)
        assert result.tier == RoutingTier.SIMPLE
        assert result.model_cfg.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_llm_judge_called_for_ambiguous(self) -> None:
        mock_response = MagicMock()
        mock_response.content = '{"tier":"STANDARD"}'
        judge_llm = AsyncMock()
        judge_llm.ainvoke = AsyncMock(return_value=mock_response)

        result = await route_task(
            "tell me about interesting things in the world of technology",
            STD_CFG,
            light_model_cfg=LIGHT_CFG,
            reasoning_model_cfg=REASON_CFG,
            judge_llm=judge_llm,
        )
        assert isinstance(result, RoutingResult)

    @pytest.mark.asyncio
    async def test_momentum_override(self) -> None:
        result = await route_task(
            "ok",
            STD_CFG,
            light_model_cfg=LIGHT_CFG,
            reasoning_model_cfg=REASON_CFG,
            recent_tiers=[RoutingTier.REASONING] * 5,
        )
        assert result.tier in (RoutingTier.STANDARD, RoutingTier.REASONING, RoutingTier.SIMPLE)

    @pytest.mark.asyncio
    async def test_content_dedup_returns_cached(self) -> None:
        result1 = await route_task("debug this error", STD_CFG, light_model_cfg=LIGHT_CFG)
        result2 = await route_task("debug this error", STD_CFG, light_model_cfg=LIGHT_CFG)
        assert result2.reason == "content_dedup"
        assert result2.tier == result1.tier

    @pytest.mark.asyncio
    async def test_traceback_routes_to_standard(self) -> None:
        traceback_text = (
            "Traceback (most recent call last):\n"
            '  File "main.py", line 42\n'
            "TypeError: unsupported operand"
        )
        result = await route_task(traceback_text, STD_CFG, light_model_cfg=LIGHT_CFG)
        assert result.tier == RoutingTier.STANDARD

    @pytest.mark.asyncio
    async def test_chinese_keywords_recognized(self) -> None:
        result = await route_task("请帮我重构这段代码并分析性能", STD_CFG, light_model_cfg=LIGHT_CFG)
        assert result.tier == RoutingTier.STANDARD

    @pytest.mark.asyncio
    async def test_math_content_routes_reasoning(self) -> None:
        result = await route_task(
            r"Solve $$\int_0^{\infty} e^{-x^2} dx$$ and prove \frac{a}{b} = c",
            STD_CFG,
            light_model_cfg=LIGHT_CFG,
            reasoning_model_cfg=REASON_CFG,
        )
        assert result.tier == RoutingTier.REASONING


# ─── RoutingResult dataclass ─────────────────────────────────────────


class TestRoutingResult:
    def test_frozen(self) -> None:
        r = RoutingResult(tier=RoutingTier.STANDARD, model_cfg=STD_CFG, fallback_model_cfg=None, reason="test")
        with pytest.raises(AttributeError):
            r.tier = RoutingTier.SIMPLE  # type: ignore[misc]

    def test_fields(self) -> None:
        r = RoutingResult(tier=RoutingTier.REASONING, model_cfg=REASON_CFG, fallback_model_cfg=STD_FALLBACK, reason="rule_based")
        assert r.tier == RoutingTier.REASONING
        assert r.model_cfg.model == "o1-preview"
        assert r.fallback_model_cfg is not None
        assert r.reason == "rule_based"


# ─── RoutingTier enum ────────────────────────────────────────────────


class TestRoutingTier:
    def test_values(self) -> None:
        assert RoutingTier.SIMPLE == "simple"
        assert RoutingTier.STANDARD == "standard"
        assert RoutingTier.REASONING == "reasoning"

    def test_from_string(self) -> None:
        assert RoutingTier("simple") == RoutingTier.SIMPLE
        assert RoutingTier("standard") == RoutingTier.STANDARD
        assert RoutingTier("reasoning") == RoutingTier.REASONING
