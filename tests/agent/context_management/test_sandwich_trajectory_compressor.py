"""Unit tests for SandwichTrajectoryCompressor."""

import pytest

from myrm_agent_harness.agent.context_management.sandwich_trajectory import (
    SandwichTrajectoryCompressor,
    TrajectoryCompressionConfig,
)


def _build_trajectory_conversation(num_turns: int, tool_chars: int = 100) -> list[dict[str, str]]:
    """Helper to assemble multi-turn conversation with system, user, assistant, and tool steps."""
    messages: list[dict[str, str]] = [
        {"role": "system", "content": "SYSTEM: Maintain strict PEP8 and clean architecture."}
    ]
    for i in range(num_turns):
        messages.append({
            "role": "user",
            "content": f"Turn {i} prompt: Detailed instructions for subtask {i}.",
        })
        messages.append({
            "role": "assistant",
            "content": f"Turn {i} assistant: Investigating module at path/to/file_{i}.py.",
        })
        messages.append({
            "role": "tool",
            "content": f"Tool {i} output: " + ("x" * tool_chars),
        })
    return messages


def test_two_end_anchor_guard_and_middle_progress_summary() -> None:
    """Verify head (initial goal) and tail (recent error/actions) are 100% preserved verbatim."""
    config = TrajectoryCompressionConfig(
        target_max_tokens=400,  # Force Stage 2 summary compression
        head_protect_turns=1,
        tail_protect_turns=2,
    )
    compressor = SandwichTrajectoryCompressor(config=config)
    messages = _build_trajectory_conversation(num_turns=6, tool_chars=400)

    # Initial head intent and final tail error context
    head_user_content = messages[1]["content"]
    tail_last_tool_content = messages[-1]["content"]

    reconstructed, result = compressor.compress_trajectory(messages)

    assert result.is_compressed is True
    assert result.summary_inserted is True
    assert result.reclaimed_tokens > 0

    # Two-End Anchor Guard assertions:
    # 1. System instruction must be at index 0
    assert reconstructed[0]["role"] == "system"
    assert "strict PEP8" in reconstructed[0]["content"]

    # 2. First human prompt must be preserved exactly
    assert reconstructed[1]["content"] == head_user_content

    # 3. Last tool message must be preserved exactly
    assert reconstructed[-1]["content"] == tail_last_tool_content

    # 4. Middle zone must be replaced by exactly one progress summary message
    summary_messages = [
        m for m in reconstructed if "[TRAJECTORY PROGRESS SUMMARY]" in m.get("content", "")
    ]
    assert len(summary_messages) == 1
    assert "Prior intermediate trajectory" in summary_messages[0]["content"]


def test_stage1_elastic_tool_output_truncation() -> None:
    """Verify Stage 1 truncates oversized tool logs when sufficient to satisfy budget."""
    config = TrajectoryCompressionConfig(
        target_max_tokens=2000,  # High enough that truncating middle tools brings it under target (1870 < 2000 < 2670)
        head_protect_turns=1,
        tail_protect_turns=2,
        max_tool_output_chars_in_middle=300,
    )
    compressor = SandwichTrajectoryCompressor(config=config)
    # Middle tools are 2,000 chars each
    messages = _build_trajectory_conversation(num_turns=5, tool_chars=2000)

    reconstructed, result = compressor.compress_trajectory(messages)

    assert result.is_compressed is True
    # In Stage 1, summary is not inserted because tool truncation alone sufficed
    assert result.summary_inserted is False
    assert result.reclaimed_tokens > 0

    # Middle tool output must contain truncation notice
    middle_tool_msgs = [
        m for m in reconstructed
        if m.get("role") == "tool" and "trimmed to fit budget" in m.get("content", "")
    ]
    assert len(middle_tool_msgs) > 0


def test_passthrough_when_under_budget() -> None:
    """Verify messages remain completely untouched when under token budget."""
    config = TrajectoryCompressionConfig(
        target_max_tokens=50000,
        head_protect_turns=1,
        tail_protect_turns=2,
    )
    compressor = SandwichTrajectoryCompressor(config=config)
    messages = _build_trajectory_conversation(num_turns=4, tool_chars=50)

    reconstructed, result = compressor.compress_trajectory(messages)

    assert result.is_compressed is False
    assert result.reclaimed_tokens == 0
    assert reconstructed == messages


def test_short_session_boundary_handling() -> None:
    """Verify conversation with turns <= head + tail passes through safely."""
    config = TrajectoryCompressionConfig(
        target_max_tokens=100,
        head_protect_turns=2,
        tail_protect_turns=2,
    )
    compressor = SandwichTrajectoryCompressor(config=config)
    # Only 3 turns (less than 2 + 2 = 4)
    messages = _build_trajectory_conversation(num_turns=3, tool_chars=200)

    partition = compressor.partition_sandwich(messages)
    assert len(partition.middle_messages) == 0

    reconstructed, result = compressor.compress_trajectory(messages)
    assert result.is_compressed is False
    assert reconstructed == messages
