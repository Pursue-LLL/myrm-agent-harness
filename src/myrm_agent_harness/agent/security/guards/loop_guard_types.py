"""Types for the unified loop detection system.

[INPUT]
(none — pure enums + dataclasses, no external deps)

[OUTPUT]
- LoopAction, LoopVerdict: verdict types for loop detection with optional pattern kind
- LoopKind, AgentPhase, SuccessLevel, SuggestionPriority: detection enums
- WarningLevel, ErrorPattern, ToolGroup: analysis enums
- VerificationCategory: verification evidence classification
- LoopGuardMetrics: statistics and observability
- CallRecord: internal call tracking record

[POS]
Core types for the unified loop guard. Provides verdict types
(ALLOW/WARN/BREAK) and analysis types (SuccessLevel, AgentPhase,
Metrics, etc.) for the LoopGuard detection system.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, StrEnum

# ---------------------------------------------------------------------------
# Verdict types (from LoopGuard)
# ---------------------------------------------------------------------------


class LoopAction(StrEnum):
    """Verdict action for a tool call."""

    ALLOW = "allow"
    WARN = "warn"
    BREAK = "break"


@dataclass(frozen=True, slots=True)
class LoopVerdict:
    """Result of loop detection check."""

    action: LoopAction
    reason: str
    backoff_hint: str
    loop_kind: str | None = None


VERDICT_ALLOW = LoopVerdict(action=LoopAction.ALLOW, reason="", backoff_hint="")


# ---------------------------------------------------------------------------
# Detection pattern types
# ---------------------------------------------------------------------------


class LoopKind(Enum):
    """Types of detected loop patterns."""

    OK = "ok"
    REPETITION = "repetition"
    PING_PONG = "ping_pong"
    NO_PROGRESS = "no_progress"
    DIVERGENCE = "divergence"
    OUTPUT_DIMINISHING = "output_diminishing"
    CONSECUTIVE_FAILURES = "consecutive_failures"
    ERROR_SIGNATURE = "error_signature"


class ErrorPattern(Enum):
    """Common error patterns in tool results."""

    FILE_NOT_FOUND = "file_not_found"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    INVALID_FORMAT = "invalid_format"
    EMPTY_RESULT = "empty_result"
    UNKNOWN = "unknown"


class AgentPhase(Enum):
    """Agent execution phases for adaptive threshold adjustment."""

    EXPLORATION = "exploration"
    EXECUTION = "execution"
    RECOVERY = "recovery"

    @property
    def divergence_failure_threshold(self) -> float:
        """Failure rate threshold for divergence detection."""
        return {
            AgentPhase.EXPLORATION: 0.60,
            AgentPhase.EXECUTION: 0.30,
            AgentPhase.RECOVERY: 0.15,
        }[self]


class WarningLevel(Enum):
    """Warning severity levels for context-aware classification."""

    CRITICAL_WARN = "critical_warn"
    NORMAL_WARN = "normal_warn"
    INFO_WARN = "info_warn"
    NO_WARN = "no_warn"


class SuggestionPriority(Enum):
    """Priority levels for suggestions."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def emoji(self) -> str:
        """Text indicator for priority level."""
        return {
            SuggestionPriority.HIGH: "[!!]",
            SuggestionPriority.MEDIUM: "[!]",
            SuggestionPriority.LOW: "[i]",
        }[self]


class SuccessLevel(Enum):
    """Layered success levels for tool results."""

    FULL_SUCCESS = "full_success"
    PARTIAL_SUCCESS = "partial_success"
    EMPTY_OK = "empty_ok"
    FAILURE = "failure"

    @property
    def weight(self) -> float:
        """Weight for effective follow rate calculation."""
        return {
            SuccessLevel.FULL_SUCCESS: 1.0,
            SuccessLevel.PARTIAL_SUCCESS: 0.5,
            SuccessLevel.EMPTY_OK: 0.3,
            SuccessLevel.FAILURE: 0.0,
        }[self]


# ---------------------------------------------------------------------------
# Tool semantic grouping (for divergence detection)
# ---------------------------------------------------------------------------


class ToolGroup(Enum):
    """Semantic grouping of tools for divergence detection."""

    SEARCH = "search"
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    MEMORY = "memory"
    BROWSER = "browser"
    NETWORK = "network"
    OTHER = "other"


TOOL_SEMANTIC_MAP: dict[str, ToolGroup] = {
    "memory_recall_tool": ToolGroup.MEMORY,
    "conversation_search_tool": ToolGroup.MEMORY,
    "memory_save_tool": ToolGroup.MEMORY,
    "memory_manage_tool": ToolGroup.MEMORY,
    "file_read_tool": ToolGroup.READ,
    "glob_tool": ToolGroup.SEARCH,
    "grep_tool": ToolGroup.SEARCH,
    "file_write_tool": ToolGroup.WRITE,
    "file_edit_tool": ToolGroup.WRITE,
    "bash_code_execute_tool": ToolGroup.EXECUTE,
    "web_search_tool": ToolGroup.SEARCH,
    "web_fetch_tool": ToolGroup.NETWORK,
    "browser_navigate_tool": ToolGroup.BROWSER,
    "browser_snapshot_tool": ToolGroup.BROWSER,
    "browser_interact_tool": ToolGroup.BROWSER,
    "browser_extract_tool": ToolGroup.BROWSER,
    "browser_manage_tool": ToolGroup.BROWSER,
    "delegate_task_tool": ToolGroup.EXECUTE,
    "skill_select_tool": ToolGroup.SEARCH,
    "discover_capability_tool": ToolGroup.SEARCH,
    "skill_discovery_tool": ToolGroup.SEARCH,
    "_completion_check": ToolGroup.OTHER,
}


def get_tool_group(tool_name: str) -> ToolGroup:
    """Map a tool name to its semantic group."""
    return TOOL_SEMANTIC_MAP.get(tool_name, ToolGroup.OTHER)


# ---------------------------------------------------------------------------
# Metrics and observability
# ---------------------------------------------------------------------------


@dataclass
class LoopGuardMetrics:
    """Statistics for loop detection performance and patterns."""

    total_calls: int = 0
    total_detections: int = 0
    detections_by_kind: dict[LoopKind, int] = field(default_factory=lambda: defaultdict(int))
    detections_by_tool: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    streak_lengths: list[int] = field(default_factory=list)
    suggestions_given: int = 0
    suggestions_followed: int = 0
    effective_follows: float = 0.0
    suggestion_quality_scores: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    suggestion_attempt_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def detection_rate(self) -> float:
        """Percentage of calls that triggered loop detection."""
        return self.total_detections / max(self.total_calls, 1)

    @property
    def avg_streak(self) -> float:
        """Average length of detected loops."""
        return sum(self.streak_lengths) / max(len(self.streak_lengths), 1)

    @property
    def param_change_rate(self) -> float:
        """Percentage of suggestions followed by parameter changes."""
        return self.suggestions_followed / max(self.suggestions_given, 1)

    @property
    def effective_follow_rate(self) -> float:
        """Percentage of suggestions followed that led to success."""
        return self.effective_follows / max(self.suggestions_given, 1)

    def get_suggestion_quality(self, suggestion_key: str) -> float:
        """Get quality score for a suggestion type. Range: [-1.0, 1.0]."""
        attempts = self.suggestion_attempt_counts.get(suggestion_key, 0)
        if attempts == 0:
            return 0.0
        return self.suggestion_quality_scores.get(suggestion_key, 0.0) / attempts

    def update_suggestion_quality(self, suggestion_key: str, success_level: SuccessLevel) -> None:
        """Update quality score for a suggestion based on outcome."""
        self.suggestion_attempt_counts[suggestion_key] += 1

        if success_level == SuccessLevel.FULL_SUCCESS:
            self.suggestion_quality_scores[suggestion_key] += 1.0
        elif success_level in (SuccessLevel.PARTIAL_SUCCESS, SuccessLevel.EMPTY_OK):
            self.suggestion_quality_scores[suggestion_key] += 0.5
        elif success_level == SuccessLevel.FAILURE:
            self.suggestion_quality_scores[suggestion_key] -= 0.5

    def to_dict(self) -> dict[str, object]:
        """Export metrics as dictionary."""
        suggestion_quality = {key: f"{self.get_suggestion_quality(key):.2f}" for key in self.suggestion_quality_scores}

        return {
            "total_calls": self.total_calls,
            "total_detections": self.total_detections,
            "detection_rate": f"{self.detection_rate:.1%}",
            "avg_streak": f"{self.avg_streak:.1f}",
            "suggestions_given": self.suggestions_given,
            "suggestions_followed": self.suggestions_followed,
            "effective_follows": self.effective_follows,
            "param_change_rate": f"{self.param_change_rate:.1%}",
            "effective_follow_rate": f"{self.effective_follow_rate:.1%}",
            "suggestion_quality": suggestion_quality,
            "by_kind": {k.value: v for k, v in self.detections_by_kind.items()},
            "by_tool": dict(self.detections_by_tool),
        }


# ---------------------------------------------------------------------------
# Internal call record
# ---------------------------------------------------------------------------


class VerificationCategory(StrEnum):
    """Categories of verification evidence detected in tool executions."""

    TEST = "test"
    LINT = "lint"
    TYPECHECK = "typecheck"
    BUILD = "build"


@dataclass(slots=True)
class CallRecord:
    """Internal record of a single tool invocation."""

    tool_name: str
    args_hash: str
    args: dict[str, object]
    result_hash: str = ""
    result_content: str = ""
    success_level: SuccessLevel | None = None
    verification_type: VerificationCategory | None = None
