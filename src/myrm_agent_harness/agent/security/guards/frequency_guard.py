"""FrequencyGuard — tool call frequency anomaly detection for DoS prevention.

Detects abnormally high-frequency tool calls that may indicate:
- Denial-of-Service (DoS) attacks
- Cost overrun from runaway loops
- Malicious or buggy agent behavior

Unlike LoopGuard (which detects logical loops with same params), FrequencyGuard
detects raw call frequency anomalies regardless of parameters.

Detection dimensions:
1. **Global frequency** — total tool calls per time window (all tools combined)
2. **Per-tool frequency** — calls to a specific tool per time window

Response levels:
- ALLOW: Normal operation
- WARN (80% of limit): Append warning to ToolMessage
- BREAK (100% of limit): Block execution entirely

[INPUT]
- (none — self-contained, pure standard library)

[OUTPUT]
- FrequencyAction: ALLOW / WARN / BREAK
- FrequencyVerdict: action + reason + remaining quota
- FrequencyGuard: session-scoped frequency tracker
- get_frequency_guard() / reset_frequency_guard(): ContextVar accessors

[POS]
Layer 5 (Anti-Abuse) guard, parallel to LoopGuard. Integrated into
tool_interceptor_middleware pre-call phase. Prevents DoS and cost overruns
via time-based frequency limits, complementing LoopGuard's logic-based detection.
"""

from __future__ import annotations

import time
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum, auto, unique

# Default exempted tools (low-cost, high-frequency read operations)
_DEFAULT_EXEMPTED_TOOLS: frozenset[str] = frozenset(
    {
        # Memory system (high-frequency readonly)
        "memory_recall_tool",
        "memory_save_tool",
        "memory_manage_tool",
        # Skill system (high-frequency readonly)
        "skill_select_tool",
        "skill_discovery_tool",
        "discover_capability_tool",
        # Knowledge base (readonly)
        "knowledge_tool",
        # UI rendering (pure display)
        "render_ui_tool",
        # Browser readonly operations
        "browser_snapshot_tool",
        "browser_extract_tool",
        # File system readonly operations
        "glob_tool",
        "grep_tool",
    }
)


@unique
class FrequencyAction(StrEnum):
    """Action to take based on frequency check."""

    ALLOW = auto()
    WARN = auto()
    BREAK = auto()


@dataclass(frozen=True, slots=True)
class FrequencyVerdict:
    """Frequency check result."""

    action: FrequencyAction
    reason: str
    global_count: int
    global_limit: int
    tool_count: int
    tool_limit: int

    @property
    def global_remaining(self) -> int:
        return max(0, self.global_limit - self.global_count)

    @property
    def tool_remaining(self) -> int:
        return max(0, self.tool_limit - self.tool_count)


@dataclass(frozen=True, slots=True)
class _CallRecord:
    """Internal record of a tool call with timestamp."""

    timestamp: float
    tool_name: str


class FrequencyGuard:
    """Session-scoped tool call frequency tracker.

    Uses sliding time window to detect DoS and cost overrun scenarios.

    Parameters
    ----------
    window_seconds:
        Time window size in seconds (default: 60s).
    global_limit:
        Maximum total tool calls across all tools in the window (default: 100).
    per_tool_limit:
        Maximum calls to a single tool in the window (default: 30).
    warning_ratio:
        Trigger WARN when usage exceeds this ratio of limit (default: 0.8 = 80%).
    exempted_tools:
        Tool names exempt from per-tool limits (default: memory/skill/knowledge tools).
    """

    def __init__(
        self,
        *,
        window_seconds: float = 60.0,
        global_limit: int = 100,
        per_tool_limit: int = 30,
        warning_ratio: float = 0.8,
        exempted_tools: frozenset[str] = _DEFAULT_EXEMPTED_TOOLS,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if global_limit <= 0:
            raise ValueError("global_limit must be positive")
        if per_tool_limit <= 0:
            raise ValueError("per_tool_limit must be positive")
        if not 0 < warning_ratio < 1:
            raise ValueError("warning_ratio must be between 0 and 1")

        self._window_seconds = window_seconds
        self._global_limit = global_limit
        self._per_tool_limit = per_tool_limit
        self._warning_ratio = warning_ratio
        self._exempted_tools = exempted_tools

        # Sliding window: all calls in chronological order
        self._calls: deque[_CallRecord] = deque()

        # Statistics
        self._total_checks: int = 0
        self._total_warns: int = 0
        self._total_breaks: int = 0

    def check(self, tool_name: str) -> FrequencyVerdict:
        """Check if calling this tool would violate frequency limits.

        Returns FrequencyVerdict with action (ALLOW/WARN/BREAK) and quota info.
        """
        self._total_checks += 1
        current_time = time.time()

        # Expire old records outside the time window
        cutoff_time = current_time - self._window_seconds
        while self._calls and self._calls[0].timestamp < cutoff_time:
            self._calls.popleft()

        # Count global and per-tool calls
        global_count = len(self._calls)
        tool_count = sum(1 for rec in self._calls if rec.tool_name == tool_name)

        # Check global limit
        if global_count >= self._global_limit:
            self._total_breaks += 1
            return FrequencyVerdict(
                action=FrequencyAction.BREAK,
                reason=(
                    f"Global tool call frequency limit exceeded: {global_count}/{self._global_limit} "
                    f"calls in {self._window_seconds}s window. "
                    "This indicates potential DoS or runaway loop. "
                    "Please reduce call frequency or review agent logic."
                ),
                global_count=global_count,
                global_limit=self._global_limit,
                tool_count=tool_count,
                tool_limit=self._per_tool_limit,
            )

        # Check per-tool limit (skip exempted tools)
        if tool_name not in self._exempted_tools:
            if tool_count >= self._per_tool_limit:
                self._total_breaks += 1
                return FrequencyVerdict(
                    action=FrequencyAction.BREAK,
                    reason=(
                        f"Tool '{tool_name}' frequency limit exceeded: {tool_count}/{self._per_tool_limit} "
                        f"calls in {self._window_seconds}s window. "
                        "This tool is being called too frequently. "
                        "Consider batching operations or using alternative approaches."
                    ),
                    global_count=global_count,
                    global_limit=self._global_limit,
                    tool_count=tool_count,
                    tool_limit=self._per_tool_limit,
                )

            # Check per-tool warning threshold
            if tool_count >= self._per_tool_limit * self._warning_ratio:
                self._total_warns += 1
                remaining = self._per_tool_limit - tool_count
                return FrequencyVerdict(
                    action=FrequencyAction.WARN,
                    reason=(
                        f"Tool '{tool_name}' approaching frequency limit: {tool_count}/{self._per_tool_limit} "
                        f"calls in {self._window_seconds}s window ({remaining} remaining). "
                        "Consider reducing call frequency to avoid hitting the limit."
                    ),
                    global_count=global_count,
                    global_limit=self._global_limit,
                    tool_count=tool_count,
                    tool_limit=self._per_tool_limit,
                )

        # Check global warning threshold
        if global_count >= self._global_limit * self._warning_ratio:
            self._total_warns += 1
            remaining = self._global_limit - global_count
            return FrequencyVerdict(
                action=FrequencyAction.WARN,
                reason=(
                    f"Global tool call frequency approaching limit: {global_count}/{self._global_limit} "
                    f"calls in {self._window_seconds}s window ({remaining} remaining). "
                    "Consider reducing overall tool call frequency."
                ),
                global_count=global_count,
                global_limit=self._global_limit,
                tool_count=tool_count,
                tool_limit=self._per_tool_limit,
            )

        return FrequencyVerdict(
            action=FrequencyAction.ALLOW,
            reason="",
            global_count=global_count,
            global_limit=self._global_limit,
            tool_count=tool_count,
            tool_limit=self._per_tool_limit,
        )

    def record(self, tool_name: str) -> None:
        """Record a tool call. Should be called after check() allows execution."""
        current_time = time.time()
        self._calls.append(_CallRecord(timestamp=current_time, tool_name=tool_name))

    def reset(self) -> None:
        """Reset all state. Call at the start of each agent run."""
        self._calls.clear()
        self._total_checks = 0
        self._total_warns = 0
        self._total_breaks = 0

    def get_stats(self) -> dict[str, int | float]:
        """Return current statistics for observability."""
        return {
            "total_checks": self._total_checks,
            "total_warns": self._total_warns,
            "total_breaks": self._total_breaks,
            "current_window_size": len(self._calls),
            "warn_rate": (
                self._total_warns / self._total_checks
                if self._total_checks > 0
                else 0.0
            ),
            "break_rate": (
                self._total_breaks / self._total_checks
                if self._total_checks > 0
                else 0.0
            ),
        }


# ContextVar for session-scoped frequency guard
_frequency_guard_var: ContextVar[FrequencyGuard] = ContextVar("frequency_guard")


def get_frequency_guard() -> FrequencyGuard:
    """Get the FrequencyGuard for the current async context.

    Creates a new one if none exists (lazy initialization).
    """
    try:
        return _frequency_guard_var.get()
    except LookupError:
        guard = FrequencyGuard()
        _frequency_guard_var.set(guard)
        return guard


def reset_frequency_guard() -> None:
    """Reset frequency guard state. Call at the start of each agent run."""
    try:
        guard = _frequency_guard_var.get()
        guard.reset()
    except LookupError:
        pass
