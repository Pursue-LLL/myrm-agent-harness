import pytest

from myrm_agent_harness.agent.streaming.reasoning_scrubber import (
    THINKING_TAG_NAMES,
    ReasoningScrubber,
)
from myrm_agent_harness.agent.streaming.types import AgentEventType


def test_reasoning_scrubber_basic():
    scrubber = ReasoningScrubber()
    events = scrubber.process("hello world")
    events.extend(scrubber.flush())
    assert len(events) == 1
    assert events[0] == (AgentEventType.MESSAGE, "hello world")


def test_reasoning_scrubber_single_chunk():
    scrubber = ReasoningScrubber()
    chunk = "start <think>thinking process</think> end"
    events = scrubber.process(chunk)
    events.extend(scrubber.flush())

    assert events == [
        (AgentEventType.MESSAGE, "start "),
        (AgentEventType.REASONING, "thinking process"),
        (AgentEventType.MESSAGE, " end"),
    ]


def test_reasoning_scrubber_split_start_tag():
    scrubber = ReasoningScrubber()
    events = scrubber.process("start <thi")
    assert events == [(AgentEventType.MESSAGE, "start ")]
    events.extend(scrubber.process("nk>thinking"))
    events.extend(scrubber.flush())
    assert events[1] == (AgentEventType.REASONING, "thinking")


def test_reasoning_scrubber_split_end_tag():
    scrubber = ReasoningScrubber()
    events = scrubber.process("<think>thinking</thi")
    assert events == [(AgentEventType.REASONING, "thinking")]
    events.extend(scrubber.process("nk> end"))
    events.extend(scrubber.flush())
    assert events[1] == (AgentEventType.MESSAGE, " end")


def test_reasoning_scrubber_multiple_blocks():
    scrubber = ReasoningScrubber()
    chunk = "<think>first</think> middle <thought>second</thought> end"
    events = scrubber.process(chunk)
    events.extend(scrubber.flush())
    assert events == [
        (AgentEventType.REASONING, "first"),
        (AgentEventType.MESSAGE, " middle "),
        (AgentEventType.REASONING, "second"),
        (AgentEventType.MESSAGE, " end"),
    ]


def test_reasoning_scrubber_unclosed_block():
    scrubber = ReasoningScrubber()
    events = scrubber.process("start <think>thinking")
    events.extend(scrubber.flush())
    assert events == [
        (AgentEventType.MESSAGE, "start "),
        (AgentEventType.REASONING, "thinking"),
    ]


@pytest.mark.parametrize("tag_name", THINKING_TAG_NAMES)
def test_reasoning_scrubber_all_tag_names(tag_name: str):
    """Every tag in THINKING_TAG_NAMES is intercepted by ReasoningScrubber."""
    scrubber = ReasoningScrubber()
    chunk = f"before <{tag_name}>hidden</{tag_name}> after"
    events = scrubber.process(chunk)
    events.extend(scrubber.flush())
    assert events == [
        (AgentEventType.MESSAGE, "before "),
        (AgentEventType.REASONING, "hidden"),
        (AgentEventType.MESSAGE, " after"),
    ]


def test_reasoning_scrubber_flush_empty_buffer():
    """flush() on empty buffer returns empty list."""
    scrubber = ReasoningScrubber()
    assert scrubber.flush() == []


def test_reasoning_scrubber_flush_non_thinking_buffer():
    """flush() with pending non-thinking text emits MESSAGE."""
    scrubber = ReasoningScrubber()
    scrubber.process("start <thi")
    events = scrubber.flush()
    assert len(events) == 1
    assert events[0][0] == AgentEventType.MESSAGE


def test_thinking_tag_names_shared_constant():
    """THINKING_TAG_NAMES contains the canonical set of all supported tag names."""
    assert "think" in THINKING_TAG_NAMES
    assert "thinking" in THINKING_TAG_NAMES
    assert "thought" in THINKING_TAG_NAMES
    assert "antthinking" in THINKING_TAG_NAMES
    assert "reasoning" in THINKING_TAG_NAMES
    assert "REASONING_SCRATCHPAD" in THINKING_TAG_NAMES
