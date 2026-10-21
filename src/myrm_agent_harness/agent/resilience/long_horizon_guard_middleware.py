"""Long Horizon Execution Guard Middleware and Terminal Output Barrier Governor.

Intercepts the agent run-loop when a model attempts to terminate prematurely
without observing deterministic exit signals for long-running processes.
Enforces the 'continue until terminal task output' contract with configurable
continuation budgets to prevent deadlocks.

[INPUT]
- .terminal_output_barrier::(ExecutionStage, LongRunningTaskState, TerminalSnifferResult, classify_terminal_output)

[OUTPUT]
- ContinuationDecision: Directive indicating whether completion is allowed or continuation required
- LongHorizonExecutionGuard: Governor tracking active tasks and enforcing terminal barriers
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Mapping

from .terminal_output_barrier import (
    ExecutionStage,
    LongRunningTaskState,
    TerminalSnifferResult,
    classify_terminal_output,
)

logger = logging.getLogger(__name__)

_DEFAULT_MAX_CONTINUATIONS: int = 5


@dataclass(frozen=True, slots=True)
class ContinuationDecision:
    """Decision made by the Terminal Output Barrier when model attempts completion."""

    should_continue: bool
    instruction: str | None
    active_task: LongRunningTaskState | None
    reason: str


class LongHorizonExecutionGuard:
    """Manages active long-running process lifecycles and enforces terminal output barriers."""

    def __init__(self, max_continuations: int = _DEFAULT_MAX_CONTINUATIONS) -> None:
        self._max_continuations = max(1, max_continuations)
        self._active_tasks: dict[str, LongRunningTaskState] = {}

    @property
    def max_continuations(self) -> int:
        return self._max_continuations

    @property
    def active_tasks(self) -> Mapping[str, LongRunningTaskState]:
        return self._active_tasks

    def record_tool_result(
        self,
        tool_name: str,
        tool_input: Mapping[str, object],
        tool_output: object,
    ) -> TerminalSnifferResult:
        """Inspect a tool execution result and update long-running task tracking.

        Args:
            tool_name: Executed tool name.
            tool_input: Tool input mapping.
            tool_output: Tool return object or text.

        Returns:
            TerminalSnifferResult classification.
        """
        sniffer = classify_terminal_output(tool_name, tool_input, tool_output)
        task_key = str(sniffer.pid) if sniffer.pid is not None else tool_name

        if sniffer.stage == ExecutionStage.INTERMEDIATE_STREAMING:
            # Register or update ongoing background task
            existing = self._active_tasks.get(task_key)
            if existing is None:
                command = str(tool_input.get("command") or tool_input.get("cmd") or "")
                is_daemon = bool(tool_input.get("is_daemon") or tool_input.get("daemon"))
                self._active_tasks[task_key] = LongRunningTaskState(
                    task_id=task_key,
                    pid=sniffer.pid,
                    tool_name=tool_name,
                    command=command if command else None,
                    stage=ExecutionStage.INTERMEDIATE_STREAMING,
                    continuation_count=0,
                    is_daemon=is_daemon,
                )
            else:
                existing.stage = ExecutionStage.INTERMEDIATE_STREAMING
        elif sniffer.is_terminal:
            # Process reached a terminal state (success or failure)
            if task_key in self._active_tasks:
                del self._active_tasks[task_key]

        return sniffer

    def evaluate_model_completion(self, has_tool_calls: bool) -> ContinuationDecision:
        """Evaluate whether an agent is allowed to finalize, or must continue.

        Args:
            has_tool_calls: True if the model response contains tool invocations.

        Returns:
            ContinuationDecision with continuation directive if barrier triggers.
        """
        # If the model is already invoking further tools, no intervention needed
        if has_tool_calls:
            return ContinuationDecision(
                should_continue=False,
                instruction=None,
                active_task=None,
                reason="Model is already issuing tool calls",
            )

        # Check for un-terminated long-running tasks
        streaming_tasks = [
            t
            for t in self._active_tasks.values()
            if t.stage == ExecutionStage.INTERMEDIATE_STREAMING and not t.is_daemon
        ]

        if not streaming_tasks:
            return ContinuationDecision(
                should_continue=False,
                instruction=None,
                active_task=None,
                reason="All long-running tasks reached terminal state or are daemonized",
            )

        # Take the most pressing active task
        task = streaming_tasks[0]
        if task.continuation_count >= self._max_continuations:
            task.stage = ExecutionStage.TERMINAL_TIMEOUT
            logger.warning(
                "Terminal output barrier exceeded continuation budget (%d) for task %s (PID=%s). "
                "Releasing barrier to prevent deadlock.",
                self._max_continuations,
                task.task_id,
                task.pid,
            )
            return ContinuationDecision(
                should_continue=False,
                instruction=None,
                active_task=task,
                reason=f"Exceeded continuation budget of {self._max_continuations}; forcing timeout exit",
            )

        task.continuation_count += 1
        pid_str = f" (PID={task.pid})" if task.pid is not None else ""
        instruction = (
            f"【Terminal Output Barrier】检测到长任务进程{pid_str}仍在后台运行中，尚未获得终态退出码或终止信号。"
            f"严禁提前判定任务已完成！[当前续轮: {task.continuation_count}/{self._max_continuations}]\n"
            f"请继续使用工具确认进程终态：例如调用 bash_process_tool(action='wait', pid={task.pid}) "
            "直到捕获进程退出信号和最终输出结果。"
        )

        return ContinuationDecision(
            should_continue=True,
            instruction=instruction,
            active_task=task,
            reason=f"Active process {task.task_id} has not emitted terminal exit signal",
        )

    def reset(self) -> None:
        """Clear all active task tracking states."""
        self._active_tasks.clear()
