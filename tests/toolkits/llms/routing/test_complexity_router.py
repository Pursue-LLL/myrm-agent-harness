"""Tests for task complexity router — all branches covered."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.config import LLMConfig
from myrm_agent_harness.toolkits.llms.routing.complexity_router import (
    DEFAULT_REASONING_KEYWORDS,
    DEFAULT_SIMPLE_INDICATORS,
    DEFAULT_STANDARD_KEYWORDS,
    PenaltyTracker,
    RoutingResult,
    RoutingTier,
    _apply_momentum,
    _cache_get,
    _cache_put,
    _compute_unified_score,
    _dedup_cache,
    _dedup_check,
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
    route_task,
)


def _make_cfg(model: str = "gpt-4o") -> LLMConfig:
    return LLMConfig(model=model, api_key="test-key")


STD_CFG = _make_cfg("gpt-4o")
LIGHT_CFG = _make_cfg("gpt-4o-mini")
REASON_CFG = _make_cfg("o1")
STD_FB = _make_cfg("gpt-4o-fallback")
LIGHT_FB = _make_cfg("gpt-4o-mini-fallback")
REASON_FB = _make_cfg("o1-fallback")


# ── _normalize_query ─────────────────────────────────────────────────────


class TestNormalizeQuery:
    def test_string_input(self):
        text, has_image = _normalize_query("hello world")
        assert text == "hello world"
        assert has_image is False

    def test_multimodal_text_only(self):
        text, has_image = _normalize_query([{"type": "text", "text": "foo"}, {"type": "text", "text": "bar"}])
        assert text == "foo bar"
        assert has_image is False

    def test_multimodal_with_image(self):
        text, has_image = _normalize_query([{"type": "text", "text": "describe"}, {"type": "image_url", "url": "x"}])
        assert text == "describe"
        assert has_image is True

    def test_multimodal_image_type(self):
        _, has_image = _normalize_query([{"type": "image", "data": "x"}])
        assert has_image is True

    def test_empty_list(self):
        text, has_image = _normalize_query([])
        assert text == ""
        assert has_image is False

    def test_non_dict_items_ignored(self):
        text, _has_image = _normalize_query([{"type": "text", "text": "ok"}, "not_a_dict"])
        assert text == "ok"


# ── helper functions ─────────────────────────────────────────────────────


class TestHelpers:
    def test_has_code_content_block(self):
        assert _has_code_content("```python\nprint(1)\n```") is True

    def test_has_code_content_inline(self):
        assert _has_code_content("use `foo()` function") is True

    def test_has_code_content_none(self):
        assert _has_code_content("no code here") is False

    def test_has_keywords(self):
        assert _has_keywords("please optimize this", DEFAULT_STANDARD_KEYWORDS) is True

    def test_has_keywords_chinese(self):
        assert _has_keywords("请重构这个模块", DEFAULT_STANDARD_KEYWORDS) is True

    def test_has_keywords_none(self):
        assert _has_keywords("hello world", DEFAULT_STANDARD_KEYWORDS) is False

    def test_has_math_content_latex(self):
        assert _has_math_content(r"\frac{1}{2}") is True

    def test_has_math_content_block(self):
        assert _has_math_content("$$E=mc^2$$") is True

    def test_has_math_content_bracket(self):
        assert _has_math_content(r"\[x^2 + y^2\]") is True

    def test_has_math_content_none(self):
        assert _has_math_content("no math here") is False

    def test_is_simple_greeting(self):
        assert _is_simple_greeting("hello", DEFAULT_SIMPLE_INDICATORS) is True

    def test_is_simple_greeting_with_punctuation(self):
        assert _is_simple_greeting("你好！", DEFAULT_SIMPLE_INDICATORS) is True

    def test_is_simple_greeting_not(self):
        assert _is_simple_greeting("help me refactor", DEFAULT_SIMPLE_INDICATORS) is False

    def test_word_count_english(self):
        assert _word_count("hello world foo") == 3

    def test_word_count_chinese(self):
        assert _word_count("你好世界") == 4

    def test_word_count_mixed(self):
        assert _word_count("hello 你好 world") == 4


# ── _rule_based_classify ─────────────────────────────────────────────────


class TestRuleBasedClassify:
    def test_image_returns_standard(self):
        result = _rule_based_classify(
            "hi", True, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        assert result == RoutingTier.STANDARD

    def test_simple_greeting(self):
        result = _rule_based_classify(
            "hello", False, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        assert result == RoutingTier.SIMPLE

    def test_math_content(self):
        result = _rule_based_classify(
            r"prove \frac{1}{x}",
            False,
            DEFAULT_STANDARD_KEYWORDS,
            DEFAULT_REASONING_KEYWORDS,
            DEFAULT_SIMPLE_INDICATORS,
        )
        assert result == RoutingTier.REASONING

    def test_reasoning_keyword(self):
        result = _rule_based_classify(
            "prove this theorem",
            False,
            DEFAULT_STANDARD_KEYWORDS,
            DEFAULT_REASONING_KEYWORDS,
            DEFAULT_SIMPLE_INDICATORS,
        )
        assert result == RoutingTier.REASONING

    def test_code_content(self):
        result = _rule_based_classify(
            "fix this ```python\nprint(1)\n```",
            False,
            DEFAULT_STANDARD_KEYWORDS,
            DEFAULT_REASONING_KEYWORDS,
            DEFAULT_SIMPLE_INDICATORS,
        )
        assert result == RoutingTier.STANDARD

    def test_short_no_keywords_simple(self):
        result = _rule_based_classify(
            "weather today", False, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        assert result == RoutingTier.SIMPLE

    def test_standard_keyword(self):
        result = _rule_based_classify(
            "please optimize this code for performance",
            False,
            DEFAULT_STANDARD_KEYWORDS,
            DEFAULT_REASONING_KEYWORDS,
            DEFAULT_SIMPLE_INDICATORS,
        )
        assert result == RoutingTier.STANDARD

    def test_long_text_standard(self):
        long_text = " ".join(["word"] * 60)
        result = _rule_based_classify(
            long_text, False, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        assert result == RoutingTier.STANDARD

    def test_ambiguous_returns_none(self):
        result = _rule_based_classify(
            "can you help me with this task that has moderate complexity",
            False,
            DEFAULT_STANDARD_KEYWORDS,
            DEFAULT_REASONING_KEYWORDS,
            DEFAULT_SIMPLE_INDICATORS,
        )
        assert result is None


# ── _select_model_for_tier ───────────────────────────────────────────────


class TestSelectModelForTier:
    def test_simple_with_light(self):
        cfg, fb = _select_model_for_tier(
            RoutingTier.SIMPLE, STD_CFG, LIGHT_CFG, REASON_CFG, STD_FB, LIGHT_FB, REASON_FB
        )
        assert cfg.model == "gpt-4o-mini"
        assert fb is not None and fb.model == "gpt-4o-mini-fallback"

    def test_simple_without_light_falls_to_standard(self):
        cfg, fb = _select_model_for_tier(RoutingTier.SIMPLE, STD_CFG, None, REASON_CFG, STD_FB, None, REASON_FB)
        assert cfg.model == "gpt-4o"
        assert fb is not None and fb.model == "gpt-4o-fallback"

    def test_reasoning_with_reasoning(self):
        cfg, fb = _select_model_for_tier(
            RoutingTier.REASONING, STD_CFG, LIGHT_CFG, REASON_CFG, STD_FB, LIGHT_FB, REASON_FB
        )
        assert cfg.model == "o1"
        assert fb is not None and fb.model == "o1-fallback"

    def test_reasoning_without_reasoning_falls_to_standard(self):
        cfg, fb = _select_model_for_tier(RoutingTier.REASONING, STD_CFG, LIGHT_CFG, None, STD_FB, LIGHT_FB, None)
        assert cfg.model == "gpt-4o"
        assert fb is not None and fb.model == "gpt-4o-fallback"

    def test_standard(self):
        cfg, fb = _select_model_for_tier(
            RoutingTier.STANDARD, STD_CFG, LIGHT_CFG, REASON_CFG, STD_FB, LIGHT_FB, REASON_FB
        )
        assert cfg.model == "gpt-4o"
        assert fb is not None and fb.model == "gpt-4o-fallback"


# ── cache ────────────────────────────────────────────────────────────────


class TestCache:
    def setup_method(self):
        _judge_cache.clear()

    def test_cache_put_and_get(self):
        _cache_put("abc", RoutingTier.SIMPLE)
        assert _cache_get("abc") == RoutingTier.SIMPLE

    def test_cache_miss(self):
        assert _cache_get("nonexistent") is None

    def test_cache_expired(self):
        _judge_cache["exp"] = ("simple", time.monotonic() - 400)
        assert _cache_get("exp") is None
        assert "exp" not in _judge_cache

    def test_cache_invalid_tier_value(self):
        _judge_cache["bad"] = ("INVALID_TIER", time.monotonic())
        assert _cache_get("bad") is None
        assert "bad" not in _judge_cache

    def test_cache_eviction(self):
        for i in range(260):
            _cache_put(f"key_{i}", RoutingTier.STANDARD)
        assert len(_judge_cache) <= 256

    def test_hash_text_deterministic(self):
        h1 = _hash_text("hello")
        h2 = _hash_text("hello")
        assert h1 == h2
        assert len(h1) == 16


# ── route_task ───────────────────────────────────────────────────────────


class TestRouteTask:
    def setup_method(self):
        _judge_cache.clear()
        _dedup_cache.clear()

    @pytest.mark.asyncio
    async def test_empty_query(self):
        result = await route_task("", STD_CFG)
        assert result.tier == RoutingTier.STANDARD
        assert result.reason == "empty_query"

    @pytest.mark.asyncio
    async def test_whitespace_query(self):
        result = await route_task("   ", STD_CFG)
        assert result.tier == RoutingTier.STANDARD
        assert result.reason == "empty_query"

    @pytest.mark.asyncio
    async def test_rule_based_simple(self):
        result = await route_task("hello", STD_CFG, light_model_cfg=LIGHT_CFG)
        assert result.tier == RoutingTier.SIMPLE
        assert result.reason == "rule_based"
        assert result.model_cfg.model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_rule_based_reasoning(self):
        result = await route_task("prove this theorem", STD_CFG, reasoning_model_cfg=REASON_CFG)
        assert result.tier == RoutingTier.REASONING
        assert result.reason == "rule_based"
        assert result.model_cfg.model == "o1"

    @pytest.mark.asyncio
    async def test_rule_based_standard_code(self):
        result = await route_task("fix this ```python\nprint(1)\n```", STD_CFG)
        assert result.tier == RoutingTier.STANDARD
        assert result.reason == "rule_based"

    @pytest.mark.asyncio
    async def test_default_standard_no_judge(self):
        result = await route_task(
            "help me with this moderate task of some length here please",
            STD_CFG,
        )
        assert result.tier == RoutingTier.STANDARD
        assert result.reason == "default_standard"

    @pytest.mark.asyncio
    async def test_llm_judge_classify(self):
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = '{"tier":"REASONING"}'
        mock_llm.ainvoke.return_value = mock_response

        result = await route_task(
            "help me with this moderate task of some length here please",
            STD_CFG,
            reasoning_model_cfg=REASON_CFG,
            judge_llm=mock_llm,
        )
        assert result.tier == RoutingTier.REASONING
        assert result.reason == "llm_judge"
        assert result.model_cfg.model == "o1"

    @pytest.mark.asyncio
    async def test_llm_judge_cached(self):
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = '{"tier":"SIMPLE"}'
        mock_llm.ainvoke.return_value = mock_response

        query = "help me with this moderate task of some length here please"
        await route_task(query, STD_CFG, light_model_cfg=LIGHT_CFG, judge_llm=mock_llm)

        result = await route_task(query, STD_CFG, light_model_cfg=LIGHT_CFG, judge_llm=mock_llm)
        assert result.reason == "llm_judge_cached"
        assert mock_llm.ainvoke.call_count == 1

    @pytest.mark.asyncio
    async def test_llm_judge_failure_defaults_standard(self):
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = RuntimeError("LLM down")

        result = await route_task(
            "help me with this moderate task of some length here please",
            STD_CFG,
            judge_llm=mock_llm,
        )
        assert result.tier == RoutingTier.STANDARD
        assert result.reason == "llm_judge"

    @pytest.mark.asyncio
    async def test_llm_judge_invalid_response(self):
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "I don't know"
        mock_llm.ainvoke.return_value = mock_response

        result = await route_task(
            "help me with this moderate task of some length here please",
            STD_CFG,
            judge_llm=mock_llm,
        )
        assert result.tier == RoutingTier.STANDARD

    @pytest.mark.asyncio
    async def test_multimodal_image_query(self):
        result = await route_task(
            [{"type": "text", "text": "describe"}, {"type": "image_url", "url": "x"}],
            STD_CFG,
        )
        assert result.tier == RoutingTier.STANDARD
        assert result.reason == "rule_based"

    @pytest.mark.asyncio
    async def test_custom_keywords(self):
        custom_reasoning = frozenset({"custom_keyword"})
        result = await route_task(
            "please apply custom_keyword to solve this complex engineering problem here",
            STD_CFG,
            reasoning_model_cfg=REASON_CFG,
            reasoning_keywords=custom_reasoning,
        )
        assert result.tier == RoutingTier.REASONING

    @pytest.mark.asyncio
    async def test_custom_judge_prompt(self):
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = '{"tier":"SIMPLE"}'
        mock_llm.ainvoke.return_value = mock_response

        result = await route_task(
            "help me with this moderate task of some length here please",
            STD_CFG,
            light_model_cfg=LIGHT_CFG,
            judge_llm=mock_llm,
            judge_system_prompt="Custom prompt",
        )
        assert result.tier == RoutingTier.SIMPLE

    @pytest.mark.asyncio
    async def test_with_all_fallbacks(self):
        result = await route_task(
            "hello",
            STD_CFG,
            light_model_cfg=LIGHT_CFG,
            reasoning_model_cfg=REASON_CFG,
            standard_fallback_cfg=STD_FB,
            light_fallback_cfg=LIGHT_FB,
            reasoning_fallback_cfg=REASON_FB,
        )
        assert result.tier == RoutingTier.SIMPLE
        assert result.model_cfg.model == "gpt-4o-mini"
        assert result.fallback_model_cfg is not None
        assert result.fallback_model_cfg.model == "gpt-4o-mini-fallback"


# ── RoutingResult / RoutingTier ──────────────────────────────────────────


class TestDataTypes:
    def test_routing_tier_values(self):
        assert RoutingTier.SIMPLE == "simple"
        assert RoutingTier.STANDARD == "standard"
        assert RoutingTier.REASONING == "reasoning"

    def test_routing_result_frozen(self):
        result = RoutingResult(tier=RoutingTier.SIMPLE, model_cfg=STD_CFG, fallback_model_cfg=None, reason="test")
        assert result.tier == RoutingTier.SIMPLE
        assert result.reason == "test"


# ── _apply_momentum ──────────────────────────────────────────────────────


class TestApplyMomentum:
    def test_no_recent_tiers_no_override(self):
        tier, overridden = _apply_momentum(RoutingTier.SIMPLE, "继续", None)
        assert tier == RoutingTier.SIMPLE
        assert overridden is False

    def test_empty_recent_tiers_no_override(self):
        tier, overridden = _apply_momentum(RoutingTier.SIMPLE, "继续", [])
        assert tier == RoutingTier.SIMPLE
        assert overridden is False

    def test_non_simple_tier_promoted_by_reasoning_history(self):
        # Short message with REASONING history → weighted momentum promotes STANDARD to REASONING
        tier, overridden = _apply_momentum(
            RoutingTier.STANDARD, "继续", [RoutingTier.REASONING, RoutingTier.REASONING]
        )
        assert tier == RoutingTier.REASONING
        assert overridden is True

    def test_long_text_no_override(self):
        long_msg = "这是一段比较长的消息内容，超过三十个字符的限制所以不应该被Momentum影响到最终的路由结果"
        assert len(long_msg) > 30
        tier, overridden = _apply_momentum(
            RoutingTier.SIMPLE, long_msg, [RoutingTier.STANDARD, RoutingTier.STANDARD]
        )
        assert tier == RoutingTier.SIMPLE
        assert overridden is False

    def test_short_msg_standard_median_overrides(self):
        tier, overridden = _apply_momentum(
            RoutingTier.SIMPLE,
            "继续",
            [RoutingTier.STANDARD, RoutingTier.STANDARD, RoutingTier.STANDARD],
        )
        assert tier == RoutingTier.STANDARD
        assert overridden is True

    def test_short_msg_reasoning_weighted_overrides(self):
        tier, overridden = _apply_momentum(
            RoutingTier.SIMPLE,
            "好的",
            [RoutingTier.REASONING, RoutingTier.REASONING, RoutingTier.REASONING],
        )
        assert tier == RoutingTier.REASONING
        assert overridden is True

    def test_short_msg_all_simple_no_override(self):
        tier, overridden = _apply_momentum(
            RoutingTier.SIMPLE,
            "ok",
            [RoutingTier.SIMPLE, RoutingTier.SIMPLE, RoutingTier.SIMPLE],
        )
        assert tier == RoutingTier.SIMPLE
        assert overridden is False

    def test_mixed_tiers_median_standard(self):
        tier, overridden = _apply_momentum(
            RoutingTier.SIMPLE,
            "对",
            [RoutingTier.SIMPLE, RoutingTier.STANDARD, RoutingTier.REASONING],
        )
        assert tier == RoutingTier.STANDARD
        assert overridden is True


class TestRouteTaskMomentum:
    def setup_method(self):
        _judge_cache.clear()
        _dedup_cache.clear()

    @pytest.mark.asyncio
    async def test_momentum_overrides_simple_short_msg(self):
        result = await route_task(
            "继续",
            STD_CFG,
            light_model_cfg=LIGHT_CFG,
            recent_tiers=[RoutingTier.STANDARD, RoutingTier.STANDARD, RoutingTier.STANDARD],
        )
        assert result.tier == RoutingTier.STANDARD
        assert result.reason == "momentum_override"
        assert result.model_cfg.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_no_momentum_when_no_recent_tiers(self):
        result = await route_task("继续", STD_CFG, light_model_cfg=LIGHT_CFG)
        assert result.tier == RoutingTier.SIMPLE
        assert result.reason == "rule_based"

    @pytest.mark.asyncio
    async def test_momentum_does_not_affect_non_simple(self):
        result = await route_task(
            "prove this theorem",
            STD_CFG,
            reasoning_model_cfg=REASON_CFG,
            recent_tiers=[RoutingTier.SIMPLE, RoutingTier.SIMPLE],
        )
        assert result.tier == RoutingTier.REASONING
        assert result.reason == "rule_based"


# ── MR-14: PenaltyTracker ──────────────────────────────────────────────


class TestPenaltyTracker:
    def test_penalty_tracker_basic(self):
        tracker = PenaltyTracker()
        assert tracker.get_penalty(RoutingTier.STANDARD) == 0.0

        tracker.record_misroute(RoutingTier.STANDARD)
        penalty = tracker.get_penalty(RoutingTier.STANDARD)
        assert penalty == 0.75  # PENALTY_PER_FLAG

    def test_penalty_tracker_cap(self):
        tracker = PenaltyTracker()
        for _ in range(10):
            tracker.record_misroute(RoutingTier.SIMPLE)
        penalty = tracker.get_penalty(RoutingTier.SIMPLE)
        assert penalty == 3.0  # PENALTY_CAP

    def test_penalty_tracker_per_tier(self):
        tracker = PenaltyTracker()
        tracker.record_misroute(RoutingTier.STANDARD)
        tracker.record_misroute(RoutingTier.REASONING)

        assert tracker.get_penalty(RoutingTier.STANDARD) == 0.75
        assert tracker.get_penalty(RoutingTier.REASONING) == 0.75
        assert tracker.get_penalty(RoutingTier.SIMPLE) == 0.0

    def test_penalty_tracker_apply_penalties(self):
        tracker = PenaltyTracker()
        tracker.record_misroute(RoutingTier.STANDARD)
        tracker.record_misroute(RoutingTier.STANDARD)

        scores = {RoutingTier.SIMPLE: 0.0, RoutingTier.STANDARD: 3.0, RoutingTier.REASONING: 0.0}
        adjusted = tracker.apply_penalties(scores)
        assert adjusted[RoutingTier.STANDARD] == 1.5  # 3.0 - 1.5

    def test_penalty_tracker_cleanup(self):
        tracker = PenaltyTracker(DECAY_HALF_LIFE_S=0.001)
        tracker.record_misroute(RoutingTier.STANDARD)
        time.sleep(0.01)
        removed = tracker.cleanup_expired()
        assert removed >= 1
        assert tracker.get_penalty(RoutingTier.STANDARD) == 0.0


# ── MR-15/MR-16: Unified Scoring ───────────────────────────────────────


class TestUnifiedScoring:
    def test_compute_unified_score_simple_greeting(self):
        scores = _compute_unified_score(
            "hello", False, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        assert scores[RoutingTier.SIMPLE] > scores[RoutingTier.STANDARD]
        assert scores[RoutingTier.SIMPLE] > scores[RoutingTier.REASONING]

    def test_compute_unified_score_reasoning_keyword(self):
        scores = _compute_unified_score(
            "prove this theorem", False, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        assert scores[RoutingTier.REASONING] > scores[RoutingTier.SIMPLE]

    def test_compute_unified_score_standard_keyword(self):
        scores = _compute_unified_score(
            "optimize this code", False, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        assert scores[RoutingTier.STANDARD] > scores[RoutingTier.SIMPLE]

    def test_compute_unified_score_code_content(self):
        scores = _compute_unified_score(
            "fix ```python\nprint(1)\n```", False, DEFAULT_STANDARD_KEYWORDS, DEFAULT_REASONING_KEYWORDS, DEFAULT_SIMPLE_INDICATORS
        )
        assert scores[RoutingTier.STANDARD] > 0

    def test_structural_signals_urls(self):
        signals = _score_structural_signals("visit https://example.com for details")
        assert "urls" in signals
        assert signals["urls"] > 0

    def test_structural_signals_file_paths(self):
        signals = _score_structural_signals("edit /home/user/project/main.py")
        assert "file_paths" in signals

    def test_contextual_signals_image(self):
        signals = _score_contextual_signals("describe this", True, 2)
        assert "image_input" in signals

    def test_contextual_signals_long_input(self):
        text = " ".join(["word"] * 80)
        signals = _score_contextual_signals(text, False, 80)
        assert "long_input" in signals

    def test_contextual_signals_repetition(self):
        signals = _score_contextual_signals("give me 5 variations of this", False, 7)
        assert "repetition_request" in signals


# ── MR-17: Weighted Momentum ───────────────────────────────────────────


class TestWeightedMomentum:
    def test_weighted_momentum_no_history(self):
        tier, overridden = _apply_momentum(RoutingTier.SIMPLE, "ok", None)
        assert tier == RoutingTier.SIMPLE
        assert overridden is False

    def test_weighted_momentum_promotes_simple(self):
        # Recent tiers all STANDARD → history_avg = 0.0 → effective > -0.1 → STANDARD
        tier, overridden = _apply_momentum(
            RoutingTier.SIMPLE, "ok", [RoutingTier.STANDARD, RoutingTier.STANDARD, RoutingTier.STANDARD]
        )
        assert tier == RoutingTier.STANDARD
        assert overridden is True

    def test_weighted_momentum_preserves_reasoning(self):
        # Recent tiers all REASONING → history_avg = 0.4 → effective > 0.1 → REASONING
        tier, overridden = _apply_momentum(
            RoutingTier.SIMPLE, "好的", [RoutingTier.REASONING, RoutingTier.REASONING, RoutingTier.REASONING]
        )
        assert tier == RoutingTier.REASONING
        assert overridden is True

    def test_weighted_momentum_long_message_no_effect(self):
        long_msg = "这是一段比较长的消息内容，超过一百个字符的限制所以不应该被Momentum影响到最终的路由结果，需要确保消息足够长才能触发这个测试用例中的逻辑判断，再加上一些额外的文字来确保长度绝对足够超过一百个字符的阈值限制"
        assert len(long_msg) > 100
        tier, overridden = _apply_momentum(
            RoutingTier.SIMPLE, long_msg, [RoutingTier.STANDARD, RoutingTier.STANDARD]
        )
        assert tier == RoutingTier.SIMPLE
        assert overridden is False

    def test_weighted_momentum_mixed_tiers(self):
        tier, overridden = _apply_momentum(
            RoutingTier.SIMPLE, "对", [RoutingTier.SIMPLE, RoutingTier.STANDARD, RoutingTier.REASONING]
        )
        # history_avg = (-0.2 + 0.0 + 0.4) / 3 = 0.067 → STANDARD
        assert tier == RoutingTier.STANDARD
        assert overridden is True


# ── MR-18: Content Dedup ───────────────────────────────────────────────


class TestContentDedup:
    def setup_method(self):
        _dedup_cache.clear()
        _judge_cache.clear()

    @pytest.mark.asyncio
    async def test_content_dedup_returns_cached(self):
        result1 = await route_task("hello", STD_CFG, light_model_cfg=LIGHT_CFG)
        assert result1.reason == "rule_based"

        result2 = await route_task("hello", STD_CFG, light_model_cfg=LIGHT_CFG)
        assert result2.reason == "content_dedup"
        assert result2.tier == result1.tier

    @pytest.mark.asyncio
    async def test_content_dedup_different_queries(self):
        result1 = await route_task("hello", STD_CFG, light_model_cfg=LIGHT_CFG)
        result2 = await route_task("prove this theorem", STD_CFG, reasoning_model_cfg=REASON_CFG)
        assert result1.reason == "rule_based"
        assert result2.reason == "rule_based"
        assert result1.tier != result2.tier

    def test_dedup_check_miss(self):
        assert _dedup_check("nonexistent") is None
