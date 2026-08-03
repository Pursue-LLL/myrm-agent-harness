"""ToolTurnBudgetGuard — per-user-turn call budget for high-cost tools.

Complements FrequencyGuard (sliding time window) with a hard cap per assistant
turn (active_message_id). Counts invocation attempts at pre-call (success or failure).

[INPUT]
- (none — self-contained, pure standard library)

[OUTPUT]
- TurnBudgetAction: ALLOW / BREAK
- TurnBudgetVerdict: action + reason + quota info
- ToolTurnBudgetGuard: session-scoped per-turn counter
- get_tool_turn_budget_guard() / reset_tool_turn_budget_guard(): ContextVar accessors

[POS]
Layer 5 (Anti-Abuse) guard, integrated into tool_interceptor_middleware pre-call
phase alongside FrequencyGuard.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum, auto, unique

_DEFAULT_TOOL_LIMITS: dict[str, int] = {
    "web_search_tool": 20,
}

DEFAULT_WEB_SEARCH_TURN_LIMIT = _DEFAULT_TOOL_LIMITS["web_search_tool"]


@unique
class TurnBudgetAction(StrEnum):
    """Action to take based on per-turn budget check."""

    ALLOW = auto()
    BREAK = auto()


@dataclass(frozen=True, slots=True)
class TurnBudgetVerdict:
    """Per-turn budget check result."""

    action: TurnBudgetAction
    reason: str
    tool_count: int
    tool_limit: int

    @property
    def tool_remaining(self) -> int:
        return max(0, self.tool_limit - self.tool_count)


class ToolTurnBudgetGuard:
    """Session-scoped per-turn tool call budget tracker.

    Counts successful tool invocations within a single user turn
    (identified by active_message_id). Resets when the message id changes
    or when reset() is called at the start of a new agent run.
    """

    def __init__(
        self,
        *,
        tool_limits: dict[str, int] | None = None,
    ) -> None:
        limits = tool_limits if tool_limits is not None else dict(_DEFAULT_TOOL_LIMITS)
        for limit in limits.values():
            if limit <= 0:
                raise ValueError("tool_limits values must be positive")
        self._tool_limits = limits
        self._message_id: str | None = None
        self._counts: dict[str, int] = {}

    def _sync_message_id(self, message_id: str | None) -> None:
        scope_key = message_id or "__default__"
        if scope_key != self._message_id:
            self._message_id = scope_key
            self._counts.clear()

    def check(self, tool_name: str, *, message_id: str | None) -> TurnBudgetVerdict:
        """Check whether calling this tool would exceed the per-turn budget."""
        limit = self._tool_limits.get(tool_name)
        if limit is None:
            return TurnBudgetVerdict(
                action=TurnBudgetAction.ALLOW,
                reason="",
                tool_count=0,
                tool_limit=0,
            )

        self._sync_message_id(message_id)
        tool_count = self._counts.get(tool_name, 0)
        if tool_count >= limit:
            return TurnBudgetVerdict(
                action=TurnBudgetAction.BREAK,
                reason=(
                    f"Tool '{tool_name}' per-turn budget exceeded: {tool_count}/{limit} "
                    "calls for the current user message. "
                    "Synthesize existing search results or ask the user before searching again."
                ),
                tool_count=tool_count,
                tool_limit=limit,
            )

        return TurnBudgetVerdict(
            action=TurnBudgetAction.ALLOW,
            reason="",
            tool_count=tool_count,
            tool_limit=limit,
        )

    def record(self, tool_name: str, *, message_id: str | None) -> None:
        """Record a tool invocation attempt against the per-turn budget."""
        if tool_name not in self._tool_limits:
            return
        self._sync_message_id(message_id)
        self._counts[tool_name] = self._counts.get(tool_name, 0) + 1

    def reset(self) -> None:
        """Reset all state. Call at the start of each agent run."""
        self._message_id = None
        self._counts.clear()


_tool_turn_budget_guard_var: ContextVar[ToolTurnBudgetGuard] = ContextVar(
    "tool_turn_budget_guard"
)


def get_tool_turn_budget_guard() -> ToolTurnBudgetGuard:
    """Get the ToolTurnBudgetGuard for the current async context."""
    try:
        return _tool_turn_budget_guard_var.get()
    except LookupError:
        guard = ToolTurnBudgetGuard()
        _tool_turn_budget_guard_var.set(guard)
        return guard


def reset_tool_turn_budget_guard() -> None:
    """Reset turn budget guard state. Call at the start of each agent run."""
    try:
        guard = _tool_turn_budget_guard_var.get()
        guard.reset()
    except LookupError:
        pass
