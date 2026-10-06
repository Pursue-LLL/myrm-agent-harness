"""Tests for AppendOnlyContextTailInvariantGuard and DeferredWriteBuffer."""

from __future__ import annotations

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)

from myrm_agent_harness.runtime.context.append_only_kv_cache_guard import (
    AppendOnlyContextTailInvariantGuard,
    CompactionBypassToken,
    DeferredWriteBuffer,
    DeferredWriteType,
    KVCacheTailInvariantViolationError,
    ViolationType,
)


def test_append_only_valid_tail_growth() -> None:
    """Verify context growing strictly at tail passes validation and updates baseline."""
    guard = AppendOnlyContextTailInvariantGuard(session_id="sess-001")

    # Round 1: [Sys, User1]
    turn1 = [
        SystemMessage(content="You are a coding assistant."),
        HumanMessage(content="Hello world"),
    ]
    assert guard.verify_append_only(turn1) is True
    assert guard.baseline_prefix_length == 2

    # Round 2: Append [AI1, Tool1] at tail
    tc = ToolCall(name="view_file", args={"path": "app.py"}, id="tc-1")
    turn2 = [
        *turn1,
        AIMessage(content="Checking app.py", tool_calls=[tc]),
        ToolMessage(content="print('ok')", tool_call_id="tc-1"),
    ]
    assert guard.verify_append_only(turn2) is True
    assert guard.baseline_prefix_length == 4

    # Round 3: Append [Human2] at tail
    turn3 = [*turn2, HumanMessage(content="Next step")]
    assert guard.verify_append_only(turn3) is True
    assert guard.baseline_prefix_length == 5


def test_mid_stream_insertion_rejected() -> None:
    """Verify inserting messages in the middle is rejected to protect KV cache."""
    guard = AppendOnlyContextTailInvariantGuard(session_id="sess-001")

    initial = [
        SystemMessage(content="System prompt"),
        HumanMessage(content="User prompt 1"),
        AIMessage(content="AI response 1"),
    ]
    guard.record_provider_request(initial)

    # Invalidate prefix by inserting an unprompted message between User and AI
    invalid_inserted = [
        SystemMessage(content="System prompt"),
        HumanMessage(content="User prompt 1"),
        HumanMessage(content="SURPRISE INJECTED NOTE"),  # Mid-stream insertion!
        AIMessage(content="AI response 1"),
    ]

    with pytest.raises(KVCacheTailInvariantViolationError) as exc_info:
        guard.verify_append_only(invalid_inserted)

    assert exc_info.value.violation_type == ViolationType.MID_STREAM_INSERTION
    assert exc_info.value.index == 2


def test_prefix_mutation_rejected() -> None:
    """Verify modifying an existing message content in the prefix is rejected."""
    guard = AppendOnlyContextTailInvariantGuard(session_id="sess-001")

    initial = [
        SystemMessage(content="System prompt"),
        HumanMessage(content="Original prompt"),
    ]
    guard.record_provider_request(initial)

    # Mutate existing message text
    mutated = [
        SystemMessage(content="System prompt"),
        HumanMessage(content="MUTATED prompt text"),  # Mutation breaks KV cache
        AIMessage(content="New response"),
    ]

    with pytest.raises(KVCacheTailInvariantViolationError) as exc_info:
        guard.verify_append_only(mutated)

    assert exc_info.value.violation_type == ViolationType.PREFIX_MUTATED
    assert exc_info.value.index == 1


def test_prefix_truncation_rejected() -> None:
    """Verify truncating prior context without compaction token is rejected."""
    guard = AppendOnlyContextTailInvariantGuard(session_id="sess-001")

    initial = [
        SystemMessage(content="System prompt"),
        HumanMessage(content="Msg 1"),
        AIMessage(content="Msg 2"),
    ]
    guard.record_provider_request(initial)

    # Truncate to just 1 message
    truncated = [
        SystemMessage(content="System prompt"),
    ]

    with pytest.raises(KVCacheTailInvariantViolationError) as exc_info:
        guard.verify_append_only(truncated)

    assert exc_info.value.violation_type == ViolationType.PREFIX_TRUNCATED


def test_compaction_bypass_token_allows_reconstruction() -> None:
    """Verify valid compaction bypass token permits prefix reconstruction and anchors new baseline."""
    guard = AppendOnlyContextTailInvariantGuard(session_id="sess-001")

    # Turn 1: 4 messages
    turn1 = [
        SystemMessage(content="System prompt"),
        HumanMessage(content="Old Msg 1"),
        AIMessage(content="Old Msg 2"),
        HumanMessage(content="Old Msg 3"),
    ]
    guard.record_provider_request(turn1)
    assert guard.baseline_prefix_length == 4

    # Compaction replaces old history with summary checkpoint + recent tail
    compacted = [
        SystemMessage(content="System prompt"),
        HumanMessage(content="[previous-summary] Summarized older turns"),
        HumanMessage(content="Old Msg 3"),
    ]

    # Without token -> fails as truncation
    with pytest.raises(KVCacheTailInvariantViolationError):
        guard.verify_append_only(compacted)

    # With mismatched session token -> fails
    invalid_token = CompactionBypassToken.create(session_id="sess-999")
    with pytest.raises(KVCacheTailInvariantViolationError):
        guard.verify_append_only(compacted, bypass_token=invalid_token)

    # With valid token -> succeeds and anchors new baseline
    valid_token = CompactionBypassToken.create(session_id="sess-001")
    assert guard.verify_append_only(compacted, bypass_token=valid_token) is True
    assert guard.baseline_prefix_length == 3

    # Subsequent append-only request builds on the new baseline
    turn2 = [*compacted, AIMessage(content="Continuing after compaction")]
    assert guard.verify_append_only(turn2) is True
    assert guard.baseline_prefix_length == 4


def test_deferred_write_buffer_checkpoint_flush() -> None:
    """Verify mid-turn writes are staged in buffer and flushed as tail appends at checkpoint."""
    guard = AppendOnlyContextTailInvariantGuard(session_id="sess-001")
    buffer = DeferredWriteBuffer()

    messages = [
        SystemMessage(content="System prompt"),
        HumanMessage(content="Initial task"),
    ]
    guard.record_provider_request(messages)

    # Mid-turn: stage external configuration update and environment fact
    buffer.stage_write(
        DeferredWriteType.CONFIG_UPDATE,
        "temperature=0.2, thinking_level=high",
        run_id="run-1",
    )
    buffer.stage_write(
        DeferredWriteType.ENVIRONMENT_FACT,
        "Memory usage: 42%",
        run_id="run-1",
    )
    assert buffer.pending_count == 2

    # At checkpoint boundary: flush into tail of messages
    flushed_messages = buffer.flush_at_checkpoint(messages)
    assert buffer.pending_count == 0
    assert len(flushed_messages) == 4

    # Verify new messages are appended at tail
    assert flushed_messages[2].content == "[CONFIG_UPDATE] temperature=0.2, thinking_level=high"
    assert flushed_messages[3].content == "[ENVIRONMENT_FACT] Memory usage: 42%"

    # Validate against guard: since it strictly grew at the tail, invariant passes!
    assert guard.verify_append_only(flushed_messages) is True
    assert guard.baseline_prefix_length == 4
