"""Tests for ThinkingBlockCleaner processor.

Covers:
- Anthropic: remove reasoning_content, keep thinking_blocks
- Non-Anthropic: selective reasoning_content cleanup based on tool_calls + position
- chars_dropped telemetry and tokens_saved accumulation
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.thinking_cleaner import (
    ThinkingBlockCleaner,
    _find_last_human_index,
    _has_tool_calls,
)


def _ctx(messages, model_name="openai/gpt-4"):
    class FakeLLM:
        def __init__(self, name):
            self.model_name = name

    return ProcessorContext(messages=messages, user_query="test", llm=FakeLLM(model_name))


# ── should_process gate ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_should_process_no_thinking():
    cleaner = ThinkingBlockCleaner()
    ctx = _ctx([HumanMessage(content="hi"), AIMessage(content="hello")])
    assert not await cleaner.should_process(ctx)


@pytest.mark.asyncio
async def test_should_process_has_reasoning():
    cleaner = ThinkingBlockCleaner()
    msg = AIMessage(content="answer", additional_kwargs={"reasoning_content": "I think..."})
    ctx = _ctx([msg])
    assert await cleaner.should_process(ctx)


# ── Anthropic path ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clean_reasoning_for_anthropic():
    """Anthropic: reasoning_content removed, thinking_blocks kept."""
    cleaner = ThinkingBlockCleaner()
    msg = AIMessage(
        content="answer",
        additional_kwargs={
            "reasoning_content": "I reasoned about...",
            "thinking_blocks": [{"type": "thinking", "thinking": "deep thought"}],
        },
    )
    ctx = _ctx([msg], model_name="anthropic/claude-3-opus-20240229")
    result = await cleaner.process(ctx)

    kwargs = result.messages[0].additional_kwargs
    assert "reasoning_content" not in kwargs
    assert kwargs["thinking_blocks"] == [{"type": "thinking", "thinking": "deep thought"}]


@pytest.mark.asyncio
async def test_anthropic_chars_dropped():
    """Anthropic: chars_dropped tracks removed reasoning_content length."""
    cleaner = ThinkingBlockCleaner()
    rc_text = "x" * 3000
    msg = AIMessage(content="ok", additional_kwargs={"reasoning_content": rc_text})
    ctx = _ctx([msg], model_name="anthropic/claude-sonnet-4-20250514")
    result = await cleaner.process(ctx)
    assert result.tokens_saved == 3000 // 4


# ── Non-Anthropic: selective cleanup ────────────────────────────────


@pytest.mark.asyncio
async def test_plain_text_before_last_human_cleaned():
    """Plain-text assistant msg BEFORE last human → reasoning_content removed."""
    cleaner = ThinkingBlockCleaner()
    rc_text = "thinking about crawlers..." * 100
    messages = [
        HumanMessage(content="write a crawler"),
        AIMessage(content="ok", additional_kwargs={"reasoning_content": rc_text}),
        HumanMessage(content="use requests"),
    ]
    ctx = _ctx(messages, model_name="deepseek/deepseek-v4-flash")
    result = await cleaner.process(ctx)

    assert "reasoning_content" not in result.messages[1].additional_kwargs
    assert result.tokens_saved == len(rc_text) // 4


@pytest.mark.asyncio
async def test_tool_call_before_last_human_preserved():
    """Tool-call assistant msg BEFORE last human → reasoning_content preserved (API requirement)."""
    cleaner = ThinkingBlockCleaner()
    rc_text = "let me write the file..."
    messages = [
        HumanMessage(content="write code"),
        AIMessage(
            content="",
            additional_kwargs={
                "reasoning_content": rc_text,
                "tool_calls": [{"id": "tc1", "function": {"name": "file_write", "arguments": "{}"}}],
            },
        ),
        HumanMessage(content="next"),
    ]
    ctx = _ctx(messages, model_name="deepseek/deepseek-v4-flash")
    result = await cleaner.process(ctx)

    assert result.messages[1].additional_kwargs["reasoning_content"] == rc_text
    assert result.tokens_saved == 0


@pytest.mark.asyncio
async def test_after_last_human_always_preserved():
    """Assistant msg AFTER last human → reasoning_content always preserved."""
    cleaner = ThinkingBlockCleaner()
    rc_text = "latest thinking"
    messages = [
        HumanMessage(content="question"),
        AIMessage(content="answer", additional_kwargs={"reasoning_content": rc_text}),
    ]
    ctx = _ctx(messages, model_name="deepseek/deepseek-v4-flash")
    result = await cleaner.process(ctx)

    assert result.messages[1].additional_kwargs["reasoning_content"] == rc_text


@pytest.mark.asyncio
async def test_langchain_tool_calls_detected():
    """AIMessage.tool_calls (LangChain native) should prevent cleanup."""
    cleaner = ThinkingBlockCleaner()
    rc_text = "planning tool use"
    msg = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": rc_text},
        tool_calls=[{"name": "bash", "args": {"cmd": "ls"}, "id": "tc1"}],
    )
    messages = [HumanMessage(content="list files"), msg, HumanMessage(content="next")]
    ctx = _ctx(messages, model_name="deepseek/deepseek-v4-flash")
    result = await cleaner.process(ctx)

    assert result.messages[1].additional_kwargs["reasoning_content"] == rc_text


@pytest.mark.asyncio
async def test_thinking_blocks_cleaned_for_non_anthropic():
    """Non-Anthropic: thinking_blocks always removed; reasoning_content on latest turn preserved."""
    cleaner = ThinkingBlockCleaner()
    msg = AIMessage(
        content="answer",
        additional_kwargs={
            "reasoning_content": "latest thinking",
            "thinking_blocks": [{"type": "thinking", "thinking": "block"}],
        },
    )
    messages = [HumanMessage(content="prev"), msg]
    ctx = _ctx(messages, model_name="openai/gpt-4o")
    result = await cleaner.process(ctx)

    kwargs = result.messages[1].additional_kwargs
    assert "thinking_blocks" not in kwargs
    assert kwargs["reasoning_content"] == "latest thinking"


@pytest.mark.asyncio
async def test_multi_turn_selective_cleanup():
    """Multi-turn: only plain-text msgs before last human get cleaned."""
    cleaner = ThinkingBlockCleaner()
    messages = [
        HumanMessage(content="q1"),
        AIMessage(content="a1", additional_kwargs={"reasoning_content": "rc1_plain"}),
        HumanMessage(content="q2"),
        AIMessage(
            content="",
            additional_kwargs={
                "reasoning_content": "rc2_tool",
                "tool_calls": [{"id": "tc", "function": {"name": "bash", "arguments": "{}"}}],
            },
        ),
        HumanMessage(content="q3"),
        AIMessage(content="a3", additional_kwargs={"reasoning_content": "rc3_after"}),
    ]
    ctx = _ctx(messages, model_name="deepseek/deepseek-v4-flash")
    result = await cleaner.process(ctx)

    # rc1_plain: before last human, no tool_calls → removed
    assert "reasoning_content" not in result.messages[1].additional_kwargs
    # rc2_tool: before last human but has tool_calls → preserved
    assert result.messages[3].additional_kwargs["reasoning_content"] == "rc2_tool"
    # rc3_after: after last human → preserved
    assert result.messages[5].additional_kwargs["reasoning_content"] == "rc3_after"
    assert result.tokens_saved == len("rc1_plain") // 4


@pytest.mark.asyncio
async def test_no_human_message_preserves_all():
    """No HumanMessage at all → nothing cleaned (last_human_idx = -1)."""
    cleaner = ThinkingBlockCleaner()
    msg = AIMessage(content="solo", additional_kwargs={"reasoning_content": "keep"})
    ctx = _ctx([msg], model_name="deepseek/deepseek-v4-flash")
    result = await cleaner.process(ctx)

    assert result.messages[0].additional_kwargs["reasoning_content"] == "keep"


@pytest.mark.asyncio
async def test_no_llm_cleans_thinking_blocks():
    """When no LLM info, clean thinking_blocks, apply selective reasoning cleanup."""
    cleaner = ThinkingBlockCleaner()
    rc_text = "x" * 500
    msg = AIMessage(
        content="answer",
        additional_kwargs={
            "reasoning_content": rc_text,
            "thinking_blocks": [{"type": "thinking"}],
        },
    )
    messages = [msg, HumanMessage(content="next")]
    ctx = ProcessorContext(messages=messages, user_query="test", llm=None)
    result = await cleaner.process(ctx)

    kwargs = result.messages[0].additional_kwargs
    assert "thinking_blocks" not in kwargs
    assert "reasoning_content" not in kwargs
    assert result.tokens_saved == 500 // 4


# ── helper function unit tests ──────────────────────────────────────


def test_has_tool_calls_empty():
    msg = AIMessage(content="no tools")
    assert not _has_tool_calls(msg)


def test_has_tool_calls_via_kwargs():
    msg = AIMessage(
        content="",
        additional_kwargs={"tool_calls": [{"id": "1", "function": {"name": "x", "arguments": "{}"}}]},
    )
    assert _has_tool_calls(msg)


def test_has_tool_calls_via_langchain():
    msg = AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "1"}])
    assert _has_tool_calls(msg)


def test_find_last_human_index_basic():
    msgs = [HumanMessage(content="a"), AIMessage(content="b"), HumanMessage(content="c")]
    assert _find_last_human_index(msgs) == 2


def test_find_last_human_index_none():
    msgs = [AIMessage(content="alone")]
    assert _find_last_human_index(msgs) == -1


# ── edge cases for full branch coverage ──────────────────────────────


@pytest.mark.asyncio
async def test_should_process_thinking_blocks_only():
    """should_process returns True when only thinking_blocks present (no reasoning_content)."""
    cleaner = ThinkingBlockCleaner()
    msg = AIMessage(content="hi", additional_kwargs={"thinking_blocks": [{"type": "thinking"}]})
    ctx = _ctx([msg])
    assert await cleaner.should_process(ctx)


@pytest.mark.asyncio
async def test_empty_kwargs_skipped():
    """AIMessage with empty additional_kwargs → silently skipped."""
    cleaner = ThinkingBlockCleaner()
    messages = [
        AIMessage(content="no kwargs"),
        HumanMessage(content="q"),
    ]
    ctx = _ctx(messages, model_name="deepseek/deepseek-v4-flash")
    result = await cleaner.process(ctx)
    assert result.tokens_saved == 0
    assert result.messages[0].content == "no kwargs"


@pytest.mark.asyncio
async def test_anthropic_non_string_reasoning_content():
    """Anthropic: reasoning_content of non-str type (e.g. True) → removed but chars_dropped stays 0."""
    cleaner = ThinkingBlockCleaner()
    msg = AIMessage(content="ok", additional_kwargs={"reasoning_content": True})
    ctx = _ctx([msg], model_name="anthropic/claude-sonnet-4-20250514")
    result = await cleaner.process(ctx)
    assert "reasoning_content" not in result.messages[0].additional_kwargs
    assert result.tokens_saved == 0


def test_name_property():
    assert ThinkingBlockCleaner().name == "ThinkingBlockCleaner"


@pytest.mark.asyncio
async def test_llm_with_model_attr_only():
    """LLM object has 'model' attr but no 'model_name' → still detects model correctly."""
    cleaner = ThinkingBlockCleaner()

    class ModelOnlyLLM:
        model = "anthropic/claude-3-haiku-20240307"

    msg = AIMessage(content="ok", additional_kwargs={"reasoning_content": "think"})
    ctx = ProcessorContext(messages=[msg], user_query="test", llm=ModelOnlyLLM())
    result = await cleaner.process(ctx)
    assert "reasoning_content" not in result.messages[0].additional_kwargs


@pytest.mark.asyncio
async def test_non_anthropic_rc_not_string_preserved():
    """Non-Anthropic: reasoning_content of non-str type → preserved (isinstance(rc, str) guard)."""
    cleaner = ThinkingBlockCleaner()
    msg = AIMessage(content="ok", additional_kwargs={"reasoning_content": 42})
    messages = [msg, HumanMessage(content="next")]
    ctx = _ctx(messages, model_name="deepseek/deepseek-v4-flash")
    result = await cleaner.process(ctx)
    assert result.messages[0].additional_kwargs["reasoning_content"] == 42


# ── _is_anthropic_model edge cases ──────────────────────────────────


@pytest.mark.asyncio
async def test_anthropic_model_via_slash_prefix():
    """Model name with '/claude' substring → detected as Anthropic (e.g. proxy routing)."""
    from myrm_agent_harness.agent.context_management.pipeline.processors.thinking_cleaner import (
        _is_anthropic_model,
    )

    assert _is_anthropic_model("openrouter/anthropic/claude-3-opus")
    assert _is_anthropic_model("bedrock/claude-sonnet")
    assert not _is_anthropic_model("deepseek/deepseek-v4")


# ── _has_tool_calls edge cases ──────────────────────────────────────


def test_has_tool_calls_empty_list():
    """tool_calls as empty list → False."""
    msg = AIMessage(content="", additional_kwargs={"tool_calls": []})
    assert not _has_tool_calls(msg)


def test_has_tool_calls_non_list():
    """tool_calls as non-list (e.g. string) → False."""
    msg = AIMessage(content="", additional_kwargs={"tool_calls": "invalid"})
    assert not _has_tool_calls(msg)


# ── _find_last_human_index edge cases ──────────────────────────────


def test_find_last_human_index_empty_list():
    """Empty message list → -1."""
    assert _find_last_human_index([]) == -1


# ── process edge cases ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_model_name_returns_none():
    """LLM whose model_name returns None → fallback chain handles gracefully."""
    cleaner = ThinkingBlockCleaner()

    class NoneModelLLM:
        model_name = None
        model = None

    rc_text = "old thinking"
    messages = [
        AIMessage(content="ok", additional_kwargs={"reasoning_content": rc_text}),
        HumanMessage(content="q"),
    ]
    ctx = ProcessorContext(messages=messages, user_query="test", llm=NoneModelLLM())
    result = await cleaner.process(ctx)
    assert "reasoning_content" not in result.messages[0].additional_kwargs


@pytest.mark.asyncio
async def test_anthropic_only_thinking_blocks_no_rc():
    """Anthropic: only thinking_blocks present (no reasoning_content) → nothing cleaned, tb untouched."""
    cleaner = ThinkingBlockCleaner()
    msg = AIMessage(
        content="ok",
        additional_kwargs={"thinking_blocks": [{"type": "thinking", "thinking": "tb only"}]},
    )
    ctx = _ctx([msg], model_name="anthropic/claude-3-opus-20240229")
    result = await cleaner.process(ctx)
    assert result.messages[0].additional_kwargs["thinking_blocks"] == [
        {"type": "thinking", "thinking": "tb only"}
    ]
    assert result.tokens_saved == 0


@pytest.mark.asyncio
async def test_multiple_anthropic_messages_cleaned():
    """Multiple AI messages with reasoning_content → all cleaned in one pass."""
    cleaner = ThinkingBlockCleaner()
    messages = [
        AIMessage(content="a1", additional_kwargs={"reasoning_content": "rc1" * 100}),
        HumanMessage(content="q"),
        AIMessage(content="a2", additional_kwargs={"reasoning_content": "rc2" * 200}),
    ]
    ctx = _ctx(messages, model_name="anthropic/claude-3-opus-20240229")
    result = await cleaner.process(ctx)
    assert "reasoning_content" not in result.messages[0].additional_kwargs
    assert "reasoning_content" not in result.messages[2].additional_kwargs
    expected_chars = len("rc1" * 100) + len("rc2" * 200)
    assert result.tokens_saved == expected_chars // 4


@pytest.mark.asyncio
async def test_tokens_saved_accumulates():
    """tokens_saved accumulates on top of pre-existing value."""
    cleaner = ThinkingBlockCleaner()
    rc_text = "x" * 400
    msg = AIMessage(content="ok", additional_kwargs={"reasoning_content": rc_text})
    ctx = _ctx([msg], model_name="anthropic/claude-sonnet-4-20250514")
    ctx.tokens_saved = 50
    result = await cleaner.process(ctx)
    assert result.tokens_saved == 50 + 400 // 4


@pytest.mark.asyncio
async def test_no_cleaning_no_log_no_tokens_saved():
    """When no items need cleaning → tokens_saved stays unchanged, no side effects."""
    cleaner = ThinkingBlockCleaner()
    messages = [
        HumanMessage(content="q"),
        AIMessage(content="just text, no rc/tb"),
    ]
    ctx = _ctx(messages, model_name="deepseek/deepseek-v4-flash")
    ctx.tokens_saved = 99
    result = await cleaner.process(ctx)
    assert result.tokens_saved == 99
