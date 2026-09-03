"""Unit tests for Task Specialty Router (myrm_agent_harness.toolkits.llms.routing.specialty_router).

Covers:
- Query normalization and multimodal detection
- 6-tier classification (CODE, LONG_DOC, REASONING, MULTIMODAL, CASUAL, GENERAL)
- Multi-turn session momentum for technical tasks
- Four-tier fallback chain construction and deduplication
- End-to-end route_task_specialty execution and smooth degradation
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.config.llm import LLMConfig
from myrm_agent_harness.toolkits.llms.routing.specialty_router import (
    LONG_DOC_CHAR_THRESHOLD,
    TaskSpecialty,
    _build_fallback_chain,
    _normalize_specialty_query,
    classify_task_specialty,
    route_task_specialty,
)

_TEST_KEY = "sk-test-key-12345678"


def _make_cfg(model: str, base_url: str | None = None) -> LLMConfig:
    return LLMConfig(model=model, api_key=_TEST_KEY, api_base=base_url)


class TestNormalizeSpecialtyQuery:
    def test_plain_string(self) -> None:
        text, has_media = _normalize_specialty_query("Hello world")
        assert text == "Hello world"
        assert has_media is False

    def test_multimodal_with_text_and_image(self) -> None:
        query: list[dict[str, object]] = [
            {"type": "text", "text": "Analyze this chart"},
            {"type": "image_url", "image_url": {"url": "https://example.com/chart.png"}},
        ]
        text, has_media = _normalize_specialty_query(query)
        assert text == "Analyze this chart"
        assert has_media is True

    def test_multimodal_with_video(self) -> None:
        query: list[dict[str, object]] = [
            {"type": "text", "text": "What happened in the video?"},
            {"type": "video_url", "video_url": {"url": "https://example.com/vid.mp4"}},
        ]
        text, has_media = _normalize_specialty_query(query)
        assert text == "What happened in the video?"
        assert has_media is True

    def test_multimodal_text_only(self) -> None:
        query: list[dict[str, object]] = [
            {"type": "text", "text": "Part 1"},
            {"type": "text", "text": "Part 2"},
        ]
        text, has_media = _normalize_specialty_query(query)
        assert text == "Part 1 Part 2"
        assert has_media is False


class TestClassifyTaskSpecialty:
    def test_empty_query(self) -> None:
        specialty, conf, reason = classify_task_specialty("")
        assert specialty == TaskSpecialty.GENERAL
        assert reason == "empty_query"

    def test_multimodal_classification(self) -> None:
        query = [
            {"type": "text", "text": "Please identify the objects in this photo"},
            {"type": "image", "image": "base64data..."},
        ]
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.MULTIMODAL
        assert conf == 1.0
        assert "multimodal" in reason

    def test_long_document_by_char_length(self) -> None:
        long_text = "This is a comprehensive report on macroeconomic policy. " * 500
        assert len(long_text) >= LONG_DOC_CHAR_THRESHOLD
        specialty, conf, reason = classify_task_specialty(long_text)
        assert specialty == TaskSpecialty.LONG_DOC
        assert "char_length_exceeded" in reason

    def test_long_document_by_keywords(self) -> None:
        query = "请帮我通读这篇300页的年度财报并提取各分部营收数据"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.LONG_DOC
        assert "long_doc_keyword_match" in reason

    def test_reasoning_by_latex_notation(self) -> None:
        query = r"Compute the integral \int_{0}^{\infty} e^{-x^2} dx and show the step by step derivation"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.REASONING
        assert "math_latex_notation" in reason

    def test_reasoning_by_keywords(self) -> None:
        query = "请用数学归纳法证明任意大于1的整数都可以唯一分解为素数乘积"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.REASONING
        assert "reasoning_keyword_match" in reason

    def test_code_by_code_fence(self) -> None:
        query = "```python\ndef fib(n):\n    return n if n <= 1 else fib(n-1) + fib(n-2)\n```\n优化这段代码"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.CODE
        assert "code_fence_block" in reason

    def test_code_by_traceback(self) -> None:
        query = "运行报错了：\nTraceback (most recent call last):\n  File 'app.py', line 42\nTypeError: unsupported operand type"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.CODE
        assert "traceback_error_log" in reason

    def test_code_by_syntax_keywords(self) -> None:
        query = "async def handle_request(req: Request) -> Response:"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.CODE
        assert "code_syntax_declaration" in reason

    def test_code_by_multiple_keywords(self) -> None:
        query = "帮我为这个 typescript 模块编写 pytest 单元测试和 refactor"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.CODE
        assert "multiple_code_keywords" in reason

    def test_casual_indicator(self) -> None:
        query = "你好，请问在吗？"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.CASUAL
        assert "casual_indicator_match" in reason

    def test_session_momentum_inheritance(self) -> None:
        # A short ambiguous follow-up should inherit the previous technical specialty
        follow_up = "解释第12行"
        specialty, conf, reason = classify_task_specialty(
            follow_up,
            recent_specialties=[TaskSpecialty.CODE],
        )
        assert specialty == TaskSpecialty.CODE
        assert "momentum_inherited(code)" in reason

    def test_session_momentum_not_applied_to_long_new_query(self) -> None:
        long_query = "写一篇关于文艺复兴时期意大利佛罗伦萨绘画艺术风格演变的八百字评论文章"
        specialty, conf, reason = classify_task_specialty(
            long_query,
            recent_specialties=[TaskSpecialty.CODE],
        )
        assert specialty == TaskSpecialty.GENERAL
        assert "general_default" in reason


class TestFallbackChain:
    def test_build_fallback_chain_full(self) -> None:
        p1 = _make_cfg("deepseek/deepseek-coder")
        s_fb = _make_cfg("anthropic/claude-3-5-sonnet-20241022")
        d_p = _make_cfg("openai/gpt-4o")
        d_fb = _make_cfg("google/gemini-1.5-pro")

        chain = _build_fallback_chain(p1, s_fb, d_p, d_fb)
        assert len(chain) == 4
        assert [c.model for c in chain] == [
            "deepseek/deepseek-coder",
            "anthropic/claude-3-5-sonnet-20241022",
            "openai/gpt-4o",
            "google/gemini-1.5-pro",
        ]

    def test_build_fallback_chain_deduplication(self) -> None:
        p1 = _make_cfg("openai/gpt-4o")
        s_fb = None
        d_p = _make_cfg("openai/gpt-4o")
        d_fb = _make_cfg("openai/gpt-4o-mini")

        chain = _build_fallback_chain(p1, s_fb, d_p, d_fb)
        assert len(chain) == 2
        assert [c.model for c in chain] == ["openai/gpt-4o", "openai/gpt-4o-mini"]


@pytest.mark.asyncio
class TestRouteTaskSpecialty:
    async def test_route_to_configured_code_specialty(self) -> None:
        base_model = _make_cfg("openai/gpt-4o")
        code_model = _make_cfg("deepseek/deepseek-coder")
        code_fallback = _make_cfg("anthropic/claude-3-5-sonnet-20241022")

        slots = {TaskSpecialty.CODE: code_model}
        fb_slots = {TaskSpecialty.CODE: code_fallback}

        result = await route_task_specialty(
            "```python\ndef hello(): pass\n```",
            default_model_cfg=base_model,
            specialty_model_slots=slots,
            specialty_fallback_slots=fb_slots,
        )

        assert result.specialty == TaskSpecialty.CODE
        assert result.model_cfg.model == "deepseek/deepseek-coder"
        assert result.fallback_model_cfg is not None
        assert result.fallback_model_cfg.model == "anthropic/claude-3-5-sonnet-20241022"
        assert len(result.fallback_chain) >= 2
        assert "specialty_slot_hit" in result.reason

    async def test_route_unconfigured_specialty_smooth_fallback(self) -> None:
        base_model = _make_cfg("openai/gpt-4o")
        base_fallback = _make_cfg("openai/gpt-4o-mini")

        # No specialty slots configured
        result = await route_task_specialty(
            "请证明费马大定理",
            default_model_cfg=base_model,
            default_fallback_cfg=base_fallback,
        )

        assert result.specialty == TaskSpecialty.REASONING
        # Smooth degradation: unconfigured specialty slots fall back to default model
        assert result.model_cfg.model == "openai/gpt-4o"
        assert result.fallback_model_cfg is not None
        assert result.fallback_model_cfg.model == "openai/gpt-4o-mini"
        assert "specialty_slot_unconfigured_fallback" in result.reason
