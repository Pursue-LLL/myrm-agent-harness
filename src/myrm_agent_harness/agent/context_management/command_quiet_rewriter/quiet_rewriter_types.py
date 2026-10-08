"""Data contracts and type definitions for preflight command rewriting and subagent log sink.

Provides strong-typed abstractions for injecting quiet flags before execution
and absorbing high-noise process outputs in isolated subagent sandboxes.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- RewriteStatus: Execution status of command preflight rewriting.
- LogSinkTaskType: Categorization of high-noise operations delegated to subagents.
- LogSinkStatus: High-level completion outcome of a log-sink subagent task.
- QuietRewriteRule: Specification of a quiet flag injection rule for a CLI tool.
- RewriteResult: Result of command preflight rewriting.
- LogSinkTaskSpec: Specification for delegating high-noise tasks to isolated subagents.
- LogSinkConclusionCard: Structured, low-noise card delivered to the main session.
- SubagentLogSinkExecutionRecord: Telemetry and execution audit for subagent log absorption.

[POS]
Data contracts and type definitions for preflight command rewriting and subagent log sink.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class RewriteStatus(str, Enum):
    """Execution status of command preflight rewriting."""

    REWRITTEN = "rewritten"
    UNCHANGED = "unchanged"
    BYPASSED_EXPLICIT_VERBOSE = "bypassed_explicit_verbose"
    BYPASSED_DISABLED = "bypassed_disabled"


class LogSinkTaskType(str, Enum):
    """Categorization of high-noise operations delegated to subagents."""

    BATCH_TEST = "batch_test"
    LOG_ANALYSIS = "log_analysis"
    GIT_HISTORY = "git_history"
    BUILD_INSPECTION = "build_inspection"
    GENERAL_HIGH_NOISE = "general_high_noise"


class LogSinkStatus(str, Enum):
    """High-level completion outcome of a log-sink subagent task."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class QuietRewriteRule:
    """Specification of a quiet flag injection rule for a CLI tool."""

    rule_id: str
    target_tool: str
    flags_to_inject: list[str]
    verbose_flags: tuple[str, ...] = ("-v", "-vv", "-vvv", "--verbose", "--debug")
    quiet_flags: tuple[str, ...] = ("-q", "--quiet", "--silent", "-s")
    description: str = ""
    priority: int = 100


@dataclass(frozen=True)
class RewriteResult:
    """Result of command preflight rewriting."""

    original_command: str
    rewritten_command: str
    status: RewriteStatus
    matched_rule: str | None = None
    injected_flags: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def was_modified(self) -> bool:
        """Return True if command string was altered."""
        return self.status == RewriteStatus.REWRITTEN and self.original_command != self.rewritten_command


@dataclass(frozen=True)
class LogSinkTaskSpec:
    """Specification for delegating high-noise tasks to isolated subagents."""

    task_id: str
    task_type: LogSinkTaskType
    command_or_path: str
    max_steps: int = 5
    quarantine_isolated: bool = True
    context_budget_tokens: int = 16000


@dataclass(frozen=True)
class LogSinkConclusionCard:
    """Structured, low-noise card delivered to the main session."""

    task_id: str
    task_type: LogSinkTaskType
    status: LogSinkStatus
    total_items: int = 0
    passed_items: int = 0
    failed_items: int = 0
    error_locations: list[str] = field(default_factory=list)
    bullet_points: list[str] = field(default_factory=list)
    suggested_action: str | None = None
    raw_character_count: int = 0
    delivered_character_count: int = 0

    @property
    def noise_reduction_ratio(self) -> float:
        """Calculate compression / reduction ratio of noise suppressed."""
        if self.raw_character_count <= 0:
            return 0.0
        reduction = 1.0 - (self.delivered_character_count / self.raw_character_count)
        return max(0.0, min(1.0, reduction))


@dataclass(frozen=True)
class SubagentLogSinkExecutionRecord:
    """Telemetry and execution audit for subagent log absorption."""

    record_id: str
    task_spec: LogSinkTaskSpec
    conclusion_card: LogSinkConclusionCard
    subagent_quarantined_messages: int
    raw_tokens_absorbed: int
    delivered_tokens: int
    duration_ms: float
