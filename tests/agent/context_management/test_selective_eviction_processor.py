"""Unit tests for SelectiveEvictionProcessor and mark-driven eviction algorithm."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.context_management.pipeline.base import ProcessorContext
from myrm_agent_harness.agent.context_management.pipeline.processors.selective_eviction_processor import (
    SelectiveEvictionProcessor,
)
from myrm_agent_harness.agent.context_management.strategies.compactor.selective_eviction import (
    evict_messages_by_marks,
)
from myrm_agent_harness.agent.context_management.working_memory.marks import (
    WorkingMemoryMark,
    with_message_marks,
)


@pytest.mark.asyncio
async def test_evict_transient_hints_and_scratchpads():
    msg_normal = HumanMessage(content="User task")
    msg_hint = HumanMessage(content="Temporary reflection hint")
    with_message_marks(msg_hint, WorkingMemoryMark.HINT)

    msg_scratchpad = AIMessage(content="Intermediate scratchpad draft")
    with_message_marks(msg_scratchpad, WorkingMemoryMark.SCRATCHPAD)

    msg_pinned = SystemMessage(content="Pinned rule: never modify database")
    with_message_marks(msg_pinned, WorkingMemoryMark.PINNED)

    messages = [msg_normal, msg_hint, msg_scratchpad, msg_pinned]

    retained, stats = evict_messages_by_marks(messages)

    # Hint and scratchpad must be evicted; normal and pinned must be retained
    assert len(retained) == 2
    assert retained[0] == msg_normal
    assert retained[1] == msg_pinned
    assert stats.evicted_count == 2
    assert "hint" in stats.evicted_marks
    assert "scratchpad" in stats.evicted_marks
    assert stats.immune_protected_count == 1
    assert stats.tokens_saved > 0


@pytest.mark.asyncio
async def test_tool_pair_invariant_folded_not_dangling():
    """Verify ToolMessage with raw output mark is folded rather than deleted, preventing dangling tool call."""
    call_id = "call_abc123"
    ai_msg = AIMessage(
        content="calling test tool",
        tool_calls=[{"name": "test_tool", "args": {"cmd": "run"}, "id": call_id}],
    )
    tool_msg = ToolMessage(
        content="Very long test output line 1\nline 2\n" * 100,
        tool_call_id=call_id,
        name="test_tool",
    )
    with_message_marks(tool_msg, WorkingMemoryMark.TOOL_RAW_OUTPUT)

    messages = [ai_msg, tool_msg]

    # Target tool_raw_output for eviction
    retained, stats = evict_messages_by_marks(
        messages,
        target_marks={WorkingMemoryMark.TOOL_RAW_OUTPUT.value},
    )

    # Both AIMessage and ToolMessage must still be present to preserve Tool Pair Invariant
    assert len(retained) == 2
    assert retained[0] == ai_msg
    assert isinstance(retained[1], ToolMessage)
    assert retained[1].tool_call_id == call_id
    assert "[Folded tool output" in str(retained[1].content)
    assert stats.tool_pairs_folded == 1
    assert stats.tokens_saved > 0


@pytest.mark.asyncio
async def test_selective_eviction_processor_pipeline_integration():
    processor = SelectiveEvictionProcessor()

    msg_normal = HumanMessage(content="User query")
    msg_transient = AIMessage(content="Single turn reflection note")
    with_message_marks(msg_transient, WorkingMemoryMark.HINT)

    context = ProcessorContext(
        messages=[msg_normal, msg_transient],
        user_query="User query",
    )

    should = await processor.should_process(context)
    assert should is True

    processed_ctx = await processor.process(context)
    assert len(processed_ctx.messages) == 1
    assert processed_ctx.messages[0] == msg_normal
    assert processed_ctx.tokens_saved > 0
    assert any("selective_eviction" in op for op in processed_ctx.operations)
    assert "selective_eviction_stats" in processed_ctx.metadata


@pytest.mark.asyncio
async def test_summarize_processor_pre_evicts_transient_hints():
    """Verify SummarizeProcessor clears transient hints before deciding to summarize."""
    from myrm_agent_harness.agent.context_management.infra.schemas import ContextConfig
    from myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor import (
        SummarizeProcessor,
    )

    config = ContextConfig(max_context_tokens=100000)
    processor = SummarizeProcessor(config=config)

    msg_main = HumanMessage(content="A normal user instruction that must remain")
    msg_hint = HumanMessage(content="A temporary hint that should be shed before summarize")
    with_message_marks(msg_hint, WorkingMemoryMark.HINT)

    context = ProcessorContext(
        messages=[msg_main, msg_hint],
        user_query="A normal user instruction that must remain",
    )

    # Process through summarize processor
    processed_ctx = await processor.process(context)

    # Transient hint should be purged via pre_summarize_eviction (not in resulting messages)
    assert all("temporary hint" not in str(m.content) for m in processed_ctx.messages)
    assert any("pre_summarize_eviction" in op for op in processed_ctx.operations)


@pytest.mark.asyncio
async def test_selective_eviction_idempotency_cleanses_marks():
    """Verify that folding a ToolMessage cleanses the eviction mark, ensuring mathematical idempotency."""
    call_id = "call_repeat_123"
    ai_msg = AIMessage(
        content="running draft tool",
        tool_calls=[{"name": "draft_tool", "args": {}, "id": call_id}],
    )
    tool_msg = ToolMessage(
        content="temporary draft data " * 50,
        tool_call_id=call_id,
        name="draft_tool",
    )
    with_message_marks(tool_msg, WorkingMemoryMark.SCRATCHPAD)

    messages = [ai_msg, tool_msg]

    # First eviction run
    first_retained, first_stats = evict_messages_by_marks(
        messages,
        target_marks={WorkingMemoryMark.SCRATCHPAD.value},
    )
    assert first_stats.tool_pairs_folded == 1
    assert first_stats.evicted_count == 1
    assert "[Folded tool output" in str(first_retained[1].content)

    # Second eviction run on the output of the first run (idempotency check: f(f(x)) == f(x))
    second_retained, second_stats = evict_messages_by_marks(
        first_retained,
        target_marks={WorkingMemoryMark.SCRATCHPAD.value},
    )
    # Must be 0 because the folded ToolMessage had its scratchpad mark stripped
    assert second_stats.tool_pairs_folded == 0
    assert second_stats.evicted_count == 0
    assert second_stats.tokens_saved == 0
    assert len(second_retained) == len(first_retained)
    assert second_retained[1].content == first_retained[1].content


