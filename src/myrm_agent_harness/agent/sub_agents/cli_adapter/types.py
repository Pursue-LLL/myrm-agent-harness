"""[INPUT] None.
[OUTPUT] Enum types and data contracts for Heterogeneous External Agent Bridge & CLI Process Adapter.
[POS] Subagent CLI process adapter domain types for multi-CLI lane dispatch and JSON receipts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ExternalAgentKind(StrEnum):
    """Supported kinds of external heterogeneous Agent CLI processes."""

    CLAUDE_CODE = "claude-code"
    CODEX_CLI = "codex-cli"
    OPENCLAW = "openclaw"
    GENERIC_STDIO = "generic-stdio"


class ProcessLaneStatus(StrEnum):
    """Lifecycle state of an external CLI Agent process lane."""

    IDLE = "idle"
    SPAWNING = "spawning"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    TERMINATED = "terminated"


@dataclass
class ExternalAgentConfig:
    """Configuration descriptor for spawning an external CLI agent lane."""

    agent_id: str
    name: str
    kind: ExternalAgentKind
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    max_turns: int = 10
    timeout_seconds: float = 60.0
    max_budget_usd: float = 1.0
    expected_model: str | None = None


@dataclass
class ProcessReceipt:
    """Cryptographically verifiable execution receipt capturing CLI output and exit facts."""

    execution_id: str
    agent_id: str
    kind: ExternalAgentKind
    status: ProcessLaneStatus
    exit_code: int | None
    duration_ms: int
    stdout_summary: str
    stderr_summary: str
    receipt_hash: str
    created_at: float = field(default_factory=time.time)


@dataclass
class ProcessExecutionRequest:
    """Execution input dispatched to the external CLI agent."""

    execution_id: str
    input_text: str
    turn_index: int = 1
    extra_args: list[str] = field(default_factory=list)
