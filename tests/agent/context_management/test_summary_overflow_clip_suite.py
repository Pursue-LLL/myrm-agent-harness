"""Comprehensive test suite for SummaryCallOverflowTailClipRetrySuite.

[INPUT]
- summary_overflow_clip package types, clipper, guard, and facade.

[OUTPUT]
- Verifies tail read_file 40-line head truncation, generic tool offload stub replacement,
  strictly monotonic token decrease validation, single-shot retry gating, and facade integration.

[POS]
- Sub-package: tests.agent.context_management
- Module: test_summary_overflow_clip_suite.py
"""

from typing import Dict, List

import pytest

from myrm_agent_harness.agent import (
    SummaryCallOverflowTailClipRetrySuite as RootExportedSuite,
)
from myrm_agent_harness.agent.context_management import (
    ClipStrategyKind,
    OverflowClipAction,
    OverflowClipOutcome,
    OverflowRetryGuard,
    SummaryCallOverflowTailClipRetrySuite,
    SummaryOverflowClipConfig,
    SummaryRetryVerdict,
    TailMessageClipper,
)


def test_tail_clipper_read_file_head_slice() -> None:
    """Verifies that large read_file outputs retain their top 40 lines with a snip notice."""
    config = SummaryOverflowClipConfig(read_file_max_head_lines=40)
    clipper = TailMessageClipper(config)

    # Generate a mock 100-line read_file tool output
    lines = [f"line_{i:03d}: def sample_function_{i}(): pass" for i in range(1, 101)]
    large_file_content = "\n".join(lines)

    messages: List[Dict[str, str]] = [
        {"role": "user", "content": "Please inspect the codebase."},
        {"role": "assistant", "content": "I will read the source file.", "tool_calls": "read_file"},
        {
            "role": "tool",
            "tool_name": "read_file",
            "content": large_file_content,
        },
    ]

    outcome = clipper.clip_trailing_tool_overflow(messages)

    assert outcome.total_messages_clipped == 1
    assert outcome.total_tokens_saved > 0
    assert outcome.is_strictly_reduced is True

    action = outcome.actions[0]
    assert action.strategy_applied == ClipStrategyKind.READ_FILE_HEAD_SLICE
    assert action.message_index == 2

    clipped_tool_content = outcome.clipped_messages[2]["content"]
    assert "line_001:" in clipped_tool_content
    assert "line_040:" in clipped_tool_content
    assert "line_041:" not in clipped_tool_content
    assert "[... head-sliced:" in outcome.clipped_messages[2]["content"]


def test_tail_clipper_generic_tool_offload_stub() -> None:
    """Verifies that non-read_file large tool results are replaced by generic storage stubs."""
    config = SummaryOverflowClipConfig(tool_stub_max_chars=120)
    clipper = TailMessageClipper(config)

    massive_bash_output = "stdout: trace logs running...\n" * 50  # ~1500 chars

    messages: List[Dict[str, str]] = [
        {"role": "user", "content": "Run tests."},
        {"role": "assistant", "content": "Running test suite...", "tool_calls": "bash"},
        {
            "role": "tool",
            "tool_name": "bash",
            "content": massive_bash_output,
        },
    ]

    outcome = clipper.clip_trailing_tool_overflow(messages)

    assert outcome.total_messages_clipped == 1
    assert outcome.total_tokens_saved > 0
    assert outcome.is_strictly_reduced is True

    action = outcome.actions[0]
    assert action.strategy_applied == ClipStrategyKind.OFFLOAD_STUB_REPLACE
    assert action.message_index == 2

    clipped_tool_content = outcome.clipped_messages[2]["content"]
    assert "[Tool 'bash' output offloaded to storage stub" in clipped_tool_content
    assert "Original size: " in clipped_tool_content


def test_retry_guard_monotonic_decreasing_and_single_shot() -> None:
    """Verifies strict monotonic reduction requirement and single-shot retry budget."""
    config = SummaryOverflowClipConfig(max_summary_retries=1)
    guard = OverflowRetryGuard(config)
    session_id = "session-overflow-001"

    mock_action = OverflowClipAction(
        message_index=2,
        tool_name="bash",
        strategy_applied=ClipStrategyKind.OFFLOAD_STUB_REPLACE,
        original_characters=2000,
        clipped_characters=100,
        estimated_saved_tokens=475,
    )
    mock_outcome = OverflowClipOutcome(
        total_messages_clipped=1,
        total_tokens_saved=475,
        is_strictly_reduced=True,
        actions=[mock_action],
        clipped_messages=[],
        diagnostic_summary="Saved 475 tokens",
    )

    # 1. Successful monotonic reduction -> Eligible for single retry
    verdict1 = guard.evaluate_retry_eligibility(session_id, mock_outcome)
    assert verdict1 == SummaryRetryVerdict.PERMITTED_ONCE
    assert guard.get_attempt_count(session_id) == 1

    # 2. Second retry attempt on same session_id -> Blocked by single-shot guard
    verdict2 = guard.evaluate_retry_eligibility(session_id, mock_outcome)
    assert verdict2 == SummaryRetryVerdict.RETRY_EXHAUSTED
    assert guard.get_attempt_count(session_id) == 1

    # 3. Reset resets session retry state
    guard.reset_session_retry_state(session_id)
    assert guard.get_attempt_count(session_id) == 0


def test_retry_guard_unreducible_overflow() -> None:
    """Verifies that when zero tokens are saved, retry is declared irreducible."""
    config = SummaryOverflowClipConfig()
    guard = OverflowRetryGuard(config)
    session_id = "session-overflow-002"

    empty_outcome = OverflowClipOutcome(
        total_messages_clipped=0,
        total_tokens_saved=0,
        is_strictly_reduced=False,
        actions=[],
        clipped_messages=[],
        diagnostic_summary="No messages clipped",
    )

    verdict = guard.evaluate_retry_eligibility(session_id, empty_outcome)
    assert verdict == SummaryRetryVerdict.IRREDUCIBLE_OVERFLOW
    assert guard.get_attempt_count(session_id) == 0


def test_summary_overflow_clip_suite_facade_end_to_end() -> None:
    """Verifies end-to-end integration via the facade class."""
    suite = SummaryCallOverflowTailClipRetrySuite()
    session_id = "test-e2e-summary-session"

    raw_file = "\n".join([f"code_statement_num_{i} = {i}" for i in range(120)])
    messages: List[Dict[str, str]] = [
        {"role": "user", "content": "Summarize operations."},
        {"role": "assistant", "content": "Examining operations."},
        {"role": "tool", "tool_name": "read_file", "content": raw_file},
        {"role": "tool", "tool_name": "curl", "content": "HTTP 200 OK\n" * 40},
    ]

    verdict, outcome = suite.handle_summary_context_overflow(session_id, messages)

    assert verdict == SummaryRetryVerdict.PERMITTED_ONCE
    assert outcome.total_messages_clipped == 2
    assert outcome.total_tokens_saved > 0
    assert outcome.is_strictly_reduced is True

    # Both tool outputs should be appropriately clipped
    assert len(outcome.clipped_messages) == 4
    assert "[... head-sliced:" in outcome.clipped_messages[2]["content"]
    assert "[Tool 'curl' output offloaded" in outcome.clipped_messages[3]["content"]

    # Verify attempt tracking & reset
    assert suite.get_retry_attempts(session_id) == 1
    suite.reset_session_retry_state(session_id)
    assert suite.get_retry_attempts(session_id) == 0


def test_root_and_package_exports() -> None:
    """Verifies that the suite is seamlessly exported at package and root levels."""
    assert RootExportedSuite is SummaryCallOverflowTailClipRetrySuite
    suite = RootExportedSuite()
    assert isinstance(suite, SummaryCallOverflowTailClipRetrySuite)
    assert suite.clipper is not None
    assert suite.guard is not None
