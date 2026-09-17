"""Unit tests for working memory marks metadata contract and inspection primitives."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from myrm_agent_harness.agent.context_management.working_memory.marks import (
    WorkingMemoryMark,
    get_message_marks,
    has_message_marks,
    is_eviction_immune,
    with_message_marks,
)


def test_working_memory_mark_enum_values():
    assert WorkingMemoryMark.HINT == "hint"
    assert WorkingMemoryMark.SCRATCHPAD == "scratchpad"
    assert WorkingMemoryMark.TOOL_RAW_OUTPUT == "tool_raw_output"
    assert WorkingMemoryMark.PINNED == "pinned"
    assert WorkingMemoryMark.TRAP_SHIELD == "trap_shield"


def test_empty_message_marks():
    msg = HumanMessage(content="hello")
    assert get_message_marks(msg) == set()
    assert not has_message_marks(msg, WorkingMemoryMark.HINT)
    assert not is_eviction_immune(msg)


def test_with_message_marks_and_retrieval():
    msg = HumanMessage(content="test")
    with_message_marks(msg, WorkingMemoryMark.HINT, "custom_tag")

    marks = get_message_marks(msg)
    assert "hint" in marks
    assert "custom_tag" in marks
    assert has_message_marks(msg, WorkingMemoryMark.HINT)
    assert has_message_marks(msg, "custom_tag")
    assert not has_message_marks(msg, WorkingMemoryMark.PINNED)


def test_eviction_immunity_predicate():
    # Regular message is not immune
    msg1 = HumanMessage(content="normal")
    assert not is_eviction_immune(msg1)

    # Hint is not immune
    msg2 = HumanMessage(content="transient hint")
    with_message_marks(msg2, WorkingMemoryMark.HINT)
    assert not is_eviction_immune(msg2)

    # Pinned mark is immune
    msg3 = SystemMessage(content="strict instruction")
    with_message_marks(msg3, WorkingMemoryMark.PINNED)
    assert is_eviction_immune(msg3)

    # Trap shield mark is immune
    msg4 = AIMessage(content="avoid error")
    with_message_marks(msg4, WorkingMemoryMark.TRAP_SHIELD)
    assert is_eviction_immune(msg4)

    # String "pinned" or "keep" in marks is immune
    msg5 = HumanMessage(content="keep this")
    with_message_marks(msg5, "keep")
    assert is_eviction_immune(msg5)
