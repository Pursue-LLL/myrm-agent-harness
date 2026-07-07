"""Budget boundary middleware — enforces budget limits mid-conversation.

[INPUT]
- .tracker::get_token_tracker (POS: Request-scoped token tracker)
- .budget_guard::BudgetStatus (POS: Budget status enum)

[OUTPUT]
- BudgetBoundaryMiddleware: Middleware that enforces budget limits within the agent loop.

[POS]
Budget boundary enforcement middleware. Reads tracker.last_budget_status after each
LLM call and applies progressive responses: WARNING → budget-aware prompt injection,
FINALIZATION → forbid tool calls and force final output.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage

from .budget_guard import BudgetStatus

logger = logging.getLogger(__name__)

_HINT_PREFIX = "[BUDGET_HINT]"


def _build_warning_hint(remaining: float | None) -> str:
    budget_info = f" Approximately ${remaining:.2f} remaining." if remaining is not None else ""
    return (
        f"Budget is running low.{budget_info} "
        "Prioritize completing your current task efficiently. "
        "Provide a concise final answer with your findings so far."
    )


def _build_finalize_hint(remaining: float | None) -> str:
    budget_info = f" (${remaining:.2f} remaining)" if remaining is not None else ""
    return (
        f"Budget limit reached{budget_info}. You MUST provide your final answer NOW. "
        "Do NOT call any more tools. Summarize your work and deliver results immediately."
    )


class BudgetBoundaryMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    """Enforces budget limits within the agent loop.

    Hooks into after_model to inspect the current budget status (set by
    TokenTracker.record() → BudgetChecker.record_cost()). Applies:

    - WARNING: Appends a budget-aware HumanMessage hint at the end of messages
      (uses HumanMessage to preserve SystemMessage hash stability → no cache break).
      Includes dynamic remaining budget amount for informed LLM decision-making.
    - FINALIZATION/EXCEEDED: Strips pending tool_calls from the last AI message,
      forcing the agent to produce a text-only final response next turn.
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled
        self._finalization_injected = False

    def before_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        if not self._enabled:
            return None

        from .tracker import get_token_tracker

        tracker = get_token_tracker()
        if tracker is None or tracker.budget_checker is None:
            return None

        status = tracker.last_budget_status
        remaining = tracker.budget_checker.get_remaining_budget()

        if status == BudgetStatus.WARNING:
            messages = list(state.get("messages", []))
            if not _has_budget_hint(messages):
                hint = _build_warning_hint(remaining)
                messages.append(HumanMessage(content=f"[SYSTEM INSTRUCTION] {_HINT_PREFIX}\n{hint}"))
                return {"messages": messages}

        elif status in (BudgetStatus.FINALIZATION, BudgetStatus.EXCEEDED):
            if not self._finalization_injected:
                self._finalization_injected = True
                messages = list(state.get("messages", []))
                hint = _build_finalize_hint(remaining)
                messages.append(HumanMessage(content=f"[SYSTEM INSTRUCTION] {_HINT_PREFIX}\n{hint}"))
                return {"messages": messages}

        return None

    def after_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        """Strip tool_calls when budget is in FINALIZATION/EXCEEDED state."""
        if not self._enabled:
            return None

        from .tracker import get_token_tracker

        tracker = get_token_tracker()
        if tracker is None:
            return None

        if tracker.budget_checker is None:
            return None

        status = tracker.last_budget_status
        if status not in (BudgetStatus.FINALIZATION, BudgetStatus.EXCEEDED):
            return None

        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage):
            return None

        if not last_msg.tool_calls:
            return None

        logger.warning(
            "BudgetBoundaryMiddleware: stripping %d tool_calls due to %s status",
            len(last_msg.tool_calls),
            status,
        )

        patched_msg = AIMessage(
            content=last_msg.content or "I need to wrap up my response now due to budget constraints.",
            id=last_msg.id,
        )

        new_messages = list(messages[:-1])
        new_messages.append(patched_msg)
        return {"messages": new_messages}


def _has_budget_hint(messages: list[Any]) -> bool:
    """Check if budget hint is already present (idempotency)."""
    for msg in reversed(messages[-3:]):
        if isinstance(msg, HumanMessage) and isinstance(msg.content, str) and _HINT_PREFIX in msg.content:
            return True
    return False
