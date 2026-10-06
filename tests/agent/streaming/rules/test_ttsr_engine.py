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
    assert "Offending fragment detected: SECRET" in str(msg.content)

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


def test_partial_json_unescaper_unicode() -> None:
    """Verify PartialJsonUnescaper decodes \\uXXXX characters streamingly and across chunk boundaries."""
    unescaper = PartialJsonUnescaper()

    # Standard contiguous unicode escape
    assert unescaper.unescape_chunk(r"cmd: \u0072\u006d -rf") == "cmd: rm -rf"
    unescaper.reset()

    # Chunk split exactly across \u and hex digits: "\u00" + "72" -> "r"
    part1 = unescaper.unescape_chunk(r'{"command": "\u00')
    part2 = unescaper.unescape_chunk(r'72\u006df"}')
    assert (part1 + part2) == '{"command": "rmf"}'
    unescaper.reset()

    # Non-hex character fallback gracefully preserves text
    assert unescaper.unescape_chunk(r"\u12xz") == r"\u12xz"
    unescaper.reset()


def test_ttsr_matcher_unicode_evasion_blocked() -> None:
    """Verify malicious unicode escaped tool_args cannot evade regex detection."""
    rule = StreamRule(
        rule_id="rule_block_rm_rf",
        name="block_rm_rf",
        pattern=re.compile(r"rm\s+-rf"),
        target="tool_args",
        action="abort_and_retry",
        reminder="Destructive rm detected.",
    )
    matcher = TtsrMatcher()

    # Model generates tool_args chunk containing \u0072\u006d -rf
    result = matcher.feed_and_match(
        rules=[rule],
        target="tool_args",
        chunk=r'{"cmd": "\u0072\u006d -rf /"}',
        turn=1,
    )
    assert result is not None
    assert result.rule.name == "block_rm_rf"
    assert "rm -rf" in result.matched_text


def test_ttsr_comprehensive_edge_cases_and_coverage() -> None:
    """Verify edge cases across unescaper, matcher, and coordinator for >=90% test coverage."""
    unescaper = PartialJsonUnescaper()

    # Empty chunk
    assert unescaper.unescape_chunk("") == ""

    # Common escape sequences: \", \\, \/, \n, \r, \t, and unrecognised escape \a
    escaped_text = r'quote: \" backslash: \\ slash: \/ nl: \n cr: \r tab: \t unrec: \a'
    unescaped = unescaper.unescape_chunk(escaped_text)
    assert unescaped == 'quote: " backslash: \\ slash: / nl: \n cr: \r tab: \t unrec: \\a'

    # Unicode invalid sequence followed by escape
    fallback_text = unescaper.unescape_chunk(r"\u12\n")
    assert r"\u12" in fallback_text
    assert "\n" in fallback_text

    # Matcher boundary and empty branches
    matcher = TtsrMatcher()
    rule_assistant = StreamRule(
        rule_id="assistant_only",
        name="Assistant Only",
        pattern=re.compile(r"FORBIDDEN"),
        target="assistant",
    )
    # Empty chunk or empty rules
    assert matcher.feed_and_match([], "assistant", "FORBIDDEN", 1) is None
    assert matcher.feed_and_match([rule_assistant], "assistant", "", 1) is None

    # Target mismatch: target is thinking, rule is assistant
    assert matcher.feed_and_match([rule_assistant], "thinking", "FORBIDDEN", 1) is None

    # Target match
    matched = matcher.feed_and_match([rule_assistant], "assistant", "FORBIDDEN text", 1)
    assert matched is not None
    assert matched.matched_text == "FORBIDDEN"

    # Reset matcher
    matcher.reset()
    assert matcher._buffers["assistant"] == ""

    # Coordinator edge properties and methods
    coordinator = TtsrCoordinator(rules=[rule_assistant])
    assert len(coordinator.rules) == 1
    assert coordinator.retries_this_turn == 0

    # Overwrite rule via register_rule
    updated_rule = StreamRule(
        rule_id="assistant_only",
        name="Assistant Only Updated",
        pattern=re.compile(r"UPDATED_FORBIDDEN"),
        target="assistant",
    )
    coordinator.register_rule(updated_rule)
    assert len(coordinator.rules) == 1
    assert coordinator.rules[0].name == "Assistant Only Updated"

    # Interrupt requested triggers immediate early return
    coordinator._interrupt_requested = True
    assert coordinator.inspect_chunk("assistant", "UPDATED_FORBIDDEN", 1) is None
    coordinator.reset_interruption()
    assert coordinator.interrupt_requested is False

    # Match and reset turn
    matched = coordinator.inspect_chunk("assistant", "UPDATED_FORBIDDEN", 1)
    assert matched is not None
    assert coordinator.last_match is not None
    coordinator.record_retry()
    assert coordinator.retries_this_turn == 1
    coordinator.reset_turn()
    assert coordinator.retries_this_turn == 0
    assert coordinator.interrupt_requested is False


def test_same_turn_retry_keeps_triggered_rules_active_and_enforces_breaker() -> None:
    """Verify that same-turn retries do NOT get suppressed by repeat_gap cooldown,

    ensuring secondary violations are strictly intercepted and max_retries limit is enforced.
    """
    rule = StreamRule(
        rule_id="ban_catastrophic_rm",
        name="Ban Rm",
        pattern=re.compile(r"rm\s+-rf\s+/"),
        target="assistant",
        repeat_gap=10,  # 10 turns cooldown across different turns
        action="abort_and_retry",
    )
    coordinator = TtsrCoordinator(rules=[rule], max_retries=2)

    # Turn 1, Attempt 1: First violation
    m1 = coordinator.inspect_chunk("assistant", "rm -rf /", current_turn=1)
    assert m1 is not None
    assert m1.rule.rule_id == "ban_catastrophic_rm"
    assert coordinator.interrupt_requested is True

    # System handles retry: records retry #1 and resets interruption flag
    can_retry_1 = coordinator.record_retry()
    assert can_retry_1 is True
    assert coordinator.retries_this_turn == 1
    coordinator.reset_interruption()
    assert coordinator.interrupt_requested is False

    # Turn 1, Attempt 2: Model stubbornly repeats same violation on retry!
    # MUST be strictly intercepted rather than silenced by repeat_gap
    m2 = coordinator.inspect_chunk("assistant", "rm -rf /", current_turn=1)
    assert m2 is not None, "Secondary violation must NOT be bypassed on same-turn retry!"
    assert m2.rule.rule_id == "ban_catastrophic_rm"
    assert coordinator.interrupt_requested is True

    # System handles retry #2
    can_retry_2 = coordinator.record_retry()
    assert can_retry_2 is True
    assert coordinator.retries_this_turn == 2
    coordinator.reset_interruption()

    # System reaches breaker limit (max_retries=2)
    can_retry_3 = coordinator.record_retry()
    assert can_retry_3 is False, "Circuit breaker must trip when exceeding max_retries=2"
    assert coordinator.retries_this_turn == 3


def test_multi_channel_isolation_and_all_target_broadcast() -> None:
    """Verify channel buffers are isolated without cross-contamination,

    and broadcast target='all' safely feeds each channel and matches channel-specific rules.
    """
    rule_thinking = StreamRule(
        rule_id="guard_thinking",
        name="Thinking Guard",
        pattern=re.compile(r"FORBIDDEN_CHAIN"),
        target="thinking",
    )
    rule_tool = StreamRule(
        rule_id="guard_tool",
        name="Tool Guard",
        pattern=re.compile(r"SECRET_ARG"),
        target="tool_args",
    )
    rule_general = StreamRule(
        rule_id="guard_all",
        name="General Guard",
        pattern=re.compile(r"DANGEROUS_CMD"),
        target="all",
    )
    matcher = TtsrMatcher(window_size=64)

    # Feeding thinking does NOT contaminate tool_args
    res_think = matcher.feed_and_match([rule_thinking, rule_tool], "thinking", "FORBIDDEN_CHAIN", turn=1)
    assert res_think is not None
    assert res_think.rule.rule_id == "guard_thinking"

    # Feeding broadcast 'all' evaluates and triggers channel-specific rules
    matcher.reset()
    res_broadcast_tool = matcher.feed_and_match([rule_tool], "all", "SECRET_ARG", turn=1)
    assert res_broadcast_tool is not None
    assert res_broadcast_tool.rule.rule_id == "guard_tool"

    # Feeding broadcast 'all' triggers general rule
    matcher.reset()
    res_broadcast_gen = matcher.feed_and_match([rule_general], "all", "DANGEROUS_CMD", turn=1)
    assert res_broadcast_gen is not None
    assert res_broadcast_gen.rule.rule_id == "guard_all"





