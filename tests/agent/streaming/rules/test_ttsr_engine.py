"""Unit and integration tests for Time-Traveling Stream Rules (TTSR) engine.

Validates sliding-window cross-chunk matching, PartialJsonUnescaper resilience,
repeat_gap quiet cooldowns, bounded retry breakers, and compaction immunity.
"""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent.context_management.strategies.compactor.selective_eviction import (
    evict_messages_by_marks,
)
from myrm_agent_harness.agent.context_management.working_memory.marks import (
    WorkingMemoryMark,
    has_message_marks,
    is_eviction_immune,
)
from myrm_agent_harness.agent.streaming.rules.coordinator import TtsrCoordinator
from myrm_agent_harness.agent.streaming.rules.matcher import (
    PartialJsonUnescaper,
    TtsrMatcher,
)
from myrm_agent_harness.agent.streaming.rules.types import StreamRule
from myrm_agent_harness.core.events.types import AgentEventType


def test_partial_json_unescaper_across_chunk_boundaries() -> None:
    """Validate JSON escape sequences split across chunk boundaries are reconstructed."""
    unescaper = PartialJsonUnescaper()

    # Split \" across chunk 1 and chunk 2
    chunk1 = '{"cmd": \\'
    chunk2 = '"rm -rf /"}'

    out1 = unescaper.unescape_chunk(chunk1)
    out2 = unescaper.unescape_chunk(chunk2)

    assert out1 == '{"cmd": '
    assert out2 == '"rm -rf /"}'
    assert out1 + out2 == '{"cmd": "rm -rf /"}'


def test_sliding_window_cross_chunk_regex_matching() -> None:
    """Ensure regex pattern split across multiple consecutive tokens is detected."""
    rule = StreamRule(
        rule_id="ban_rm_rf",
        name="Ban Destructive Rm",
        pattern=re.compile(r"rm\s+-rf\s+[/~]"),
        target="assistant",
        reminder="Destructive rm commands are prohibited.",
    )
    matcher = TtsrMatcher(window_size=64)

    # Token flow split: "r" -> "m -" -> "rf /"
    res1 = matcher.feed_and_match([rule], "assistant", "echo safe; r", turn=1)
    assert res1 is None

    res2 = matcher.feed_and_match([rule], "assistant", "m -", turn=1)
    assert res2 is None

    res3 = matcher.feed_and_match([rule], "assistant", "rf /tmp/root", turn=1)
    assert res3 is not None
    assert res3.rule.rule_id == "ban_rm_rf"
    assert "rm -rf /" in res3.matched_text


def test_tool_args_unescaped_matching() -> None:
    """Ensure tool_args channel receives automatic unescaping before pattern evaluation."""
    rule = StreamRule(
        rule_id="ban_leak_key",
        name="Ban Secret Leak",
        pattern=re.compile(r"sk-[a-zA-Z0-9]{12}"),
        target="tool_args",
        reminder="API keys must never be passed to tools.",
    )
    matcher = TtsrMatcher(window_size=128)

    # JSON escaped key inside string: \"sk-1234567890ab\"
    chunk = '{\\"key\\": \\"sk-1234567890ab\\"}'
    res = matcher.feed_and_match([rule], "tool_args", chunk, turn=1)
    assert res is not None
    assert res.rule.rule_id == "ban_leak_key"
    assert res.matched_text == "sk-1234567890ab"


def test_repeat_gap_cooldown_behavior() -> None:
    """Verify repeat_gap prevents excessive noise when model re-encounters condition."""
    rule = StreamRule(
        rule_id="format_guard",
        name="Format Guard",
        pattern=re.compile(r"```unformatted"),
        target="assistant",
        reminder="Please format using standard markdown.",
        repeat_gap=5,
    )
    coordinator = TtsrCoordinator(rules=[rule])

    # Turn 1: trigger rule
    m1 = coordinator.inspect_chunk("assistant", "```unformatted block", current_turn=1)
    assert m1 is not None
    assert coordinator.interrupt_requested is True

    coordinator.reset_interruption()

    # Turn 2: within repeat_gap (2 - 1 < 5) -> should be quiet/suppressed
    m2 = coordinator.inspect_chunk("assistant", "```unformatted block", current_turn=2)
    assert m2 is None
    assert coordinator.interrupt_requested is False

    # Turn 6: cooldown expired (6 - 1 >= 5) -> triggers again
    m6 = coordinator.inspect_chunk("assistant", "```unformatted block", current_turn=6)
    assert m6 is not None
    assert coordinator.interrupt_requested is True


def test_bounded_retry_circuit_breaker() -> None:
    """Verify max_retries limit enforces bounded execution without infinite loops."""
    rule = StreamRule(
        rule_id="stub_rule",
        name="Stub Rule",
        pattern=re.compile(r"BAD_TOKEN"),
        target="assistant",
        reminder="Retry reminder",
    )
    coordinator = TtsrCoordinator(rules=[rule], max_retries=2)

    # Attempt 1
    assert coordinator.record_retry() is True
    assert coordinator.retries_this_turn == 1

    # Attempt 2
    assert coordinator.record_retry() is True
    assert coordinator.retries_this_turn == 2

    # Attempt 3: exceeds max_retries=2 -> breaker trips
    assert coordinator.record_retry() is False
    assert coordinator.retries_this_turn == 3


def test_survives_compaction_immunity() -> None:
    """Verify TTSR injection message is immune from selective eviction and compaction."""
    rule = StreamRule(
        rule_id="no_leak",
        name="No Leak",
        pattern=re.compile(r"SECRET"),
        target="assistant",
        reminder="Secrets cannot be emitted.",
    )
    coordinator = TtsrCoordinator(rules=[rule])
    match = coordinator.inspect_chunk("assistant", "Found SECRET key", current_turn=1)
    assert match is not None

    msg = coordinator.create_interruption_message(match)

    # Verify memory mark & persistence metadata
    assert has_message_marks(msg, WorkingMemoryMark.TRAP_SHIELD.value)
    assert is_eviction_immune(msg)
    assert msg.additional_kwargs.get("retention") == "persistent"
    assert "<system-interrupt>" in str(msg.content)

    # Simulate selective eviction pipeline targeting transient marks
    transient_msg = HumanMessage(
        content="temporary reflection",
        additional_kwargs={"marks": [WorkingMemoryMark.HINT.value]},
    )
    history = [transient_msg, msg, AIMessage(content="subsequent reply")]

    retained, stats = evict_messages_by_marks(history)

    # Transient message evicted, TTSR interruption message preserved
    assert transient_msg not in retained
    assert msg in retained
    assert stats.evicted_count == 1


def test_agent_event_type_contract() -> None:
    """Verify TTSR_TRIGGERED event exists in standard AgentEventType enumeration."""
    assert hasattr(AgentEventType, "TTSR_TRIGGERED")
    assert AgentEventType.TTSR_TRIGGERED.value == "ttsr_triggered"
