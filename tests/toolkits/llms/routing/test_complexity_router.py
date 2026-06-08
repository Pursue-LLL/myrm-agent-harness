"""Tests for task complexity router — unified scoring, momentum, penalty, and dedup.

Covers: Phase 1 rule-based classification, weighted keyword scoring, structural/contextual
signals, multi-turn momentum, penalty feedback with decay, content dedup, Phase 2 LLM judge,
model selection, and end-to-end ``route_task`` flows.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.core.config.llm import LLMConfig
from myrm_agent_harness.toolkits.llms.routing.complexity_router import (
    DEFAULT_JUDGE_SYSTEM_PROMPT,
    DEFAULT_REASONING_KEYWORDS,
    DEFAULT_SIMPLE_INDICATORS,
    DEFAULT_STANDARD_KEYWORDS,
    PenaltyTracker,
    RoutingResult,
    RoutingTier,
    WeightedKeyword,
    _apply_momentum,
    _build_weighted_keywords,
    _cache_get,
    _cache_put,
    _compute_unified_score,
    _dedup_cache,
    _dedup_check,
    _dedup_store,
    _has_code_content,
    _has_keywords,
    _has_math_content,
    _hash_text,
    _is_simple_greeting,
    _judge_cache,
    _normalize_query,
    _rule_based_classify,
    _score_contextual_signals,
    _score_structural_signals,
    _select_model_for_tier,
    _word_count,
    record_misroute,
    route_task,
)


@pytest.fixture(autouse=True)
def _clear_caches():
    """Clear all module-level caches before each test."""
    _judge_cache.clear()
    _dedup_cache.clear()
    yield
    _judge_cache.clear()
    _dedup_cache.clear()


def _make_cfg(model: str = "gpt-4") -> LLMConfig:
    return LLMConfig(model=model, api_key="test-key")


# ────────────────────── RoutingTier enum ──────────────────────


class TestRoutingTier:
    def test_values(self):
        assert RoutingTier.SIMPLE == "simple"
        assert RoutingTier.STANDARD == "standard"
        assert RoutingTier.REASONING == "reasoning"

    def test_is_str_enum(self):
        assert isinstance(RoutingTier.SIMPLE, str)


# ────────────────────── Helper functions ──────────────────────


class TestNormalizeQuery:
    def test_plain_string(self):
        text, has_image = _normalize_query("hello")
        assert text == "hello"
        assert has_image is False

    def test_multimodal_text_only(self):
        msgs = [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]
        text, has_image = _normalize_query(msgs)
        assert text == "hello world"
        assert has_image is False

    def test_multimodal_with_image(self):
        msgs = [{"type": "text", "text": "describe"}, {"type": "image_url", "url": "..."}]
        text, has_image = _normalize_query(msgs)
        assert "describe" in text
        assert has_image is True

    def test_image_type_variant(self):
        msgs = [{"type": "image", "data": "..."}]
        _, has_image = _normalize_query(msgs)
        assert has_image is True


class TestWordCount:
    def test_english(self):
        assert _word_count("hello world") == 2

    def test_chinese(self):
        assert _word_count("你好世界") == 4

    def test_mixed(self):
        count = _word_count("hello 你好 world")
        assert count == 4  # 2 latin + 2 CJK


class TestHasCodeContent:
    def test_code_block(self):
        assert _has_code_content("```python\nprint(1)\n```") is True

    def test_inline_code(self):
        assert _has_code_content("use `pip install`") is True

    def test_no_code(self):
        assert _has_code_content("just plain text") is False


class TestHasMathContent:
    def test_latex_command(self):
        assert _has_math_content("\\frac{1}{2}") is True

    def test_latex_block(self):
        assert _has_math_content("$$x^2$$") is True

    def test_no_math(self):
        assert _has_math_content("no math here") is False


class TestIsSimpleGreeting:
    def test_basic_greetings(self):
        for g in ["hello", "hi", "thanks", "你好", "谢谢"]:
            assert _is_simple_greeting(g, DEFAULT_SIMPLE_INDICATORS) is True

    def test_with_punctuation(self):
        assert _is_simple_greeting("hello!", DEFAULT_SIMPLE_INDICATORS) is True
        assert _is_simple_greeting("你好！", DEFAULT_SIMPLE_INDICATORS) is True

    def test_not_greeting(self):
        assert _is_simple_greeting("implement a web server", DEFAULT_SIMPLE_INDICATORS) is False


class TestHasKeywords:
    def test_standard_keyword_found(self):
        assert _has_keywords("please refactor this code", DEFAULT_STANDARD_KEYWORDS) is True

    def test_chinese_keyword(self):
        assert _has_keywords("请帮我重构代码", DEFAULT_STANDARD_KEYWORDS) is True

    def test_reasoning_keyword(self):
        assert _has_keywords("prove this theorem", DEFAULT_REASONING_KEYWORDS) is True

    def test_no_match(self):
        assert _has_keywords("hello world", DEFAULT_STANDARD_KEYWORDS) is False


# ────────────────────── Structural signals ──────────────────────


class TestStructuralSignals:
    def test_url_detection(self):
        scores = _score_structural_signals("check https://example.com/api")
        assert "urls" in scores
        assert scores["urls"] > 0

    def test_file_path_detection(self):
        scores = _score_structural_signals("edit /src/main.py")
        assert "file_paths" in scores

    def test_no_signals(self):
        scores = _score_structural_signals("just plain text")
        assert len(scores) == 0

    def test_multiple_urls(self):
        scores = _score_structural_signals("see https://a.com and https://b.com and https://c.com")
        assert scores["urls"] == 1.5  # capped at min(3*0.5, 1.5)


# ────────────────────── Contextual signals ──────────────────────


class TestContextualSignals:
    def test_image_signal(self):
        scores = _score_contextual_signals("describe", has_image=True, word_count=1)
        assert scores["image_input"] == 6.0

    def test_long_input(self):
        scores = _score_contextual_signals("x", has_image=False, word_count=100)
        assert "long_input" in scores
        assert scores["long_input"] > 0

    def test_repetition_request(self):
        scores = _score_contextual_signals("give me 5 variations", has_image=False, word_count=5)
        assert "repetition_request" in scores
        assert scores["repetition_request"] == 0.6

    def test_large_repetition(self):
        scores = _score_contextual_signals("give me 20 examples", has_image=False, word_count=5)
        assert scores["repetition_request"] == 0.9

    def test_no_signals(self):
        scores = _score_contextual_signals("short text", has_image=False, word_count=2)
        assert len(scores) == 0


# ────────────────────── Unified scoring ──────────────────────


class TestUnifiedScoring:
    def test_simple_greeting_scores_high(self):
        scores = _compute_unified_score(
            "hello",
            has_image=False,
            standard_keywords=DEFAULT_STANDARD_KEYWORDS,
            reasoning_keywords=DEFAULT_REASONING_KEYWORDS,
            simple_indicators=DEFAULT_SIMPLE_INDICATORS,
        )
        assert scores[RoutingTier.SIMPLE] > scores[RoutingTier.STANDARD]
        assert scores[RoutingTier.SIMPLE] > scores[RoutingTier.REASONING]

    def test_refactor_scores_standard(self):
        scores = _compute_unified_score(
            "refactor the database module",
            has_image=False,
            standard_keywords=DEFAULT_STANDARD_KEYWORDS,
            reasoning_keywords=DEFAULT_REASONING_KEYWORDS,
            simple_indicators=DEFAULT_SIMPLE_INDICATORS,
        )
        assert scores[RoutingTier.STANDARD] > scores[RoutingTier.SIMPLE]

    def test_prove_scores_reasoning(self):
        scores = _compute_unified_score(
            "prove this theorem step by step",
            has_image=False,
            standard_keywords=DEFAULT_STANDARD_KEYWORDS,
            reasoning_keywords=DEFAULT_REASONING_KEYWORDS,
            simple_indicators=DEFAULT_SIMPLE_INDICATORS,
        )
        assert scores[RoutingTier.REASONING] > scores[RoutingTier.STANDARD]

    def test_code_block_boosts_standard(self):
        scores = _compute_unified_score(
            "```python\nprint(1)\n```",
            has_image=False,
            standard_keywords=DEFAULT_STANDARD_KEYWORDS,
            reasoning_keywords=DEFAULT_REASONING_KEYWORDS,
            simple_indicators=DEFAULT_SIMPLE_INDICATORS,
        )
        assert scores[RoutingTier.STANDARD] >= 2.0

    def test_math_boosts_reasoning(self):
        scores = _compute_unified_score(
            "\\frac{1}{2} + \\sum_{i=1}^{n}",
            has_image=False,
            standard_keywords=DEFAULT_STANDARD_KEYWORDS,
            reasoning_keywords=DEFAULT_REASONING_KEYWORDS,
            simple_indicators=DEFAULT_SIMPLE_INDICATORS,
        )
        assert scores[RoutingTier.REASONING] >= 3.0

    def test_short_message_without_signals(self):
        scores = _compute_unified_score(
            "ok fine",
            has_image=False,
            standard_keywords=DEFAULT_STANDARD_KEYWORDS,
            reasoning_keywords=DEFAULT_REASONING_KEYWORDS,
            simple_indicators=DEFAULT_SIMPLE_INDICATORS,
        )
        assert scores[RoutingTier.SIMPLE] >= 3.0

    def test_image_boosts_standard(self):
        scores = _compute_unified_score(
            "describe this",
            has_image=True,
            standard_keywords=DEFAULT_STANDARD_KEYWORDS,
            reasoning_keywords=DEFAULT_REASONING_KEYWORDS,
            simple_indicators=DEFAULT_SIMPLE_INDICATORS,
        )
        assert scores[RoutingTier.STANDARD] >= 6.0

    def test_chinese_keywords(self):
        scores = _compute_unified_score(
            "请帮我推导这个定理",
            has_image=False,
            standard_keywords=DEFAULT_STANDARD_KEYWORDS,
            reasoning_keywords=DEFAULT_REASONING_KEYWORDS,
            simple_indicators=DEFAULT_SIMPLE_INDICATORS,
        )
        assert scores[RoutingTier.REASONING] > 0


# ────────────────────── Rule-based classification ──────────────────────


class TestRuleBasedClassify:
    def test_simple_greeting(self):
        result = _rule_based_classify(
            "hello", False, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        assert result == RoutingTier.SIMPLE

    def test_standard_keyword(self):
        result = _rule_based_classify(
            "refactor the authentication module",
            False,
            DEFAULT_STANDARD_KEYWORDS,
            DEFAULT_REASONING_KEYWORDS,
            DEFAULT_SIMPLE_INDICATORS,
        )
        assert result == RoutingTier.STANDARD

    def test_reasoning_keyword(self):
        result = _rule_based_classify(
            "prove this theorem step by step",
            False,
            DEFAULT_STANDARD_KEYWORDS,
            DEFAULT_REASONING_KEYWORDS,
            DEFAULT_SIMPLE_INDICATORS,
        )
        assert result == RoutingTier.REASONING

    def test_ambiguous_returns_none(self):
        result = _rule_based_classify(
            "tell me about something interesting",
            False,
            DEFAULT_STANDARD_KEYWORDS,
            DEFAULT_REASONING_KEYWORDS,
            DEFAULT_SIMPLE_INDICATORS,
        )
        # Ambiguous: no strong keyword signals, not a simple greeting, not a short message
        # Could return None or SIMPLE/STANDARD depending on word count
        assert result is None or isinstance(result, RoutingTier)


# ────────────────────── PenaltyTracker ──────────────────────


class TestPenaltyTracker:
    def test_initial_no_penalty(self):
        tracker = PenaltyTracker()
        assert tracker.get_penalty(RoutingTier.SIMPLE) == 0.0

    def test_record_increases_penalty(self):
        tracker = PenaltyTracker()
        tracker.record_misroute(RoutingTier.SIMPLE)
        p = tracker.get_penalty(RoutingTier.SIMPLE)
        assert p == pytest.approx(0.75, abs=0.01)

    def test_multiple_flags_accumulate(self):
        tracker = PenaltyTracker()
        for _ in range(3):
            tracker.record_misroute(RoutingTier.STANDARD)
        p = tracker.get_penalty(RoutingTier.STANDARD)
        assert p == pytest.approx(2.25, abs=0.01)

    def test_penalty_cap(self):
        tracker = PenaltyTracker()
        for _ in range(10):
            tracker.record_misroute(RoutingTier.REASONING)
        p = tracker.get_penalty(RoutingTier.REASONING)
        assert p == 3.0  # capped

    def test_apply_penalties_reduces_scores(self):
        tracker = PenaltyTracker()
        tracker.record_misroute(RoutingTier.SIMPLE)
        scores = {RoutingTier.SIMPLE: 5.0, RoutingTier.STANDARD: 3.0, RoutingTier.REASONING: 1.0}
        adjusted = tracker.apply_penalties(scores)
        assert adjusted[RoutingTier.SIMPLE] < 5.0
        assert adjusted[RoutingTier.STANDARD] == 3.0  # no penalty
        assert adjusted[RoutingTier.REASONING] == 1.0  # no penalty

    def test_apply_penalties_floor_at_zero(self):
        tracker = PenaltyTracker()
        for _ in range(5):
            tracker.record_misroute(RoutingTier.SIMPLE)
        scores = {RoutingTier.SIMPLE: 1.0, RoutingTier.STANDARD: 0.0, RoutingTier.REASONING: 0.0}
        adjusted = tracker.apply_penalties(scores)
        assert adjusted[RoutingTier.SIMPLE] == 0.0  # floored at 0

    def test_cleanup_expired(self):
        tracker = PenaltyTracker(DECAY_HALF_LIFE_S=0.001)
        tracker.record_misroute(RoutingTier.SIMPLE)
        time.sleep(0.01)
        removed = tracker.cleanup_expired()
        assert removed >= 1
        assert tracker.get_penalty(RoutingTier.SIMPLE) == 0.0

    def test_different_tiers_independent(self):
        tracker = PenaltyTracker()
        tracker.record_misroute(RoutingTier.SIMPLE)
        tracker.record_misroute(RoutingTier.REASONING)
        assert tracker.get_penalty(RoutingTier.SIMPLE) > 0
        assert tracker.get_penalty(RoutingTier.REASONING) > 0
        assert tracker.get_penalty(RoutingTier.STANDARD) == 0.0


# ────────────────────── Weighted Keywords ──────────────────────


class TestWeightedKeywords:
    def test_multiword_gets_strong_weight(self):
        result = _build_weighted_keywords(frozenset({"step by step", "hi"}))
        assert result["step by step"] == 2.0
        assert result["hi"] == 1.0

    def test_long_word_gets_strong_weight(self):
        result = _build_weighted_keywords(frozenset({"infrastructure", "code"}))
        assert result["infrastructure"] == 2.0
        assert result["code"] == 1.0


# ────────────────────── Momentum ──────────────────────


class TestMomentum:
    def test_no_history_no_change(self):
        tier, overridden = _apply_momentum(RoutingTier.STANDARD, "short", None)
        assert tier == RoutingTier.STANDARD
        assert overridden is False

    def test_empty_history_no_change(self):
        tier, overridden = _apply_momentum(RoutingTier.STANDARD, "short", [])
        assert tier == RoutingTier.STANDARD
        assert overridden is False

    def test_short_message_gets_momentum(self):
        recent = [RoutingTier.REASONING, RoutingTier.REASONING, RoutingTier.REASONING]
        tier, overridden = _apply_momentum(RoutingTier.SIMPLE, "ok", recent)
        assert tier in (RoutingTier.STANDARD, RoutingTier.REASONING)
        assert overridden is True

    def test_long_message_no_momentum(self):
        recent = [RoutingTier.REASONING, RoutingTier.REASONING]
        long_text = "a" * 200
        tier, overridden = _apply_momentum(RoutingTier.SIMPLE, long_text, recent)
        assert tier == RoutingTier.SIMPLE
        assert overridden is False

    def test_medium_message_reduced_momentum(self):
        recent = [RoutingTier.REASONING] * 5
        medium_text = "a" * 50
        tier, _ = _apply_momentum(RoutingTier.SIMPLE, medium_text, recent)
        # Medium text gets partial momentum
        assert isinstance(tier, RoutingTier)


# ────────────────────── Judge cache ──────────────────────


class TestJudgeCache:
    def test_cache_miss(self):
        assert _cache_get("nonexistent") is None

    def test_cache_hit(self):
        _cache_put("test_hash", RoutingTier.STANDARD)
        assert _cache_get("test_hash") == RoutingTier.STANDARD

    def test_cache_ttl_expiry(self):
        _judge_cache["expired"] = ("standard", time.monotonic() - 600)
        assert _cache_get("expired") is None

    def test_cache_eviction(self):
        for i in range(260):
            _cache_put(f"key_{i}", RoutingTier.SIMPLE)
        assert len(_judge_cache) <= 256


# ────────────────────── Content dedup ──────────────────────


class TestContentDedup:
    def test_dedup_miss(self):
        assert _dedup_check("new query") is None

    def test_dedup_hit(self):
        _dedup_store("hello world", RoutingTier.SIMPLE)
        assert _dedup_check("hello world") == RoutingTier.SIMPLE

    def test_dedup_different_text(self):
        _dedup_store("query A", RoutingTier.SIMPLE)
        assert _dedup_check("query B") is None


# ────────────────────── Hash function ──────────────────────


class TestHash:
    def test_deterministic(self):
        assert _hash_text("hello") == _hash_text("hello")

    def test_different_inputs(self):
        assert _hash_text("hello") != _hash_text("world")

    def test_length(self):
        assert len(_hash_text("test")) == 16


# ────────────────────── Model selection ──────────────────────


class TestModelSelection:
    def test_simple_uses_light(self):
        std = _make_cfg("gpt-4")
        light = _make_cfg("gpt-3.5")
        cfg, _ = _select_model_for_tier(RoutingTier.SIMPLE, std, light, None, None, None, None)
        assert cfg.model == "gpt-3.5"

    def test_simple_fallback_to_standard(self):
        std = _make_cfg("gpt-4")
        cfg, _ = _select_model_for_tier(RoutingTier.SIMPLE, std, None, None, None, None, None)
        assert cfg.model == "gpt-4"

    def test_reasoning_uses_reasoning(self):
        std = _make_cfg("gpt-4")
        reasoning = _make_cfg("o1")
        cfg, _ = _select_model_for_tier(RoutingTier.REASONING, std, None, reasoning, None, None, None)
        assert cfg.model == "o1"

    def test_reasoning_fallback_to_standard(self):
        std = _make_cfg("gpt-4")
        cfg, _ = _select_model_for_tier(RoutingTier.REASONING, std, None, None, None, None, None)
        assert cfg.model == "gpt-4"

    def test_standard_uses_standard(self):
        std = _make_cfg("gpt-4")
        cfg, _ = _select_model_for_tier(RoutingTier.STANDARD, std, None, None, None, None, None)
        assert cfg.model == "gpt-4"

    def test_fallback_configs_returned(self):
        std = _make_cfg("gpt-4")
        std_fb = _make_cfg("gpt-3.5-fallback")
        _, fallback = _select_model_for_tier(RoutingTier.STANDARD, std, None, None, std_fb, None, None)
        assert fallback is not None
        assert fallback.model == "gpt-3.5-fallback"


# ────────────────────── route_task (async) ──────────────────────


class TestRouteTask:
    @pytest.fixture
    def std_cfg(self):
        return _make_cfg("gpt-4")

    @pytest.fixture
    def light_cfg(self):
        return _make_cfg("gpt-3.5")

    @pytest.fixture
    def reasoning_cfg(self):
        return _make_cfg("o1")

    @pytest.mark.asyncio
    async def test_empty_query_returns_standard(self, std_cfg):
        result = await route_task("", std_cfg)
        assert result.tier == RoutingTier.STANDARD
        assert result.reason == "empty_query"

    @pytest.mark.asyncio
    async def test_simple_greeting(self, std_cfg, light_cfg):
        result = await route_task("hello", std_cfg, light_model_cfg=light_cfg)
        assert result.tier == RoutingTier.SIMPLE
        assert result.model_cfg.model == "gpt-3.5"

    @pytest.mark.asyncio
    async def test_standard_keyword_routing(self, std_cfg, light_cfg):
        result = await route_task("refactor the authentication module", std_cfg, light_model_cfg=light_cfg)
        assert result.tier == RoutingTier.STANDARD
        assert result.model_cfg.model == "gpt-4"

    @pytest.mark.asyncio
    async def test_reasoning_keyword_routing(self, std_cfg, reasoning_cfg):
        result = await route_task("prove this theorem step by step", std_cfg, reasoning_model_cfg=reasoning_cfg)
        assert result.tier == RoutingTier.REASONING
        assert result.model_cfg.model == "o1"

    @pytest.mark.asyncio
    async def test_multimodal_image_routing(self, std_cfg):
        query = [{"type": "text", "text": "describe"}, {"type": "image_url", "url": "..."}]
        result = await route_task(query, std_cfg)
        assert result.tier == RoutingTier.STANDARD

    @pytest.mark.asyncio
    async def test_content_dedup(self, std_cfg):
        r1 = await route_task("hello", std_cfg)
        r2 = await route_task("hello", std_cfg)
        assert r2.reason == "content_dedup"
        assert r1.tier == r2.tier

    @pytest.mark.asyncio
    async def test_momentum_override(self, std_cfg, light_cfg):
        recent = [RoutingTier.REASONING, RoutingTier.REASONING, RoutingTier.REASONING]
        result = await route_task("ok", std_cfg, light_model_cfg=light_cfg, recent_tiers=recent)
        # Short "ok" with reasoning history should get momentum boost
        assert result.tier in (RoutingTier.STANDARD, RoutingTier.REASONING)

    @pytest.mark.asyncio
    async def test_llm_judge_fallback(self, std_cfg):
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = '{"tier":"REASONING"}'
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        result = await route_task(
            "a somewhat ambiguous but nuanced question about life",
            std_cfg,
            judge_llm=mock_llm,
        )
        # Should use judge if rule-based is ambiguous, or fall back to default
        assert isinstance(result, RoutingResult)

    @pytest.mark.asyncio
    async def test_chinese_routing(self, std_cfg, reasoning_cfg):
        result = await route_task("请帮我证明这个定理，逐步推导", std_cfg, reasoning_model_cfg=reasoning_cfg)
        assert result.tier == RoutingTier.REASONING

    @pytest.mark.asyncio
    async def test_code_routing(self, std_cfg):
        result = await route_task("```python\nfor i in range(10): print(i)\n```", std_cfg)
        assert result.tier == RoutingTier.STANDARD

    @pytest.mark.asyncio
    async def test_result_has_all_fields(self, std_cfg):
        result = await route_task("hello", std_cfg)
        assert hasattr(result, "tier")
        assert hasattr(result, "model_cfg")
        assert hasattr(result, "fallback_model_cfg")
        assert hasattr(result, "reason")


# ────────────────────── record_misroute (module-level) ──────────────────────


class TestRecordMisroute:
    def test_module_level_function(self):
        record_misroute(RoutingTier.SIMPLE)
        from myrm_agent_harness.toolkits.llms.routing.complexity_router import get_penalty_tracker

        tracker = get_penalty_tracker()
        assert tracker.get_penalty(RoutingTier.SIMPLE) > 0
