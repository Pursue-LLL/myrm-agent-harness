"""ToolTurnBudgetGuard — per-user-turn budget for high-cost tools.

Complements FrequencyGuard (sliding time window) with a hard cap per assistant
turn (active_message_id). web_search_tool consumes one unit per question (1–5);
other tools consume one unit per invocation. Pre-call check and record.

[INPUT]
- (none — self-contained, pure standard library)

[OUTPUT]
- TurnBudgetAction: ALLOW / BREAK
- TurnBudgetVerdict: action + reason + quota info
- ToolTurnBudgetGuard: session-scoped per-turn counter
- resolve_turn_budget_units: map tool args → budget units
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

_WEB_SEARCH_MAX_QUESTIONS = 5


def resolve_turn_budget_units(tool_name: str, tool_args: dict[str, object]) -> int:
    """Resolve how many budget units a tool call consumes (web_search = question count)."""
    if tool_name != "web_search_tool":
        return 1
    raw_questions = tool_args.get("questions")
    if isinstance(raw_questions, list):
        count = len([item for item in raw_questions if str(item).strip()])
        return max(1, min(count, _WEB_SEARCH_MAX_QUESTIONS))
    if isinstance(raw_questions, str) and raw_questions.strip():
        return 1
    return 1


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

    def check(
        self,
        tool_name: str,
        *,
        message_id: str | None,
        units: int = 1,
    ) -> TurnBudgetVerdict:
        """Check whether calling this tool would exceed the per-turn budget."""
        limit = self._tool_limits.get(tool_name)
        if limit is None:
            return TurnBudgetVerdict(
                action=TurnBudgetAction.ALLOW,
                reason="",
                tool_count=0,
                tool_limit=0,
            )

        budget_units = max(1, units)
        self._sync_message_id(message_id)
        tool_count = self._counts.get(tool_name, 0)
        if tool_count + budget_units > limit:
            unit_label = "search queries" if tool_name == "web_search_tool" else "calls"
            return TurnBudgetVerdict(
                action=TurnBudgetAction.BREAK,
                reason=(
                    f"Tool '{tool_name}' per-turn budget exceeded: {tool_count}/{limit} "
                    f"{unit_label} for the current user message "
                    f"(requested {budget_units} more). "
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

    def record(
        self,
        tool_name: str,
        *,
        message_id: str | None,
        units: int = 1,
    ) -> None:
        """Record budget units consumed by a tool invocation."""
        if tool_name not in self._tool_limits:
            return
        budget_units = max(1, units)
        self._sync_message_id(message_id)
        self._counts[tool_name] = self._counts.get(tool_name, 0) + budget_units

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
