"""Tests for cross-vendor task domain specialty router."""

import pytest
from myrm_agent_harness.core.config.llm import LLMConfig
from myrm_agent_harness.toolkits.llms.routing.specialty_router import (
    LONG_DOC_CHAR_THRESHOLD,
    SpecialtyRoutingResult,
    TaskSpecialty,
    classify_task_specialty,
    route_task_specialty,
)

_DUMMY_KEY = "sk-specialty-test-key"


def _cfg(model: str) -> LLMConfig:
    return LLMConfig(model=model, api_key=_DUMMY_KEY)


DEFAULT_CFG = _cfg("openai/gpt-4o")
DEFAULT_FALLBACK = _cfg("anthropic/claude-3-5-sonnet")
CODE_CFG = _cfg("deepseek/deepseek-coder")
CODE_FALLBACK = _cfg("qwen/qwen-2.5-coder-32b")
LONG_DOC_CFG = _cfg("moonshot/moonshot-v1-128k")
REASONING_CFG = _cfg("openai/o1")


class TestClassifyTaskSpecialty:
    def test_empty_query(self) -> None:
        specialty, conf, reason = classify_task_specialty("")
        assert specialty == TaskSpecialty.GENERAL
        assert reason == "empty_query"

    def test_multimodal_media_present(self) -> None:
        query = [
            {"type": "text", "text": "What is in this image?"},
            {"type": "image_url", "url": "https://example.com/a.png"},
        ]
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.MULTIMODAL
        assert conf == 1.0

    def test_long_document_char_threshold(self) -> None:
        long_text = "This is a comprehensive report on software design. " * 600
        assert len(long_text) >= LONG_DOC_CHAR_THRESHOLD
        specialty, conf, reason = classify_task_specialty(long_text)
        assert specialty == TaskSpecialty.LONG_DOC
        assert "char_length_exceeded" in reason

    def test_long_document_keywords(self) -> None:
        query = "请阅读整份报告并提取附录中的所有风险点"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.LONG_DOC
        assert "long_doc_keyword_match" in reason

    def test_math_reasoning_latex(self) -> None:
        query = r"请证明当 $n \ge 1$ 时，\sum_{i=1}^n i = \frac{n(n+1)}{2}"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.REASONING
        assert "math_latex_notation" in reason

    def test_math_reasoning_keywords(self) -> None:
        query = "请使用数学归纳法证明费马小定理"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.REASONING
        assert "reasoning_keyword_match" in reason

    def test_code_fence_block(self) -> None:
        query = "请重构这段代码：\n```python\ndef solve():\n    return 42\n```"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.CODE
        assert "code_fence_block" in reason

    def test_code_traceback(self) -> None:
        query = "帮我看看这个报错：\nTraceback (most recent call last):\n  File \"app.py\", line 12, in <module>\nTypeError: unsupported operand"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.CODE
        assert "traceback_error_log" in reason

    def test_code_syntax_declaration(self) -> None:
        query = "请编写 async def fetch_user_data(user_id: int) -> dict:"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.CODE
        assert "code_syntax_declaration" in reason

    def test_code_keywords_and_intent(self) -> None:
        query = "帮我编写一个 typescript 的 rest api endpoint"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.CODE

    def test_general_fallback(self) -> None:
        query = "你好，今天北京天气怎么样？"
        specialty, conf, reason = classify_task_specialty(query)
        assert specialty == TaskSpecialty.GENERAL
        assert reason == "general_default"


@pytest.mark.asyncio
class TestRouteTaskSpecialty:
    async def test_route_to_configured_code_slot(self) -> None:
        query = "```rust\nfn main() { println!(\"Hello\"); }\n```"
        slots = {
            TaskSpecialty.CODE: CODE_CFG,
            TaskSpecialty.LONG_DOC: LONG_DOC_CFG,
        }
        fallback_slots = {
            TaskSpecialty.CODE: CODE_FALLBACK,
        }

        result = await route_task_specialty(
            query=query,
            default_model_cfg=DEFAULT_CFG,
            specialty_model_slots=slots,
            specialty_fallback_slots=fallback_slots,
            default_fallback_cfg=DEFAULT_FALLBACK,
        )

        assert isinstance(result, SpecialtyRoutingResult)
        assert result.specialty == TaskSpecialty.CODE
        assert result.model_cfg.model == "deepseek/deepseek-coder"
        assert result.fallback_model_cfg is not None
        assert result.fallback_model_cfg.model == "qwen/qwen-2.5-coder-32b"
        assert "specialty_slot_hit" in result.reason

    async def test_route_to_unconfigured_slot_smooth_fallback(self) -> None:
        query = r"请推导 \int_0^\infty e^{-x^2} dx 的高斯积分公式"
        # Reasoning slot is not configured in slots
        slots = {
            TaskSpecialty.CODE: CODE_CFG,
        }

        result = await route_task_specialty(
            query=query,
            default_model_cfg=DEFAULT_CFG,
            specialty_model_slots=slots,
            default_fallback_cfg=DEFAULT_FALLBACK,
        )

        assert result.specialty == TaskSpecialty.REASONING
        # Falls back gracefully to DEFAULT_CFG
        assert result.model_cfg.model == "openai/gpt-4o"
        assert result.fallback_model_cfg is not None
        assert result.fallback_model_cfg.model == "anthropic/claude-3-5-sonnet"
        assert "specialty_slot_unconfigured_fallback" in result.reason

    async def test_route_general_query(self) -> None:
        query = "请帮我写一封感谢信"
        slots = {
            TaskSpecialty.CODE: CODE_CFG,
            TaskSpecialty.REASONING: REASONING_CFG,
        }

        result = await route_task_specialty(
            query=query,
            default_model_cfg=DEFAULT_CFG,
            specialty_model_slots=slots,
            default_fallback_cfg=DEFAULT_FALLBACK,
        )

        assert result.specialty == TaskSpecialty.GENERAL
        assert result.model_cfg.model == "openai/gpt-4o"
        assert "specialty_slot_unconfigured_fallback" in result.reason
