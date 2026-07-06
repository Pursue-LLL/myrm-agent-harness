"""Completion verification guard middleware.

Intercepts the Agent's final answer attempt and enforces verification for
code modification tasks. When the Agent modifies code files but skips
verification (tests, lint, type-check), the guard blocks completion and
forces the Agent to run checks first.

Task-type-aware strictness:
  - **Code modification** (has_writes=True + code files): CRITICAL blocking
    mode, up to max_rejections before forced finish.
  - **Query/non-code tasks**: no intervention — the Agent finishes immediately.

Also implements the **Mixed Message Guard**: when an LLM outputs both a
substantive final response AND read-only tool_calls in the same message,
strips the tool_calls to let the agent terminate immediately — saving
unnecessary tool execution rounds and extra LLM calls.

Internal tool CallRecords (``_``-prefixed names like ``_completion_check``)
are excluded from the checklist to prevent self-feedback loops.

State is stored as module-level variables (not ContextVar) because LangGraph
executes nodes in copied contexts, which prevents ContextVar state from
persisting across ReAct cycles.

[INPUT]
- langchain.agents.middleware::AgentMiddleware (POS: LangChain middleware base)
- langchain_core.tools::tool (POS: tool decorator)
- agent.middlewares.tool_interceptor_middleware::get_loop_guard (POS: LoopGuard accessor)
- agent.middlewares.completion_guard_checklist::build_checklist, classify_verification (POS: Verification command classification and checklist generation for CompletionGuard.)

[OUTPUT]
- CompletionGuard: aafter_model middleware for critical completion verification
- classify_verification(): detect verification commands in bash tool args
- reset_completion_guard(): reset session state for new run

[POS]
Fills the "Agent finishing" gap in the guard chain. Existing guards cover
tool-call loops (LoopGuard), context overflow (ContextBudgetGuard), and
emergency stops (EStop). CompletionGuard ensures code modifications are
verified before delivery, and the Mixed Message Guard prevents wasted
token/time when LLM already produced a complete answer.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.agent.middlewares.completion_guard_checklist import (
    build_checklist,
    classify_verification,
)

_build_checklist = build_checklist

logger = logging.getLogger(__name__)

COMPLETION_CHECK_TOOL_NAME = "_completion_check"

_MUTATION_TOOLS: frozenset[str] = frozenset(
    {
        "write_file",
        "create_file",
        "edit_file",
        "delete_file",
        "file_write_tool",
        "file_edit_tool",
        "file_create_tool",
        "execute_command",
        "run_terminal",
        "bash_code_execute_tool",
        "send_message",
        "git_commit",
        "git_push",
        "apply_diff",
        "delegate_task_tool",
        "spawn_subagent",
        "request_answer_user_tool",
        "answer_user",
        "finish",
        "complete_task",
        "browser_navigate_tool",
        "browser_click_tool",
        "browser_type_tool",
        "skill_manage_tool",
        "kanban_manage_tool",
        "canvas_tool",
        "cron_manage_tool",
    }
)


def is_mutating_tool(tool_name: str) -> bool:
    """Return True when the tool may mutate workspace or external state."""
    return tool_name in _MUTATION_TOOLS


_rejection_count: int = 0


def reset_completion_guard() -> None:
    """Reset guard state — call at the start of each agent run."""
    global _rejection_count
    _rejection_count = 0


@tool(COMPLETION_CHECK_TOOL_NAME)
def _completion_check_tool(workspace_root: str = "", force_fail: bool = False) -> str:
    """Internal verification checkpoint — generates a task-aware checklist.

    This tool is injected by the CompletionGuard middleware. It reads the
    session's tool-call history to produce a verification checklist so the
    Agent can self-audit before delivering its final answer.
    """
    if force_fail:
        return (
            " CRITICAL SYSTEM DIRECTIVE: You have failed to verify your work multiple times. "
            "You are now permitted to finish the task, but you MUST include a clear warning "
            "in your final response to the user stating that you were unable to successfully "
            "verify the changes (e.g., tests failed or were not run) and that they should "
            "manually review the work."
        )

    from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
        get_loop_guard,
    )

    guard = get_loop_guard()
    records = list(guard._window)
    checklist_str, _ = _build_checklist(records, workspace_root=workspace_root)
    return checklist_str


_UNFINISHED_MARKERS: tuple[str, ...] = (
    "...",
    "接下来我会",
    "I'll now",
    "Let me",
    "I will now",
    "下面我来",
    "让我",
    "我现在",
    "Next, I'll",
)

_STRUCTURE_MARKERS: tuple[str, ...] = ("\n#", "\n-", "\n*", "\n1.", "```")


def _is_substantive_final_response(content: str) -> bool:
    """Determine if content is a complete final response rather than in-progress narration.

    Returns True only when the content exhibits characteristics of a finished answer:
    sufficient length, structured formatting, and no trailing "unfinished" indicators.
    """
    if len(content) < 500:
        return False
    has_structure = any(marker in content for marker in _STRUCTURE_MARKERS)
    if not has_structure:
        return False
    tail = content[-100:]
    has_unfinished = any(marker in tail for marker in _UNFINISHED_MARKERS)
    return not has_unfinished


class CompletionGuard(AgentMiddleware):  # type: ignore[type-arg]
    """Critical completion verification guard.

    Only blocks the Agent when code files were modified without verification
    (tests, lint, type-check). Non-critical tasks pass through immediately.

    Also implements the Mixed Message Guard to strip read-only tool_calls
    from messages that already contain a substantive final answer.

    Parameters
    ----------
    enabled:
        Master on/off switch.
    max_rejections:
        Maximum times the guard blocks before forced finish (safety valve).
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_rejections: int = 3,
    ) -> None:
        self._enabled = enabled
        self._max_rejections = max_rejections

    def get_tools(self) -> list[BaseTool]:
        """Expose the internal ``_completion_check`` tool for registration."""
        return [_completion_check_tool]

    async def aafter_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        """Intercept completion attempts and inject verification when critical errors exist."""
        global _rejection_count
        if not self._enabled:
            return None

        messages = state.get("messages", [])
        if not messages:
            return None

        last_ai_msg = next((msg for msg in reversed(messages) if isinstance(msg, AIMessage)), None)
        if last_ai_msg is None:
            return None

        is_attempting_completion = False

        if not last_ai_msg.tool_calls:
            is_attempting_completion = True
        else:
            finish_tool_names = {
                "request_answer_user_tool",
                "answer_user",
                "finish",
                "complete_task",
            }
            has_finish_tool = any(
                tc.get("name") in finish_tool_names for tc in last_ai_msg.tool_calls if isinstance(tc, dict)
            )
            if has_finish_tool:
                is_attempting_completion = True

        if not is_attempting_completion:
            # --- Mixed Message Guard ---
            if last_ai_msg.content and last_ai_msg.tool_calls:
                content_str = last_ai_msg.content if isinstance(last_ai_msg.content, str) else str(last_ai_msg.content)
                if _is_substantive_final_response(content_str):
                    has_mutation = any(
                        tc.get("name") in _MUTATION_TOOLS for tc in last_ai_msg.tool_calls if isinstance(tc, dict)
                    )
                    if not has_mutation:
                        logger.info(
                            "[CompletionGuard] Mixed message detected: content is substantive "
                            "final response with %d read-only tool_calls — stripping to terminate early.",
                            len(last_ai_msg.tool_calls),
                        )
                        last_ai_msg.tool_calls = []
                        return {"messages": [last_ai_msg]}
            return None

        from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
            get_loop_guard,
        )

        guard = get_loop_guard()
        records = list(guard._window)

        workspace_root = None
        if hasattr(runtime, "get") and isinstance(runtime, dict):
            configurable = runtime.get("configurable", {})
            if isinstance(configurable, dict):
                context = configurable.get("context", {})
                if isinstance(context, dict):
                    workspace_root = context.get("workspace_root")

        _, has_critical_errors = _build_checklist(
            records, workspace_root=str(workspace_root) if workspace_root else None
        )

        if not has_critical_errors:
            return None

        # --- CRITICAL BLOCKING MODE ---
        current_rejections = _rejection_count

        if current_rejections >= self._max_rejections:
            logger.error(
                "[CompletionGuard] Max rejections (%d) reached. Allowing agent to finish despite critical errors.",
                self._max_rejections,
            )
            tool_call_id = f"call_{uuid.uuid4().hex[:24]}"
            last_ai_msg.tool_calls = [
                {
                    "name": COMPLETION_CHECK_TOOL_NAME,
                    "args": {
                        "workspace_root": (str(workspace_root) if workspace_root else ""),
                        "force_fail": True,
                    },
                    "id": tool_call_id,
                    "type": "tool_call",
                }
            ]
            _rejection_count = 0
            return {"messages": [last_ai_msg]}

        _rejection_count = current_rejections + 1
        logger.warning(
            "[CompletionGuard] Critical errors found. Blocking completion (rejection %d/%d).",
            current_rejections + 1,
            self._max_rejections,
        )

        tool_call_id = f"call_{uuid.uuid4().hex[:24]}"
        last_ai_msg.tool_calls = [
            {
                "name": COMPLETION_CHECK_TOOL_NAME,
                "args": {"workspace_root": str(workspace_root) if workspace_root else ""},
                "id": tool_call_id,
                "type": "tool_call",
            }
        ]
        return {"messages": [last_ai_msg]}


__all__ = [
    "COMPLETION_CHECK_TOOL_NAME",
    "CompletionGuard",
    "classify_verification",
    "reset_completion_guard",
]
