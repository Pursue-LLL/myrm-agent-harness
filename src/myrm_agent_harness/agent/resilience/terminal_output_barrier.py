"""Terminal Output Barrier and Long Horizon Execution Guard.

Defends against premature completion (the "fake finish" flaw) where an Agent
stops tool invocation upon observing intermediate streaming or background logs
(e.g., compile progress, auto-yield chunks) before the process has exited.
Implements the 'continue until terminal task output' contract (aligned with
Wuwe commit 295d8e7d).

[INPUT]
- tool_name: str
- tool_input: dict[str, object]
- tool_output: str | dict[str, object]

[OUTPUT]
- ExecutionStage: Enum for intermediate streaming vs terminal success/failure/timeout
- TerminalSnifferResult: Objective classification of tool outputs
- LongRunningTaskState: Stateful context tracking active background executions
- classify_terminal_output: Objective sniffer determining if an output is terminal
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Mapping


class ExecutionStage(str, Enum):
    """Lifecycle stage of a long-running execution."""

    INTERMEDIATE_STREAMING = "intermediate_streaming"
    TERMINAL_SUCCESS = "terminal_success"
    TERMINAL_FAILURE = "terminal_failure"
    TERMINAL_TIMEOUT = "terminal_timeout"


@dataclass(frozen=True, slots=True)
class TerminalSnifferResult:
    """Outcome of analyzing a tool output for process termination signals."""

    is_terminal: bool
    stage: ExecutionStage
    pid: int | None
    exit_code: int | None
    reason: str
    continuation_prompt: str | None


@dataclass(slots=True)
class LongRunningTaskState:
    """Tracks state and continuation budget for an active long-running task."""

    task_id: str
    pid: int | None
    tool_name: str
    command: str | None
    stage: ExecutionStage
    continuation_count: int = 0
    is_daemon: bool = False


_RE_EXIT_CODE = re.compile(
    r"(?:process exited with (?:code|status)|exit code:|return code:)\s*(-?\d+)",
    re.IGNORECASE,
)
_RE_PID = re.compile(r"(?:pid[=:\s]+|process id[=:\s]+)(\d+)", re.IGNORECASE)
_RE_AUTO_YIELD = re.compile(
    r"(?:auto-yield|command still running in background|running in the background)",
    re.IGNORECASE,
)
_RE_INTERMEDIATE_PROGRESS = re.compile(
    r"(?:compiling\s+\w+|building\s+\w+|\[\s*\d+/\d+\s*\]|downloading\s+\w+|progress:\s*\d+%)",
    re.IGNORECASE,
)


def _extract_int_field(data: Mapping[str, object], *keys: str) -> int | None:
    for k in keys:
        val = data.get(k)
        if isinstance(val, int) and not isinstance(val, bool):
            return val
        if isinstance(val, str) and val.strip().lstrip("-").isdigit():
            try:
                return int(val.strip())
            except ValueError:
                continue
    return None


def _extract_bool_field(data: Mapping[str, object], *keys: str) -> bool:
    for k in keys:
        val = data.get(k)
        if isinstance(val, bool):
            return val
        if isinstance(val, str) and val.lower() in ("true", "1", "yes"):
            return True
    return False


def classify_terminal_output(
    tool_name: str,
    tool_input: Mapping[str, object],
    tool_output: object,
) -> TerminalSnifferResult:
    """Classify tool output into intermediate streaming vs terminal signal.

    Args:
        tool_name: Name of the executed tool (e.g. 'bash_code_execute_tool').
        tool_input: Input dictionary passed to the tool.
        tool_output: Output from the tool, either a string, dict, or structured object.

    Returns:
        TerminalSnifferResult indicating whether execution reached a terminal point.
    """
    # 1. Daemon / detached processes explicitly opt out of terminal wait
    if _extract_bool_field(tool_input, "is_daemon", "daemon", "detach", "run_in_background"):
        # If user explicitly asked for background daemon, treat initial launch as detached success
        if _extract_bool_field(tool_input, "is_daemon", "daemon"):
            return TerminalSnifferResult(
                is_terminal=True,
                stage=ExecutionStage.TERMINAL_SUCCESS,
                pid=_extract_int_field(tool_input, "pid"),
                exit_code=0,
                reason="Daemon process explicitly detached; no terminal wait required",
                continuation_prompt=None,
            )

    # 2. Structured dictionary output inspection
    if isinstance(tool_output, Mapping):
        exit_code = _extract_int_field(tool_output, "exit_code", "returncode", "code", "exit_status")
        pid = _extract_int_field(tool_output, "pid", "process_id") or _extract_int_field(tool_input, "pid")

        # Check explicit running / still_running flags
        is_still_running = _extract_bool_field(
            tool_output, "still_running", "is_running", "running", "in_progress"
        )
        waiting_for_input = _extract_bool_field(tool_output, "waiting_for_input", "needs_input")

        if is_still_running or (pid is not None and exit_code is None and tool_output.get("status") == "running"):
            pid_str = f" PID={pid}" if pid else ""
            if waiting_for_input:
                hint = str(tool_output.get("input_wait_hint") or "waiting for interactive input")
                prompt = (
                    f"【Terminal Output Barrier】Background process{pid_str} is paused waiting for user/stdin input: "
                    f"'{hint}'. You must NOT claim completion. Use bash_process_tool(action='submit_stdin', pid={pid}) "
                    "to provide input or resume execution."
                )
            else:
                prompt = (
                    f"【Terminal Output Barrier】Task command is still actively running in background{pid_str}. "
                    "You must NOT claim completion prematurely. Continue waiting or monitor until process exit is confirmed "
                    f"via bash_process_tool(action='wait', pid={pid})."
                )
            return TerminalSnifferResult(
                is_terminal=False,
                stage=ExecutionStage.INTERMEDIATE_STREAMING,
                pid=pid,
                exit_code=None,
                reason="Process still actively running in background without exit code",
                continuation_prompt=prompt,
            )

        # Check definite exit codes
        if exit_code is not None:
            stage = ExecutionStage.TERMINAL_SUCCESS if exit_code == 0 else ExecutionStage.TERMINAL_FAILURE
            return TerminalSnifferResult(
                is_terminal=True,
                stage=stage,
                pid=pid,
                exit_code=exit_code,
                reason=f"Process exited with deterministic exit code {exit_code}",
                continuation_prompt=None,
            )

    # 3. String / text inspection
    text = str(tool_output or "")

    # Look for auto-yield or background running cues
    if _RE_AUTO_YIELD.search(text):
        pid_match = _RE_PID.search(text)
        pid_val = int(pid_match.group(1)) if pid_match else _extract_int_field(tool_input, "pid")
        pid_str = f" PID={pid_val}" if pid_val else ""
        prompt = (
            f"【Terminal Output Barrier】Auto-yield detected: command still running in background{pid_str}. "
            "Do NOT assume the build/task is complete. Use bash_process_tool(action='wait', pid="
            f"{pid_val or 'PID'}) to wait until terminal output and exit code are observed."
        )
        return TerminalSnifferResult(
            is_terminal=False,
            stage=ExecutionStage.INTERMEDIATE_STREAMING,
            pid=pid_val,
            exit_code=None,
            reason="Output indicates auto-yield background execution in progress",
            continuation_prompt=prompt,
        )

    # Look for definite exit code in string
    exit_match = _RE_EXIT_CODE.search(text)
    if exit_match:
        ec = int(exit_match.group(1))
        stage = ExecutionStage.TERMINAL_SUCCESS if ec == 0 else ExecutionStage.TERMINAL_FAILURE
        return TerminalSnifferResult(
            is_terminal=True,
            stage=stage,
            pid=_extract_int_field(tool_input, "pid"),
            exit_code=ec,
            reason=f"Parsed exit code {ec} from text output",
            continuation_prompt=None,
        )

    # Look for intermediate compilation/progress indicators without exit code
    if _RE_INTERMEDIATE_PROGRESS.search(text) and "finished" not in text.lower() and "succeeded" not in text.lower():
        pid_val = _extract_int_field(tool_input, "pid")
        prompt = (
            "【Terminal Output Barrier】Observed intermediate streaming progress without terminal completion marker. "
            "Do NOT conclude task prematurely. Continue execution or verify exit status."
        )
        return TerminalSnifferResult(
            is_terminal=False,
            stage=ExecutionStage.INTERMEDIATE_STREAMING,
            pid=pid_val,
            exit_code=None,
            reason="Observed intermediate streaming progress without terminal completion marker",
            continuation_prompt=prompt,
        )

    # Default: non-background regular tool return is treated as terminal success
    return TerminalSnifferResult(
        is_terminal=True,
        stage=ExecutionStage.TERMINAL_SUCCESS,
        pid=_extract_int_field(tool_input, "pid"),
        exit_code=0,
        reason="Regular tool output with no pending background signals",
        continuation_prompt=None,
    )
