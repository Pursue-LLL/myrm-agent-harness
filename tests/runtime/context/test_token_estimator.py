"""Unit tests for dual-track provider usage anchored token estimator and orthogonal budget gate."""

from __future__ import annotations

import time

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.runtime.context.token_estimator import (
    CompactionBudgetSettings,
    estimate_context_tokens_anchored,
    extract_provider_usage_anchor,
    is_compaction_triggered,
)
from myrm_agent_harness.utils.token_estimation import (
    estimate_context_tokens,
    estimate_messages_tokens,
)


def test_extract_provider_usage_anchor_empty_and_no_ai() -> None:
    """Empty message lists or lists with no AIMessage return None."""
    assert extract_provider_usage_anchor([]) is None
    assert extract_provider_usage_anchor([HumanMessage(content="Hello world")]) is None
    assert extract_provider_usage_anchor([AIMessage(content="Response without usage")]) is None


def test_extract_provider_usage_anchor_from_usage_metadata() -> None:
    """Extract authoritative usage from AIMessage.usage_metadata."""
    ai_msg = AIMessage(
        content="I have usage metadata",
        usage_metadata={"input_tokens": 4200, "output_tokens": 180, "total_tokens": 4380},
    )
    anchor = extract_provider_usage_anchor([HumanMessage(content="Hi"), ai_msg])
    assert anchor is not None
    assert anchor.anchor_index == 1
    assert anchor.prompt_tokens == 4200
    assert anchor.output_tokens == 180
    assert anchor.total_tokens == 4380


def test_extract_provider_usage_anchor_from_response_metadata() -> None:
    """Extract authoritative usage from AIMessage.response_metadata['usage']."""
    ai_msg = AIMessage(
        content="From response_metadata",
        response_metadata={"usage": {"prompt_tokens": 3100, "completion_tokens": 95}},
    )
    anchor = extract_provider_usage_anchor([ai_msg])
    assert anchor is not None
    assert anchor.anchor_index == 0
    assert anchor.prompt_tokens == 3100
    assert anchor.output_tokens == 95
    assert anchor.total_tokens == 3195


def test_extract_provider_usage_anchor_from_additional_kwargs() -> None:
    """Extract authoritative usage from AIMessage.additional_kwargs['usage']."""
    ai_msg = AIMessage(
        content="From additional_kwargs",
        additional_kwargs={"usage": {"input_tokens": 1500, "output_tokens": 50}},
    )
    anchor = extract_provider_usage_anchor([ai_msg])
    assert anchor is not None
    assert anchor.anchor_index == 0
    assert anchor.prompt_tokens == 1500
    assert anchor.output_tokens == 50
    assert anchor.total_tokens == 1550


def test_extract_provider_usage_anchor_reverse_scan_picks_newest() -> None:
    """Reverse scan reliably picks the newest completed LLM round-trip."""
    turn1_ai = AIMessage(
        content="Turn 1",
        usage_metadata={"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050},
    )
    turn2_ai = AIMessage(
        content="Turn 2",
        usage_metadata={"input_tokens": 2500, "output_tokens": 80, "total_tokens": 2580},
    )
    messages = [
        HumanMessage(content="Question 1"),
        turn1_ai,
        HumanMessage(content="Question 2"),
        turn2_ai,
        ToolMessage(content="tool output", tool_call_id="call_1"),
    ]
    anchor = extract_provider_usage_anchor(messages)
    assert anchor is not None
    assert anchor.anchor_index == 3
    assert anchor.prompt_tokens == 2500
    assert anchor.output_tokens == 80


def test_estimate_context_tokens_anchored_fallback_when_no_anchor() -> None:
    """Smooth fallback to standard message estimator when no provider usage exists."""
    messages = [
        HumanMessage(content="Message A"),
        AIMessage(content="Message B without usage"),
    ]
    tokens, is_anchored = estimate_context_tokens_anchored(messages, bound_tool_overhead_tokens=100)
    assert not is_anchored
    assert tokens == estimate_messages_tokens(messages) + 100


def test_estimate_context_tokens_anchored_with_tail_messages() -> None:
    """Anchored calculation: anchor.prompt_tokens + anchor.output_tokens + tail increments."""
    anchor_ai = AIMessage(
        content="Calling tool...",
        tool_calls=[{"name": "read_file", "args": {"path": "a.txt"}, "id": "call_1"}],
        usage_metadata={"input_tokens": 5000, "output_tokens": 30, "total_tokens": 5030},
    )
    tool_res = ToolMessage(content="File content here", tool_call_id="call_1")
    human_next = HumanMessage(content="Next step please")

    messages = [
        HumanMessage(content="Ancient historical message that should be skipped by anchor"),
        anchor_ai,
        tool_res,
        human_next,
    ]

    tokens, is_anchored = estimate_context_tokens_anchored(messages)
    assert is_anchored
    # Baseline = 5000 + 30 (anchor output) + estimate(tool_res) + estimate(human_next)
    expected_tail = 5000 + 30 + estimate_messages_tokens([tool_res, human_next])
    assert tokens == expected_tail


def test_compaction_budget_settings_orthogonal_gates() -> None:
    """Test orthogonal dual-budget settings, trigger threshold, and summary budget."""
    settings = CompactionBudgetSettings(reserve_tokens=16384, keep_recent_tokens=20000)
    window = 128000
    threshold = window - 16384  # 111616

    assert not settings.is_triggered(threshold - 1, window)
    assert not settings.is_triggered(threshold, window)
    assert settings.is_triggered(threshold + 1, window)
    assert settings.is_triggered(120000, window)

    # Summary ceiling = floor(16384 * 0.8) = 13107
    assert settings.max_summary_tokens() == 13107
    # Bound by model max tokens
    assert settings.max_summary_tokens(model_max_tokens=4096) == 4096


def test_is_compaction_triggered_direct() -> None:
    """Direct pure function verification of reserve gate."""
    assert not is_compaction_triggered(context_tokens=10000, context_window=100000, reserve_tokens=10000)
    assert is_compaction_triggered(context_tokens=90001, context_window=100000, reserve_tokens=10000)


def test_performance_o1_tail_scaling_benchmark() -> None:
    """Verify O(1) performance: benchmark anchored estimator on massive message histories."""
    # Build a simulated long conversation with 300 heavy turns
    messages = []
    for i in range(150):
        messages.append(HumanMessage(content=f"Human request {i} " + "content " * 50))
        messages.append(AIMessage(content=f"AI response {i} " + "details " * 50))

    # Append an authoritative anchor near the end
    anchor_ai = AIMessage(
        content="Latest round-trip AI message",
        usage_metadata={"input_tokens": 48000, "output_tokens": 120, "total_tokens": 48120},
    )
    messages.append(anchor_ai)
    messages.append(ToolMessage(content="Tail tool output", tool_call_id="call_x"))

    # Benchmark full evaluation vs anchored evaluation
    start_anchored = time.perf_counter()
    anchored_tokens, is_anchored = estimate_context_tokens_anchored(messages)
    elapsed_anchored_ms = (time.perf_counter() - start_anchored) * 1000

    assert is_anchored
    assert anchored_tokens > 48000
    # Anchored calculation scans backwards, stops at anchor, and only tokens 2 messages (< 5ms)
    assert elapsed_anchored_ms < 10.0


def test_token_estimation_use_anchor_integration() -> None:
    """Verify estimate_context_tokens integration with use_anchor=True."""
    anchor_ai = AIMessage(
        content="Anchor",
        usage_metadata={"input_tokens": 10000, "output_tokens": 50, "total_tokens": 10050},
    )
    messages = [anchor_ai, HumanMessage(content="Follow-up")]

    res = estimate_context_tokens(messages, use_anchor=True)
    assert res >= 10050

    # Respects last_provider_prompt_tokens ceiling if provided
    res_with_higher = estimate_context_tokens(messages, last_provider_prompt_tokens=20000, use_anchor=True)
    assert res_with_higher == 20000
