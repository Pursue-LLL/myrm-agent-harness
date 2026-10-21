"""Strongly typed contracts for Persistent Scriptable REPL Desktop Session.

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- ReplRuntimeKind: Enumeration of scriptable runtime interpreters.
- ReplExecutionStatus: Execution status of batch scripts within REPL context.
- ReplScriptCommand: Input specification for multi-step atomic automation script.
- ReplExecutionResult: Output payload capturing stdout, stderr, variable states, and duration.
- DesktopReplSessionSnapshot: Observable state snapshot of a persistent REPL session.

[POS]
Defines data structures powering in-session multi-turn REPL persistence,
cross-turn variable retention, and fast atomic reset for Computer Use.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class ReplRuntimeKind(str, enum.Enum):
    """Runtime interpreter dialect supported by persistent REPL."""

    PYTHON_REPL = "python_repl"
    NODE_REPL = "node_repl"


class ReplExecutionStatus(str, enum.Enum):
    """Execution status resulting from in-session script execution."""

    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    RESET_TRIGGERED = "reset_triggered"


@dataclass(frozen=True, slots=True)
class ReplScriptCommand:
    """Input payload for multi-step scriptable batch automation execution."""

    code: str
    runtime: ReplRuntimeKind = ReplRuntimeKind.PYTHON_REPL
    timeout_seconds: float = 30.0
    preserve_variables: bool = True


@dataclass(slots=True)
class ReplExecutionResult:
    """Execution outcome capturing stdout/stderr, returned value, and active variable state."""

    status: ReplExecutionStatus
    stdout: str
    stderr: str
    returned_value_repr: str
    persisted_variables: list[str]
    execution_time_ms: float
    was_reset: bool = False

    def is_success(self) -> bool:
        """Determines if the batch script executed cleanly."""
        return self.status == ReplExecutionStatus.SUCCESS

    def to_dict(self) -> dict[str, object]:
        """Serializes result into a JSON-compatible dictionary."""
        return {
            "status": self.status.value,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returned_value_repr": self.returned_value_repr,
            "persisted_variables": list(self.persisted_variables),
            "execution_time_ms": self.execution_time_ms,
            "was_reset": self.was_reset,
        }


@dataclass(slots=True)
class DesktopReplSessionSnapshot:
    """State audit snapshot of an active persistent REPL desktop session."""

    session_id: str
    runtime: ReplRuntimeKind
    execution_count: int
    variable_names: list[str]
    variable_types: dict[str, str]
    is_alive: bool
    created_at: float
    last_executed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """Serializes session snapshot to dictionary."""
        return {
            "session_id": self.session_id,
            "runtime": self.runtime.value,
            "execution_count": self.execution_count,
            "variable_names": list(self.variable_names),
            "variable_types": dict(self.variable_types),
            "is_alive": self.is_alive,
            "created_at": self.created_at,
            "last_executed_at": self.last_executed_at,
        }
