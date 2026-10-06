"""Comprehensive unit tests for Lean-Tail compression and reasoning trace stripping."""

from __future__ import annotations

from myrm_agent_harness.runtime.context.lean_tail_compression_engine import (
    LeanTailCompressionEngine,
)
from myrm_agent_harness.runtime.context.lean_tail_compression_types import (
    LeanTailConfig,
)
from myrm_agent_harness.runtime.context.reasoning_trace_stripper import (
    ReasoningTraceStripper,
)


def test_sub_512k_threshold_floor_at_75_percent() -> None:
    """Verify that models with context windows below 512K get their threshold floored at 75%."""
    config = LeanTailConfig(
        default_trigger_threshold=0.60,  # Lower than 75%
        sub_512k_threshold_floor=0.75,
    )
    engine = LeanTailCompressionEngine(config)

    # 128K context window -> sub-512k -> must floor at 75%
    budget_128k = engine.calculate_budget(128_000)
    assert budget_128k.is_floored_to_75_percent is True
    assert budget_128k.effective_threshold == 0.75
    assert budget_128k.trigger_tokens == 96_000

    # 1M context window -> large model -> uses default 60%
    budget_1m = engine.calculate_budget(1_000_000)
    assert budget_1m.is_floored_to_75_percent is False
    assert budget_1m.effective_threshold == 0.60
    assert budget_1m.trigger_tokens == 600_000


def test_fixed_tail_protection_bounds() -> None:
    """Verify tail protection tokens are bounded strictly within [floor, cap] (10k ~ 25k)."""
    config = LeanTailConfig(
        floor_tokens=10_000,
        cap_tokens=25_000,
    )
    engine = LeanTailCompressionEngine(config)

    # Very small window (50k tokens) -> 10% is 5,000, but floor is 10,000
    b_small = engine.calculate_budget(50_000)
    assert b_small.protected_tail_tokens == 10_000

    # Normal window (200k tokens) -> 10% is 20,000 -> in between [10k, 25k]
    b_mid = engine.calculate_budget(200_000)
    assert b_mid.protected_tail_tokens == 20_000

    # Giant window (2M tokens) -> 10% is 200,000, but cap is 25,000 -> prevents giant uncompressed tails
    b_giant = engine.calculate_budget(2_000_000)
    assert b_giant.protected_tail_tokens == 25_000


def test_reasoning_trace_stripper_recursive_and_unclosed() -> None:
    """Verify stripper removes nested tags, unclosed streaming tags, and all CoT markup."""
    stripper = ReasoningTraceStripper()

    # 1. Standard tags
    text_std = (
        "Hello world.\n"
        "<think>Let me calculate 2+2=4.</think>\n"
        "The answer is 4."
    )
    cleaned_std, chars_std, tags_std = stripper.strip_text(text_std)
    assert "<think>" not in cleaned_std
    assert "The answer is 4." in cleaned_std
    assert tags_std == 1
    assert chars_std > 20

    # 2. Nested tags: <think> inside <reasoning>
    text_nested = (
        "Start step.\n"
        "<reasoning>Outer step <think>Inner thought</think> concluding</reasoning>\n"
        "Step finished."
    )
    cleaned_nest, _, tags_nest = stripper.strip_text(text_nested)
    assert "<reasoning>" not in cleaned_nest
    assert "<think>" not in cleaned_nest
    assert "Step finished." in cleaned_nest
    assert tags_nest >= 2

    # 3. Unclosed streaming tag at end of message
    text_unclosed = (
        "Initial text.\n"
        "<thought>Interrupted mid-sentence during generation..."
    )
    cleaned_unclosed, _, tags_unclosed = stripper.strip_text(text_unclosed)
    assert "<thought>" not in cleaned_unclosed
    assert "Interrupted mid-sentence" not in cleaned_unclosed
    assert "Initial text." in cleaned_unclosed
    assert tags_unclosed == 1


def test_summarizer_prompt_soft_budget_guidance() -> None:
    """Verify summarizer receives soft budget guidance instead of wire-level truncation."""
    config = LeanTailConfig(
        target_summary_tokens=1_500,
        floor_tokens=100,
        cap_tokens=500,
        default_trigger_threshold=0.50,
    )
    engine = LeanTailCompressionEngine(config)

    # Create dummy messages exceeding 75% of 1000 tokens (750 tokens = ~3000 chars)
    messages = [
        {"role": "system", "content": "System prompt."},
        {"role": "user", "content": "Question 1 " + "A" * 1200},
        {"role": "assistant", "content": "<think>Deliberation</think>Answer 1 " + "B" * 1200},
        {"role": "user", "content": "Question 2 " + "C" * 1200},
        {"role": "assistant", "content": "Answer 2 recent " + "D" * 200},
    ]

    plan = engine.plan_compaction(messages, context_window_size=1000)
    assert plan.needs_compaction is True
    assert "Target summary volume: ~1500 tokens" in plan.summarizer_prompt_instructions
    assert "Do NOT emit <think>" in plan.summarizer_prompt_instructions
    assert plan.messages_to_compact_count >= 1
    assert plan.protected_tail_messages_count >= 1

    # Verify input messages sent to summarizer have thoughts stripped
    to_compact = messages[: plan.messages_to_compact_count]
    cleaned_for_summary = engine.prepare_summarizer_input(to_compact)
    for m in cleaned_for_summary:
        assert "<think>" not in m["content"]


def test_summarizer_output_stripping() -> None:
    """Verify that thoughts emitted BY the summarizer model are stripped before persistence."""
    engine = LeanTailCompressionEngine()

    raw_summary_from_model = (
        "<think>\n"
        "I need to summarize the user's progress on the database refactor.\n"
        "Key points: SQLite was selected, tables migrated.\n"
        "</think>\n"
        "Summary: User migrated database schema to SQLite and verified all tests."
    )

    clean_summary = engine.finalize_summary(raw_summary_from_model)
    assert "<think>" not in clean_summary
    assert "I need to summarize" not in clean_summary
    assert clean_summary.startswith("Summary: User migrated database schema")


def test_lean_tail_end_to_end_assembly() -> None:
    """Verify complete end-to-end flow: system msg + cleaned summary + protected tail."""
    engine = LeanTailCompressionEngine()

    system_msg = {"role": "system", "content": "You are a professional software architect."}
    raw_summary = (
        "<thought>Refining summary</thought>"
        "Phase 1 completed successfully with all unit tests passing."
    )
    tail_msgs = [
        {"role": "user", "content": "What is the next task?"},
        {"role": "assistant", "content": "Next task is implementing lean-tail compression."},
    ]

    assembled = engine.assemble_compacted_messages(system_msg, raw_summary, tail_msgs)
    assert len(assembled) == 4
    assert assembled[0]["role"] == "system"
    assert "<compacted_history_summary>" in assembled[1]["content"]
    assert "<thought>" not in assembled[1]["content"]
    assert "Phase 1 completed successfully" in assembled[1]["content"]
    assert assembled[2]["content"] == "What is the next task?"
    assert assembled[3]["content"] == "Next task is implementing lean-tail compression."
