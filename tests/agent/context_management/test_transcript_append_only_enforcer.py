# ============================================================================
# Unit Tests: Transcript Append-Only Invariant Enforcer (Item 169)
# ============================================================================

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.transcript_enforcer import (
    TranscriptAppendOnlyInvariantEnforcer,
    ViolationKind,
)


def test_initial_turn_snapshot_commit_and_valid_append() -> None:
    """Test initial snapshot capture and subsequent clean append validation."""
    enforcer = TranscriptAppendOnlyInvariantEnforcer()

    # Turn 1
    t1_msgs = [
        SystemMessage(content="System instruction base."),
        HumanMessage(content="List project files."),
        AIMessage(content="Listing files now..."),
    ]
    snapshot1 = enforcer.commit_turn_snapshot(turn_index=1, messages=t1_msgs)

    assert snapshot1.turn_index == 1
    assert snapshot1.message_count == 3
    assert len(snapshot1.fingerprints) == 3
    assert len(snapshot1.aggregate_prefix_sha256) == 64

    # Turn 2: Append 2 new messages cleanly to tail
    t2_msgs = list(t1_msgs) + [
        HumanMessage(content="Tool result: file1.py, file2.py"),
        AIMessage(content="Done reading files."),
    ]
    res2 = enforcer.validate_append_only(t2_msgs, snapshot1)

    assert res2.is_valid_append_only is True
    assert res2.appended_message_count == 2
    assert len(res2.violations) == 0
    assert "Append-only invariant strictly satisfied" in res2.diagnostic_message


def test_in_place_truncation_violation_detection() -> None:
    """Test detecting in-place message truncation that breaks prefix cache."""
    enforcer = TranscriptAppendOnlyInvariantEnforcer()

    long_output = "Long tool output: " + ("x" * 2000)
    t1_msgs = [
        SystemMessage(content="System base."),
        HumanMessage(content=long_output),
        AIMessage(content="Processing..."),
    ]
    snapshot1 = enforcer.commit_turn_snapshot(turn_index=1, messages=t1_msgs)

    # Bad pattern: middleware in-place truncates message #1 to save space
    truncated_msg = HumanMessage(content=long_output[:200])  # truncated
    bad_t2_msgs = [
        t1_msgs[0],
        truncated_msg,
        t1_msgs[2],
        AIMessage(content="Next step."),
    ]

    res = enforcer.validate_append_only(bad_t2_msgs, snapshot1)
    assert res.is_valid_append_only is False
    assert len(res.violations) == 1
    v = res.violations[0]
    assert v.violation_kind == ViolationKind.MESSAGE_TRUNCATED
    assert v.message_index == 1
    assert "In-place truncation destroys prefix KV-cache" in v.detail


def test_in_place_content_mutation_and_role_change_violation() -> None:
    """Test detecting in-place text mutation and role tampering in history."""
    enforcer = TranscriptAppendOnlyInvariantEnforcer()

    t1_msgs = [
        SystemMessage(content="Base rules."),
        HumanMessage(content="Initial prompt."),
    ]
    snapshot1 = enforcer.commit_turn_snapshot(turn_index=1, messages=t1_msgs)

    # 1. Mutate content of message #1
    mutated_msgs = [
        t1_msgs[0],
        HumanMessage(content="Altered prompt completely!"),
        AIMessage(content="Answer."),
    ]
    res_mut = enforcer.validate_append_only(mutated_msgs, snapshot1)
    assert res_mut.is_valid_append_only is False
    assert res_mut.violations[0].violation_kind == ViolationKind.CONTENT_MUTATED

    # 2. Tamper role of message #0 from SystemMessage to HumanMessage
    role_tampered_msgs = [
        HumanMessage(content="Base rules."),  # Role changed
        t1_msgs[1],
        AIMessage(content="Answer."),
    ]
    res_role = enforcer.validate_append_only(role_tampered_msgs, snapshot1)
    assert res_role.is_valid_append_only is False
    assert res_role.violations[0].violation_kind == ViolationKind.ROLE_CHANGED


def test_history_deletion_violation() -> None:
    """Test detecting historical messages missing from incoming sequence."""
    enforcer = TranscriptAppendOnlyInvariantEnforcer()

    t1_msgs = [
        SystemMessage(content="Sys"),
        HumanMessage(content="User 1"),
        AIMessage(content="AI 1"),
    ]
    snapshot1 = enforcer.commit_turn_snapshot(turn_index=1, messages=t1_msgs)

    # Incoming message list only has 2 messages (1 message deleted)
    truncated_seq = [t1_msgs[0], t1_msgs[1]]
    res = enforcer.validate_append_only(truncated_seq, snapshot1)

    assert res.is_valid_append_only is False
    assert len(res.violations) == 1
    assert res.violations[0].violation_kind == ViolationKind.MESSAGE_DELETED


def test_delta_correction_evolution_and_safeguard_repair() -> None:
    """Test delta correction message formatting and safeguard repair pipeline."""
    enforcer = TranscriptAppendOnlyInvariantEnforcer()

    # Delta correction formatting
    delta_msg = enforcer.create_delta_correction_message(
        target_message_index=2,
        correction_summary="Tool return code 0 but status failed.",
    )
    assert '<context_delta_evolution target_index="2">' in str(delta_msg.content)
    assert "Tool return code 0 but status failed." in str(delta_msg.content)

    # Safeguard repair on in-place mutation
    t1_msgs = [
        SystemMessage(content="System"),
        HumanMessage(content="Original long query"),
    ]
    snapshot1 = enforcer.commit_turn_snapshot(turn_index=1, messages=t1_msgs)

    # Bad incoming with mutated message #1
    bad_incoming = [
        t1_msgs[0],
        HumanMessage(content="Modified query"),
        AIMessage(content="Next turn response"),
    ]

    repaired_msgs, repair_res = enforcer.safeguard_or_repair_messages(
        incoming_messages=bad_incoming,
        last_snapshot=snapshot1,
        committed_baseline_messages=t1_msgs,
    )

    # History prefix is restored to pristine baseline to save KV cache!
    assert repair_res.is_valid_append_only is True
    assert repaired_msgs[0].content == "System"
    assert repaired_msgs[1].content == "Original long query"
    # Appended response is preserved at tail
    assert repaired_msgs[2].content == "Next turn response"
    # Delta note appended at very end
    assert "<context_delta_evolution" in str(repaired_msgs[3].content)
