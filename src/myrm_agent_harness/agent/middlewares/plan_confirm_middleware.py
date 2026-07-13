"""Plan Confirmation Middleware — intercepts first plan creation for user review.

When the Agent creates a structured task list via ``todo_write(merge=False)``
with 3+ items in the first plan of a session, this middleware pauses execution
via LangGraph ``interrupt()`` so the user can review, edit, or skip the plan
before the Agent begins execution.

Uses the same ``interrupt()`` / ``resume`` mechanism as ToolApprovalMiddleware
and ReplanMiddleware — no new infrastructure required.

[INPUT]
- langgraph.types::interrupt (POS: LangGraph native HITL suspend/resume)
- agent.middlewares._session_context::get_security_config (POS: Middleware session context)

[OUTPUT]
- PlanConfirmMiddleware: awrap_tool_call middleware for plan-phase HITL

[POS]
Plan-phase HITL gate. Complements ToolApprovalMiddleware (tool-level)
and ShadowGit (post-execution rollback) with pre-execution plan review.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command, interrupt

logger = logging.getLogger(__name__)

_plan_confirmed_var: ContextVar[bool] = ContextVar("plan_confirmed", default=False)

MIN_ITEMS_FOR_CONFIRM = 3


def reset_plan_confirm_state() -> None:
    """Reset plan confirmation state at session start."""
    _plan_confirmed_var.set(False)


class PlanConfirmMiddleware(AgentMiddleware[Any, Any]):
    """Intercept first ``todo_write(merge=False)`` with 3+ items for user review.

    Trigger conditions (ALL must be true):
    1. Tool is ``todo_write``
    2. ``merge`` is ``False`` (new plan, not an update)
    3. Items count >= ``MIN_ITEMS_FOR_CONFIRM``
    4. First plan in session (not yet confirmed/skipped)
    5. ``plan_confirm_enabled`` is ``True`` in session context

    On trigger, calls ``interrupt()`` with the plan payload. The user can:
    - **confirm**: proceed as-is
    - **edit**: provide modified todo list
    - **skip**: proceed without confirmation (disables for rest of session)
    """

    name = "plan_confirm_middleware"

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        raise NotImplementedError("PlanConfirmMiddleware does not support synchronous wrap_tool_call")

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        tool_name = request.tool_call.get("name", "")
        if tool_name != "todo_write":
            return await handler(request)

        if _plan_confirmed_var.get():
            return await handler(request)

        if not _is_plan_confirm_enabled():
            return await handler(request)

        args = request.tool_call.get("args") or {}
        if not isinstance(args, dict):
            return await handler(request)

        merge = args.get("merge", False)
        if merge:
            return await handler(request)

        todos = args.get("todos", [])
        if not isinstance(todos, list) or len(todos) < MIN_ITEMS_FOR_CONFIRM:
            _plan_confirmed_var.set(True)
            return await handler(request)

        plan_items = _extract_plan_summary(todos)

        resume_value = interrupt({
            "action_type": "plan_confirm",
            "tool_name": "todo_write",
            "plan_items": plan_items,
            "total_items": len(todos),
            "goal": args.get("goal"),
        })

        if not isinstance(resume_value, dict):
            _plan_confirmed_var.set(True)
            return await handler(request)

        action = resume_value.get("action", "confirm")

        if action == "skip":
            _plan_confirmed_var.set(True)
            return await handler(request)

        if action == "edit":
            edited_todos = resume_value.get("edited_todos")
            if isinstance(edited_todos, list) and edited_todos:
                request.tool_call["args"]["todos"] = edited_todos
            _plan_confirmed_var.set(True)
            return await handler(request)

        # action == "confirm" (default)
        _plan_confirmed_var.set(True)
        return await handler(request)


def _is_plan_confirm_enabled() -> bool:
    """Check session context for plan_confirm_enabled flag."""
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_security_config,
    )

    config = get_security_config()
    if config is None:
        return False
    return config.plan_confirm_enabled


def _extract_plan_summary(todos: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Extract id + content from todo items for UI display."""
    items: list[dict[str, str]] = []
    for todo in todos:
        if not isinstance(todo, dict):
            continue
        item: dict[str, str] = {}
        if "id" in todo:
            item["id"] = str(todo["id"])
        if "content" in todo:
            item["content"] = str(todo["content"])
        if "status" in todo:
            item["status"] = str(todo["status"])
        if item:
            items.append(item)
    return items


__all__ = ["PlanConfirmMiddleware", "reset_plan_confirm_state"]
