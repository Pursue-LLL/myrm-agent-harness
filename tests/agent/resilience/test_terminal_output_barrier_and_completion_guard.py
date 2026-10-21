"""Unit tests for Terminal Output Barrier and Long Horizon Execution Completion Guard.

Verifies:
1. classify_terminal_output accurately distinguishes intermediate streaming from terminal exit codes.
2. Auto-yield and interactive input states generate appropriate continuation prompts.
3. Explicit daemon background processes are granted terminal check exemptions.
4. LongHorizonExecutionGuard blocks premature model completion when background jobs are running.
5. LongHorizonExecutionGuard releases barrier once deterministic exit signal is captured.
6. Guard continuation budget enforces deadlock prevention and timeout fallbacks.
7. Reset clears all tracked process states.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.resilience.long_horizon_guard_middleware import (
    LongHorizonExecutionGuard,
)
from myrm_agent_harness.agent.resilience.terminal_output_barrier import (
    ExecutionStage,
    classify_terminal_output,
)


def test_classify_terminal_output_structured_dict_running_vs_exited() -> None:
    # 1. Deterministic success exit code
    res_success = classify_terminal_output(
        "bash_code_execute_tool",
        {"command": "cargo build --release"},
        {"exit_code": 0, "output": "Finished release target"},
    )
    assert res_success.is_terminal
    assert res_success.stage == ExecutionStage.TERMINAL_SUCCESS
    assert res_success.exit_code == 0
    assert res_success.continuation_prompt is None

    # 2. Deterministic failure exit code
    res_fail = classify_terminal_output(
        "bash_code_execute_tool",
        {"command": "cargo test"},
        {"exit_code": 101, "output": "test failed"},
    )
    assert res_fail.is_terminal
    assert res_fail.stage == ExecutionStage.TERMINAL_FAILURE
    assert res_fail.exit_code == 101
    assert res_fail.continuation_prompt is None

    # 3. Active background task with PID and still_running=True
    res_running = classify_terminal_output(
        "bash_process_tool",
        {"action": "wait", "pid": 1234},
        {"pid": 1234, "still_running": True, "output": "compiling..."},
    )
    assert not res_running.is_terminal
    assert res_running.stage == ExecutionStage.INTERMEDIATE_STREAMING
    assert res_running.pid == 1234
    assert res_running.continuation_prompt is not None
    assert "still actively running in background" in res_running.continuation_prompt
    assert "pid=1234" in res_running.continuation_prompt

    # 4. Interactive stdin input pause
    res_input = classify_terminal_output(
        "bash_process_tool",
        {"action": "output", "pid": 5678},
        {
            "pid": 5678,
            "still_running": True,
            "waiting_for_input": True,
            "input_wait_hint": "Proceed with deployment? [y/N]",
        },
    )
    assert not res_input.is_terminal
    assert res_input.stage == ExecutionStage.INTERMEDIATE_STREAMING
    assert res_input.continuation_prompt is not None
    assert "submit_stdin" in res_input.continuation_prompt
    assert "Proceed with deployment? [y/N]" in res_input.continuation_prompt


def test_classify_terminal_output_text_auto_yield_and_progress() -> None:
    # 1. Text with auto-yield background indicator
    text_auto_yield = "Auto-yield: command still running in background, pid=8899\n[1/10] Starting batch..."
    res_yield = classify_terminal_output("bash_code_execute_tool", {}, text_auto_yield)
    assert not res_yield.is_terminal
    assert res_yield.stage == ExecutionStage.INTERMEDIATE_STREAMING
    assert res_yield.pid == 8899
    assert res_yield.continuation_prompt is not None
    assert "Auto-yield detected" in res_yield.continuation_prompt

    # 2. Text with intermediate compiling progress
    text_progress = "   Compiling serde v1.0.197\n   Compiling syn v2.0.48\n[ 24/150 ] Compiling tokio..."
    res_prog = classify_terminal_output("bash_code_execute_tool", {"pid": 7711}, text_progress)
    assert not res_prog.is_terminal
    assert res_prog.stage == ExecutionStage.INTERMEDIATE_STREAMING
    assert res_prog.continuation_prompt is not None
    assert "intermediate streaming progress" in res_prog.continuation_prompt

    # 3. Text with explicit exit code
    text_exit = "Compiling done.\nProcess exited with code 0\nAll 42 tests passed."
    res_exit = classify_terminal_output("bash_code_execute_tool", {}, text_exit)
    assert res_exit.is_terminal
    assert res_exit.stage == ExecutionStage.TERMINAL_SUCCESS
    assert res_exit.exit_code == 0

    # 4. Text with error status code
    text_err = "Cargo abort: linking failed\nProcess exited with status 1"
    res_err = classify_terminal_output("bash_code_execute_tool", {}, text_err)
    assert res_exit.is_terminal
    assert res_err.stage == ExecutionStage.TERMINAL_FAILURE
    assert res_err.exit_code == 1


def test_classify_terminal_output_daemon_process_exemption() -> None:
    res_daemon = classify_terminal_output(
        "bash_code_execute_tool",
        {"command": "npm run dev", "is_daemon": True, "pid": 9999},
        "Server listening on http://localhost:3000",
    )
    assert res_daemon.is_terminal
    assert res_daemon.stage == ExecutionStage.TERMINAL_SUCCESS
    assert "Daemon process explicitly detached" in res_daemon.reason


def test_guard_intercepts_premature_completion_on_streaming_task() -> None:
    guard = LongHorizonExecutionGuard(max_continuations=3)

    # Tool returns intermediate background running output
    guard.record_tool_result(
        "bash_code_execute_tool",
        {"command": "cargo build"},
        "Auto-yield: command still running in background, pid=1010",
    )
    assert len(guard.active_tasks) == 1
    assert "1010" in guard.active_tasks

    # Model attempts premature completion without tool calls
    decision = guard.evaluate_model_completion(has_tool_calls=False)
    assert decision.should_continue
    assert decision.instruction is not None
    assert "【Terminal Output Barrier】" in decision.instruction
    assert "PID=1010" in decision.instruction
    assert "1/3" in decision.instruction

    # If the model emits tool calls (e.g. calling wait), guard does not intervene
    decision_with_tool = guard.evaluate_model_completion(has_tool_calls=True)
    assert not decision_with_tool.should_continue
    assert decision_with_tool.instruction is None


def test_guard_allows_completion_when_process_reaches_terminal() -> None:
    guard = LongHorizonExecutionGuard()

    # Initial yield
    guard.record_tool_result(
        "bash_code_execute_tool",
        {"command": "long_job.sh"},
        "Auto-yield: command still running in background, pid=2020",
    )
    assert len(guard.active_tasks) == 1

    # Follow-up tool call captures terminal success
    guard.record_tool_result(
        "bash_process_tool",
        {"action": "wait", "pid": 2020},
        {"exit_code": 0, "output": "Job completed successfully"},
    )
    assert len(guard.active_tasks) == 0

    # Model attempts final answer after process exit
    decision = guard.evaluate_model_completion(has_tool_calls=False)
    assert not decision.should_continue
    assert decision.instruction is None
    assert "reached terminal state" in decision.reason


def test_guard_enforces_budget_and_prevents_deadlock() -> None:
    guard = LongHorizonExecutionGuard(max_continuations=2)

    guard.record_tool_result(
        "bash_code_execute_tool",
        {"command": "sleep 1000"},
        "Auto-yield: command still running in background, pid=3030",
    )

    # 1st continuation
    d1 = guard.evaluate_model_completion(has_tool_calls=False)
    assert d1.should_continue
    assert "1/2" in str(d1.instruction)

    # 2nd continuation
    d2 = guard.evaluate_model_completion(has_tool_calls=False)
    assert d2.should_continue
    assert "2/2" in str(d2.instruction)

    # 3rd attempt exceeds budget: barrier released to prevent deadlock
    d3 = guard.evaluate_model_completion(has_tool_calls=False)
    assert not d3.should_continue
    assert d3.instruction is None
    assert "Exceeded continuation budget" in d3.reason
    assert guard.active_tasks["3030"].stage == ExecutionStage.TERMINAL_TIMEOUT


def test_guard_reset_clears_active_tasks() -> None:
    guard = LongHorizonExecutionGuard()
    guard.record_tool_result(
        "bash_code_execute_tool",
        {"command": "test.sh"},
        "Auto-yield: command still running in background, pid=4040",
    )
    assert len(guard.active_tasks) == 1
    guard.reset()
    assert len(guard.active_tasks) == 0
    decision = guard.evaluate_model_completion(has_tool_calls=False)
    assert not decision.should_continue
