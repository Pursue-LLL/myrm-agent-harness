# [INPUT]: None
# [OUTPUT]: None
# [POS]: tests/agent/context_management/test_collapse_idle_suite.py

"""Comprehensive unit test suite for Headlong collapse-idle-before-cut stream windowing."""

import pytest

from myrm_agent_harness.agent.context_management.collapse_idle_window import (
    CollapseWindowConfig,
    HeadlongCollapseIdleBeforeCutSuite,
    StepType,
    collapse_then_cut_stream,
    format_time_duration,
    make_stream_step,
)


def test_collapse_before_cut_preserves_tail_actions() -> None:
    """Crucial bugfix test: 25 consecutive idles must collapse before cutting window,

    preventing premature eviction of preceding critical business actions.
    """
    suite = HeadlongCollapseIdleBeforeCutSuite(
        CollapseWindowConfig(target_window_size=20, raw_tail_bound=200)
    )

    steps = []
    base_time = 10000.0

    # 1. 10 critical actions occurred in the stream
    for i in range(10):
        steps.append(
            make_stream_step(
                step_id=f"act_{i}",
                run_id=f"run_act_{i}",
                step_type=StepType.ACTION,
                content=f"Important business operation #{i}",
                timestamp=base_time + (i * 60),
            )
        )

    # 2. Followed by 25 consecutive idle wakes during a quiet period
    idle_start = base_time + 1000.0
    for j in range(25):
        steps.append(
            make_stream_step(
                step_id=f"idle_{j}",
                run_id=f"run_idle_{j}",
                step_type=StepType.IDLE,
                content="idle",
                timestamp=idle_start + (j * 120),  # 2 mins between wakes
            )
        )

    # 3. Process stream with collapse-before-cut
    final_window, receipt = suite.process_stream(steps)

    # 4. Assertions:
    # 25 idles collapsed into 1 synthetic step; total effective steps = 10 actions + 1 collapsed idle = 11.
    # Because 11 <= 20 (window size), ALL 10 actions are fully preserved!
    assert len(final_window) == 11
    assert receipt.tail_actions_preserved_count == 10
    assert receipt.collapsed_idle_count == 24  # 25 steps collapsed by 24 into 1
    assert receipt.final_window_count == 11

    # The last step in the window is the collapsed idle
    last_step = final_window[-1]
    assert last_step.step_type == StepType.IDLE
    assert last_step.collapsed_count == 25
    assert "idle x25 over 48m" in last_step.content
    assert last_step.step_id == "idle_24"

    # All 10 preceding actions exist in the window in correct chronological order
    for idx, action_step in enumerate(final_window[:10]):
        assert action_step.step_type == StepType.ACTION
        assert action_step.step_id == f"act_{idx}"


def test_consecutive_idle_and_error_collapsing_with_duration() -> None:
    """Validate multi-step consecutive runs of idle and error collapsing with duration formatting."""
    t0 = 20000.0
    steps = [
        # 3 consecutive idles
        make_stream_step("i1", "r1", StepType.IDLE, "idle", timestamp=t0),
        make_stream_step("i2", "r2", StepType.IDLE, "idle", timestamp=t0 + 1800),
        make_stream_step("i3", "r3", StepType.IDLE, "idle", timestamp=t0 + 7200),  # 2 hours
        # An isolated action (must break the consecutive run)
        make_stream_step("a1", "r4", StepType.ACTION, "git commit", timestamp=t0 + 7300),
        # 4 consecutive errors
        make_stream_step("e1", "r5", StepType.ERROR, "fail", timestamp=t0 + 7400, return_code=1),
        make_stream_step("e2", "r6", StepType.ERROR, "fail", timestamp=t0 + 7500, return_code=1),
        make_stream_step("e3", "r7", StepType.ERROR, "fail", timestamp=t0 + 7600, return_code=1),
        make_stream_step("e4", "r8", StepType.ERROR, "fail", timestamp=t0 + 7700, return_code=137),
        # Single isolated idle
        make_stream_step("i4", "r9", StepType.IDLE, "idle", timestamp=t0 + 8000),
    ]

    final_window, receipt = collapse_then_cut_stream(steps, target_window_size=10)

    # 3 idles -> 1, 1 action -> 1, 4 errors -> 1, 1 isolated idle -> 1 = 4 total steps
    assert len(final_window) == 4

    # Idle group
    assert final_window[0].step_type == StepType.IDLE
    assert final_window[0].collapsed_count == 3
    assert "idle x3 over 2h0m" in final_window[0].content
    assert final_window[0].step_id == "i3"

    # Action untouched
    assert final_window[1].step_type == StepType.ACTION
    assert final_window[1].content == "git commit"
    assert final_window[1].collapsed_count == 1

    # Error group
    assert final_window[2].step_type == StepType.ERROR
    assert final_window[2].collapsed_count == 4
    assert "run failed x4 over 5m (rc=137)" in final_window[2].content
    assert final_window[2].return_code == 137

    # Isolated idle untouched
    assert final_window[3].step_type == StepType.IDLE
    assert final_window[3].collapsed_count == 1
    assert final_window[3].content == "idle"

    # Test time formatting helper
    assert format_time_duration(45) == "45s"
    assert format_time_duration(120) == "2m"
    assert format_time_duration(3665) == "1h1m"
    assert format_time_duration(90000) == "1d1h"


def test_redundant_step_pruning_and_reasoning_filter() -> None:
    """Verify pruning of redundant idle finals, superseded observations, and ephemeral reasoning."""
    suite = HeadlongCollapseIdleBeforeCutSuite()
    t = 30000.0

    steps = [
        # Run 1: Normal action and reasoning that should be stripped
        make_stream_step("s1", "run1", StepType.ACTION, "fetch papers", timestamp=t),
        make_stream_step("s2", "run1", StepType.REASONING, "thinking about papers...", timestamp=t + 1),
        make_stream_step("s3", "run1", StepType.OBSERVATION, "early milestone obs", timestamp=t + 2),
        make_stream_step("s4", "run1", StepType.OBSERVATION, "final duplicate obs", timestamp=t + 3),
        make_stream_step("s5", "run1", StepType.FINAL, "done fetching papers", timestamp=t + 4),
        # Run 2: Idle step followed by redundant final ("Idle - nothing to do")
        make_stream_step("s6", "run2", StepType.IDLE, "idle", timestamp=t + 10),
        make_stream_step("s7", "run2", StepType.FINAL, "Idle — nothing to do", timestamp=t + 11),
    ]

    final_window, receipt = suite.process_stream(steps)

    # Pruned steps:
    # 1. Reasoning step (s2) stripped
    # 2. Duplicated observation before final (s4) stripped; early milestone (s3) preserved
    # 3. Redundant final after idle (s7) stripped
    assert receipt.pruned_step_count == 3

    step_ids = [s.step_id for s in final_window]
    assert "s2" not in step_ids  # reasoning pruned
    assert "s4" not in step_ids  # nearest observation superseded by final pruned
    assert "s3" in step_ids      # early milestone observation preserved
    assert "s7" not in step_ids  # redundant final after idle pruned
    assert "s6" in step_ids      # idle retained


def test_raw_tail_bounding_and_zero_step_safety() -> None:
    """Validate boundary cases: large stream bounding, zero steps, and configuration guards."""
    suite = HeadlongCollapseIdleBeforeCutSuite(
        CollapseWindowConfig(target_window_size=10, raw_tail_bound=30)
    )

    # 1. Test empty stream
    empty_win, empty_receipt = suite.process_stream([])
    assert len(empty_win) == 0
    assert empty_receipt.raw_step_count == 0
    assert empty_receipt.final_window_count == 0

    # 2. Test large stream bounded by raw_tail_bound
    oversized_steps = [
        make_stream_step(f"step_{i}", f"run_{i}", StepType.ACTION, f"Action {i}", timestamp=float(i))
        for i in range(100)
    ]
    window, receipt = suite.process_stream(oversized_steps)

    # raw_step_count tracks all 100, bounded to 30, and window cut to 10
    assert receipt.raw_step_count == 100
    assert len(window) == 10
    assert window[0].step_id == "step_90"
    assert window[-1].step_id == "step_99"

    # 3. Configuration guards
    with pytest.raises(ValueError):
        CollapseWindowConfig(target_window_size=0)

    with pytest.raises(ValueError):
        CollapseWindowConfig(target_window_size=50, raw_tail_bound=20)
