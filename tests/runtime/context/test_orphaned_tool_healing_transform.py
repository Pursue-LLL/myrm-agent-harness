"""Tests for Orphaned Tool Call Provider Transform Healing (Pi Harness v2 Item 21)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.runtime.context.orphaned_tool_healing_transform import (
    CanonicalMessageRole,
    CanonicalMessageTurn,
    CanonicalToolCallDescriptor,
    HealingMetrics,
    OrphanedToolCallHealingTransform,
    heal_orphaned_tool_calls_canonical,
    heal_orphaned_tool_calls_langchain,
)


def test_canonical_mid_batch_tail_healed_at_request_build_time() -> None:
    """Test when fork/navigate leaves branch tip mid-tool-batch, synthetic empty results are appended."""
    turns = [
        CanonicalMessageTurn(role=CanonicalMessageRole.USER, content="Run diagnostics"),
        CanonicalMessageTurn(
            role=CanonicalMessageRole.ASSISTANT,
            content="I will check cpu, mem, and disk.",
            tool_calls=(
                CanonicalToolCallDescriptor(tool_call_id="call-cpu", tool_name="check_cpu"),
                CanonicalToolCallDescriptor(tool_call_id="call-mem", tool_name="check_mem"),
                CanonicalToolCallDescriptor(tool_call_id="call-disk", tool_name="check_disk"),
            ),
        ),
        CanonicalMessageTurn(
            role=CanonicalMessageRole.TOOL,
            tool_call_id="call-cpu",
            tool_name="check_cpu",
            content="CPU: 45%",
        ),
        # Fork or navigation occurred right here: call-mem and call-disk never settled
    ]

    healed, metrics = heal_orphaned_tool_calls_canonical(turns)
    assert isinstance(metrics, HealingMetrics)
    assert metrics.total_messages_in == 3
    assert metrics.synthesized_count == 2
    assert metrics.synthesized_call_ids == ("call-mem", "call-disk")
    assert len(healed) == 5

    # Check that tool results are properly matched
    roles = [h.role for h in healed]
    assert roles == [
        CanonicalMessageRole.USER,
        CanonicalMessageRole.ASSISTANT,
        CanonicalMessageRole.TOOL,
        CanonicalMessageRole.TOOL,
        CanonicalMessageRole.TOOL,
    ]
    tool_ids = [h.tool_call_id for h in healed if h.role == CanonicalMessageRole.TOOL]
    assert tool_ids == ["call-cpu", "call-mem", "call-disk"]

    # Synthesized items have error flag and synthetic details
    assert healed[3].is_error is True
    assert healed[3].details["synthetic_healing"] == "mid_batch_fork_navigate"
    assert healed[4].is_error is True


def test_canonical_mid_batch_interrupted_by_new_user_turn() -> None:
    """Test that when a new user turn arrives before a batch completes, orphans are closed before user turn."""
    turns = [
        CanonicalMessageTurn(
            role=CanonicalMessageRole.ASSISTANT,
            content="Calling tools",
            tool_calls=(
                CanonicalToolCallDescriptor(tool_call_id="call-1", tool_name="t1"),
                CanonicalToolCallDescriptor(tool_call_id="call-2", tool_name="t2"),
            ),
        ),
        # Only call-1 answered
        CanonicalMessageTurn(role=CanonicalMessageRole.TOOL, tool_call_id="call-1", content="res1"),
        # User interrupts with new prompt
        CanonicalMessageTurn(role=CanonicalMessageRole.USER, content="Stop, do something else"),
    ]

    healed, metrics = heal_orphaned_tool_calls_canonical(turns)
    assert metrics.synthesized_count == 1
    assert metrics.synthesized_call_ids == ("call-2",)

    # Invariant: User message must come AFTER the synthesized tool result
    assert healed[0].role == CanonicalMessageRole.ASSISTANT
    assert healed[1].tool_call_id == "call-1"
    assert healed[2].tool_call_id == "call-2"
    assert healed[2].role == CanonicalMessageRole.TOOL
    assert healed[3].role == CanonicalMessageRole.USER
    assert healed[3].content == "Stop, do something else"


def test_transparent_held_system_message_sequencing() -> None:
    """Test that system messages landing mid-batch are held until all tool results settle."""
    turns = [
        CanonicalMessageTurn(
            role=CanonicalMessageRole.ASSISTANT,
            content="Working",
            tool_calls=(
                CanonicalToolCallDescriptor(tool_call_id="call-a", tool_name="ta"),
                CanonicalToolCallDescriptor(tool_call_id="call-b", tool_name="tb"),
            ),
        ),
        CanonicalMessageTurn(role=CanonicalMessageRole.TOOL, tool_call_id="call-a", content="ok"),
        # System message injected unexpectedly mid-batch
        CanonicalMessageTurn(role=CanonicalMessageRole.SYSTEM, content="System prompt notification"),
    ]

    healed, metrics = heal_orphaned_tool_calls_canonical(turns)
    assert metrics.synthesized_count == 1
    assert metrics.held_system_count == 1

    # Order must be: Assistant -> Tool(call-a) -> Tool(call-b synthetic) -> System
    roles = [h.role for h in healed]
    assert roles == [
        CanonicalMessageRole.ASSISTANT,
        CanonicalMessageRole.TOOL,
        CanonicalMessageRole.TOOL,
        CanonicalMessageRole.SYSTEM,
    ]
    assert healed[2].tool_call_id == "call-b"
    assert healed[3].content == "System prompt notification"


def test_all_calls_already_paired_is_noop() -> None:
    """Test that when all tool calls have matching results, no synthetic items are generated."""
    turns = [
        CanonicalMessageTurn(
            role=CanonicalMessageRole.ASSISTANT,
            content="Execute",
            tool_calls=(
                CanonicalToolCallDescriptor(tool_call_id="c1", tool_name="t1"),
            ),
        ),
        CanonicalMessageTurn(role=CanonicalMessageRole.TOOL, tool_call_id="c1", content="done"),
        CanonicalMessageTurn(role=CanonicalMessageRole.USER, content="Next"),
    ]

    healed, metrics = heal_orphaned_tool_calls_canonical(turns)
    assert metrics.synthesized_count == 0
    assert metrics.total_messages_in == metrics.total_messages_out == 3
    assert len(healed) == 3


def test_langchain_base_message_healing_parity() -> None:
    """Test LangChain BaseMessage stream healing across raw and parsed tool calls."""
    engine = OrphanedToolCallHealingTransform()

    # Assistant with both parsed tool_calls and additional_kwargs raw payload
    ai_msg = AIMessage(
        content="I will call tools",
        tool_calls=[
            {"id": "tc-standard", "name": "standard_tool", "args": {}},
        ],
        additional_kwargs={
            "tool_calls": [
                {
                    "id": "tc-raw",
                    "type": "function",
                    "function": {"name": "raw_tool", "arguments": "{}"},
                }
            ]
        },
    )
    # Only tc-standard has a ToolMessage
    tool_msg = ToolMessage(content="Standard success", tool_call_id="tc-standard")
    user_msg = HumanMessage(content="What is next?")

    messages = [ai_msg, tool_msg, user_msg]

    healed, metrics = engine.heal_langchain_messages(messages)
    assert metrics.synthesized_count == 1
    assert metrics.synthesized_call_ids == ("tc-raw",)
    assert len(healed) == 4

    # Structure check: AI -> Tool(tc-standard) -> Tool(tc-raw synthetic) -> Human
    assert isinstance(healed[0], AIMessage)
    assert isinstance(healed[1], ToolMessage) and healed[1].tool_call_id == "tc-standard"
    assert isinstance(healed[2], ToolMessage) and healed[2].tool_call_id == "tc-raw"
    assert healed[2].status == "error"
    assert isinstance(healed[3], HumanMessage)

    # Convenience function parity
    healed2, metrics2 = heal_orphaned_tool_calls_langchain(messages)
    assert metrics2.synthesized_count == 1
    assert len(healed2) == 4
