"""Unit tests for MicroCompactorEngine and Amortized Turn Context Reclamation."""

import pytest

from myrm_agent_harness.agent.context_management.micro_compaction import (
    ExchangeBlock,
    MicroCompactionConfig,
    MicroCompactorEngine,
)


def _build_multi_turn_conversation(num_turns: int) -> list[dict[str, str]]:
    """Helper to generate multi-turn conversation with user, assistant, and tool messages."""
    messages: list[dict[str, str]] = [
        {"role": "system", "content": "You are a senior full-stack architect."}
    ]
    for i in range(num_turns):
        messages.append({
            "role": "user",
            "content": f"User Turn {i}: Specific prompt requirement and strict constraints for step {i}.",
        })
        messages.append({
            "role": "assistant",
            "content": f"Assistant Turn {i}: Elaborate explanation of strategy for step {i}.",
        })
        messages.append({
            "role": "tool",
            "content": f"Tool Turn {i} result: Output logs for step {i} containing 500 lines of data.",
        })
    return messages


def test_user_messages_verbatim_preservation_and_single_summary_tag() -> None:
    """Verify that user prompts are 100% preserved verbatim and single running summary tag is injected."""
    config = MicroCompactionConfig(
        head_protected_turns=1,
        tail_protected_turns=2,
        compact_every_n_turns=1,
    )
    engine = MicroCompactorEngine(config=config)
    session_id = "sess-micro-001"
    messages = _build_multi_turn_conversation(num_turns=5)

    original_user_prompts = [m["content"] for m in messages if m["role"] == "user"]
    assert len(original_user_prompts) == 5

    # Trigger micro-compaction at turn 4
    compacted_messages, result = engine.compact_turn_instalment(
        session_id=session_id,
        current_turn_index=4,
        messages=messages,
    )

    assert result.is_compacted is True
    assert result.absorbed_exchange_id == "exchange-turn-1"
    assert result.reclaimed_chars > 0

    # User messages must be 100% verbatim preserved
    compacted_user_prompts = [m["content"] for m in compacted_messages if m["role"] == "user"]
    assert compacted_user_prompts == original_user_prompts

    # Exactly one running summary marker should exist in the entire transcript
    summary_markers = [
        m for m in compacted_messages
        if "<running_context_summary>" in m.get("content", "")
    ]
    assert len(summary_markers) == 1
    assert "Assistant executed" in summary_markers[0]["content"]


def test_three_zone_boundary_and_amortized_turn_folding() -> None:
    """Verify head and tail protection zones and incremental per-turn folding."""
    config = MicroCompactionConfig(
        head_protected_turns=1,
        tail_protected_turns=2,
        compact_every_n_turns=1,
    )
    engine = MicroCompactorEngine(config=config)
    session_id = "sess-micro-002"
    messages = _build_multi_turn_conversation(num_turns=5)

    # First instalment: absorbs turn 1 (middle zone begins at turn 1)
    msgs_1, res_1 = engine.compact_turn_instalment(
        session_id=session_id,
        current_turn_index=4,
        messages=messages,
    )
    assert res_1.is_compacted is True
    assert res_1.running_summary.absorbed_exchanges_count == 1
    assert res_1.running_summary.last_absorbed_turn_index == 1

    # Second instalment: absorbs turn 2
    msgs_2, res_2 = engine.compact_turn_instalment(
        session_id=session_id,
        current_turn_index=4,
        messages=msgs_1,
    )
    assert res_2.is_compacted is True
    assert res_2.running_summary.absorbed_exchanges_count == 2
    assert res_2.running_summary.last_absorbed_turn_index == 2

    # Third instalment: turn 3 is inside protected tail (5 total turns: tail is turn 3 and 4)
    msgs_3, res_3 = engine.compact_turn_instalment(
        session_id=session_id,
        current_turn_index=4,
        messages=msgs_2,
    )
    assert res_3.is_compacted is False
    assert "No eligible unabsorbed exchanges" in res_3.diagnostics


def test_defrag_threshold_state_machine() -> None:
    """Verify running summary defragmentation when exceeding token threshold."""
    config = MicroCompactionConfig(
        head_protected_turns=1,
        tail_protected_turns=1,
        max_running_summary_tokens=25,  # Very low threshold to trigger defrag (~100 chars)
    )
    engine = MicroCompactorEngine(config=config)
    session_id = "sess-micro-003"
    messages = _build_multi_turn_conversation(num_turns=6)

    # Custom summarizer generating verbose notes
    def verbose_summarizer(existing: str, ex: ExchangeBlock) -> str:
        note = f"Step {ex.turn_index}: Detailed extensive log note detailing actions taken and results."
        return f"{existing}\n{note}" if existing else note

    _, res_1 = engine.compact_turn_instalment(
        session_id=session_id,
        current_turn_index=5,
        messages=messages,
        custom_summarizer=verbose_summarizer,
    )
    _, res_2 = engine.compact_turn_instalment(
        session_id=session_id,
        current_turn_index=5,
        messages=messages,
        custom_summarizer=verbose_summarizer,
    )
    _, res_3 = engine.compact_turn_instalment(
        session_id=session_id,
        current_turn_index=5,
        messages=messages,
        custom_summarizer=verbose_summarizer,
    )

    summary_state = engine.get_running_summary(session_id)
    assert summary_state is not None
    assert summary_state.defrag_count >= 1
    assert "Defragged" in summary_state.summary_text


def test_cadence_governor_and_three_strike_failure_skip() -> None:
    """Verify cadence skip for prefix cache and 3-strike failure skip to prevent hang."""
    # Test cadence: compact only every 3 turns
    config = MicroCompactionConfig(
        head_protected_turns=1,
        tail_protected_turns=2,
        compact_every_n_turns=3,
        max_retries_per_exchange=3,
    )
    engine = MicroCompactorEngine(config=config)
    session_id = "sess-micro-004"
    messages = _build_multi_turn_conversation(num_turns=6)

    # Turn index 4 is not divisible by 3 -> skipped
    _, res_skipped = engine.compact_turn_instalment(
        session_id=session_id,
        current_turn_index=4,
        messages=messages,
    )
    assert res_skipped.is_compacted is False
    assert "Cadence threshold" in res_skipped.diagnostics

    # Now test 3-strike failure skip
    fail_engine = MicroCompactorEngine(
        config=MicroCompactionConfig(
            head_protected_turns=1,
            tail_protected_turns=1,
            compact_every_n_turns=1,
            max_retries_per_exchange=3,
        )
    )

    def failing_summarizer(existing: str, ex: ExchangeBlock) -> str:
        if ex.turn_index == 1:
            raise RuntimeError("Temporary model rate-limit")
        return f"{existing}\nFolded turn {ex.turn_index}"

    # Fail 3 times on turn 1
    for _ in range(3):
        _, res = fail_engine.compact_turn_instalment(
            session_id=session_id,
            current_turn_index=4,
            messages=messages,
            custom_summarizer=failing_summarizer,
        )
        assert res.is_compacted is False

    # 4th call: turn 1 has 3 strikes -> engine advances cursor and absorbs turn 2!
    _, res_advanced = fail_engine.compact_turn_instalment(
        session_id=session_id,
        current_turn_index=4,
        messages=messages,
        custom_summarizer=failing_summarizer,
    )
    assert res_advanced.is_compacted is True
    assert res_advanced.absorbed_exchange_id == "exchange-turn-2"
