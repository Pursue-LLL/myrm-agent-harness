"""Real-LLM e2e tests for the answer-content extraction helpers.

These exercises the exact code path fixed for reasoning models: the LLM returns
an ``AIMessage`` and ``extract_answer_text`` / ``extract_litellm_answer_text``
must return the real answer without leaking ``<think>`` blocks. No mocks on the
extraction path.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.utils.chat_utils import (
    extract_answer_text,
    extract_litellm_answer_text,
)

pytestmark = pytest.mark.e2e


async def _ask(llm, question: str) -> object:
    return await llm.ainvoke([HumanMessage(content=question)])


@pytest.mark.asyncio
async def test_extract_answer_text_basic_lane(basic_llm) -> None:
    """Real BASIC-lane LLM answer is extracted non-empty and free of think blocks."""
    response = await _ask(basic_llm, "Reply with exactly: hello world")
    text = extract_answer_text(response)
    assert isinstance(text, str)
    assert text.strip(), "extract_answer_text returned empty text for a real LLM response"
    assert "<think>" not in text and "</think>" not in text


@pytest.mark.asyncio
async def test_extract_answer_text_lite_lane(lite_llm) -> None:
    """Real LITE-lane (minimax) LLM answer is extracted non-empty."""
    response = await _ask(lite_llm, "Reply with exactly: hello world")
    text = extract_answer_text(response)
    assert isinstance(text, str)
    assert text.strip(), "extract_answer_text returned empty text for a real LLM response"


@pytest.mark.asyncio
async def test_extract_answer_text_strips_think_blocks(basic_llm) -> None:
    """A model that returns an answer inside <think>…</think> has the block stripped."""
    response = await _ask(
        basic_llm,
        "First think step by step inside a <think>...</think> block, then answer. Output exactly: final answer 42",
    )
    text = extract_answer_text(response)
    assert isinstance(text, str)
    assert text.strip(), "extract_answer_text returned empty text"
    assert "<think>" not in text and "</think>" not in text
    assert "42" in text


@pytest.mark.asyncio
async def test_extract_litellm_answer_text_real_llm() -> None:
    """extract_litellm_answer_text works on a raw litellm.acompletion response."""
    import litellm
    from conftest import litellm_config_for

    api_key, base_url, model, _provider = litellm_config_for("LITE")
    response = await litellm.acompletion(
        model=model,
        api_key=api_key,
        api_base=base_url,
        messages=[{"role": "user", "content": "Reply with exactly: litellm works"}],
        temperature=0.0,
        max_tokens=128,
    )
    text = extract_litellm_answer_text(response)
    assert isinstance(text, str)
    assert text.strip(), "extract_litellm_answer_text returned empty text"
    assert "litellm works" in text.lower()
