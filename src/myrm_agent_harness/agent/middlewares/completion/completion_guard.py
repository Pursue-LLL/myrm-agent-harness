"""Completion verification guard middleware.

Intercepts the Agent's final answer attempt and enforces verification for
code modification tasks. When the Agent modifies code files but skips
verification (tests, lint, type-check), the guard blocks completion and
forces the Agent to run checks first.

Task-type-aware strictness:
  - **Code modification** (has_writes=True + code files): CRITICAL blocking
    mode, up to max_rejections before forced finish.
  - **Freshness-sensitive query tasks**: when user asks for latest/current data
    but no successful web/search/browser evidence exists, block completion and
    request evidence collection before finishing.
  - **Other query/non-code tasks**: no intervention — the Agent finishes immediately.

Temporal ordering enforcement: when code is modified AFTER the last successful
verification, the guard independently re-runs the verification command in the
sandbox before allowing completion — zero LLM cost, no agent trust required.

Also implements the **Mixed Message Guard**: when an LLM outputs both a
substantive final response AND read-only tool_calls in the same message,
strips the tool_calls to let the agent terminate immediately — saving
unnecessary tool execution rounds and extra LLM calls. A call is preserved
when it is effectful (`is_mutating_tool`) or is an interaction/UI carrier
(`_INTERACTION_UI_TOOLS`) — dropping either would lose a user-visible side
effect or break the interaction chain. When the user request demands external
evidence (freshness/citation) and no successful evidence exists yet, the
tool_calls are kept so the agent gathers real data instead of letting
unverified content reach the user.

Internal tool CallRecords (``_``-prefixed names like ``_completion_check``)
are excluded from the checklist to prevent self-feedback loops.

State is stored as module-level variables (not ContextVar) because LangGraph
executes nodes in copied contexts, which prevents ContextVar state from
persisting across ReAct cycles.

[INPUT]
- langchain.agents.middleware::AgentMiddleware (POS: LangChain middleware base)
- langchain_core.tools::tool (POS: tool decorator)
- agent.middlewares.tool_interceptor_middleware::get_loop_guard (POS: LoopGuard accessor)
- agent.middlewares.completion.completion_guard_checklist::build_checklist, classify_verification, find_last_successful_verification_command (POS: Verification command classification, checklist generation, and temporal-order verification command extraction for CompletionGuard.)
- agent.middlewares.completion.completion_guard_external_evidence::build_external_evidence_reason (POS: Freshness-sensitive external evidence gate including MCP PTC bash via skills.mcp_* and Direct FC via mcp__{server}__{tool})
- agent.middlewares.completion.deliverable_write_verifier::check_deliverable_write_claim (POS: Zero-call deliverable write claim detection for CompletionGuard)
- core.security.tool_registry::resolve_safety_metadata (POS: tool safety metadata incl. MCP readOnlyHint)

[OUTPUT]
- CompletionGuard: after_model middleware for critical completion verification + independent re-run
- is_mutating_tool(): SSOT for effectful tool detection (static mutation set, registry fail-closed fallback)
- classify_verification(): re-export from completion_guard_checklist
- reset_completion_guard(): reset session state for new run

[POS]
Fills the "Agent finishing" gap in the guard chain. Existing guards cover
tool-call loops (LoopGuard), context overflow (ContextBudgetGuard), and
emergency stops (EStop). CompletionGuard ensures code modifications are
verified before delivery via temporal ordering analysis and independent
sandbox re-run when code changes occur after the last successful verification.
The Mixed Message Guard prevents wasted token/time when LLM already produced
a complete answer.
"""

from __future__ import annotations

import logging
import uuid
from copy import deepcopy
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.agent.middlewares.completion.completion_guard_checklist import (
    _CODE_EXTENSIONS,
    _has_post_verification_code_write,
    _is_code_file,
    build_checklist,
    classify_verification,
    find_last_successful_verification_command,
)
from myrm_agent_harness.agent.middlewares.completion.completion_guard_external_evidence import (
    build_external_evidence_reason,
)
from myrm_agent_harness.agent.middlewares.completion.deliverable_write_verifier import (
    check_deliverable_write_claim,
)
from myrm_agent_harness.agent.orchestration.hooks import COMPLETION_CHECK_TOOL_NAME
from myrm_agent_harness.agent.security.guards.loop_guard import (
    ToolGroup,
    get_tool_group,
)
from myrm_agent_harness.core.security.tool_registry import resolve_safety_metadata

_build_checklist = build_checklist
_find_last_verification_cmd = find_last_successful_verification_command

logger = logging.getLogger(__name__)

_MUTATION_TOOLS: frozenset[str] = frozenset(
    {
        # 写/执行/管理类（会改变工作区或外部状态）
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
        "skill_market_tool",  # install/uninstall/install_from_url 写入技能库，registry 只读标注但实为变异
        "kanban_manage_tool",
        "cron_manage_tool",
    }
)

# 交互/UI 承载类：registry 标只读，但剥离会丢失用户可见功能（提问/授权/渲染/人类接管）
_INTERACTION_UI_TOOLS: frozenset[str] = frozenset(
    {
        "ask_question_tool",
        "request_directory_tool",
        "render_ui_tool",
        "update_ui_data_tool",
        "browser_ask_human_tool",
    }
)


def is_mutating_tool(tool_name: str) -> bool:
    """Return True when the tool mutates workspace or external state (effectful).

    SSOT used by Cron post-run verification to decide whether a run needs an
    adversarial-reviewer pass. The static alias set is authoritative; everything
    else resolves via registry metadata (fail-closed: unknown tools assumed
    effectful, since a side effect must never go unverified).
    """
    if tool_name in _MUTATION_TOOLS:
        return True
    return not resolve_safety_metadata(tool_name).is_read_only


_rejection_count: int = 0
_forced_finish: bool = False


def reset_completion_guard() -> None:
    """Reset guard state — call at the start of each agent run."""
    global _rejection_count, _forced_finish
    _rejection_count = 0
    _forced_finish = False


@tool(COMPLETION_CHECK_TOOL_NAME)
def _completion_check_tool(
    workspace_root: str = "",
    force_fail: bool = False,
    evidence_reason: str = "",
    deliverable_write_reason: str = "",
) -> str:
    """Generate a task-aware verification checklist before finishing.

    Review the session's tool-call history and produce a checklist of items
    to verify (tests, lint, type-check, browser state, execution results)
    before delivering the final answer.
    """
    if force_fail:
        return (
            " CRITICAL SYSTEM DIRECTIVE: You have failed to verify your work multiple times. "
            "You are now permitted to finish the task, but you MUST include a clear warning "
            "in your final response to the user stating that you were unable to successfully "
            "verify the changes (e.g., tests failed or were not run) and that they should "
            "manually review the work."
        )

    if evidence_reason.strip():
        return (
            " CRITICAL COMPLETION CHECK: This response appears to require external evidence, "
            "but no successful evidence-gathering tools were observed in this run.\n"
            f"Reason: {evidence_reason}\n"
            "Before finishing, run at least one successful evidence step (web_search_tool, "
            "web_fetch_tool, browser evidence tools, or MCP tools), then synthesize the answer."
        )

    if deliverable_write_reason.strip():
        return (
            " CRITICAL COMPLETION CHECK: Deliverable write claim without tool evidence.\n"
            f"Reason: {deliverable_write_reason}\n"
            "Before finishing, call file_write_tool or file_edit_tool to persist the file, "
            "or revise the response to remove the false write claim."
        )

    from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
        get_loop_guard,
    )

    guard = get_loop_guard()
    records = list(guard._window)
    checklist_str, _ = _build_checklist(records, workspace_root=workspace_root)
    return checklist_str


_RERUN_TIMEOUT_SECONDS: int = 120


async def _rerun_verification_in_sandbox(command: str) -> bool:
    """Execute a verification command independently in the sandbox.

    Returns True only when the command exits with code 0. Any executor
    unavailability or execution failure returns False (fail-closed).
    """
    try:
        from myrm_agent_harness.toolkits.code_execution.executors.base import (
            get_executor,
        )
        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            ExecutionContext,
        )

        executor = get_executor()
        if not executor:
            logger.warning(
                "[CompletionGuard] Sandbox executor unavailable — skipping independent re-run."
            )
            return False

        context = ExecutionContext(code=command, timeout=_RERUN_TIMEOUT_SECONDS)
        result = await executor.execute_bash(context)

        if result.exit_code == 0:
            return True

        logger.warning(
            "[CompletionGuard] Independent re-run failed (exit_code=%d): %s",
            result.exit_code,
            (result.stderr or result.stdout or "")[:500],
        )
        return False
    except Exception:
        logger.warning(
            "[CompletionGuard] Independent re-run raised exception.", exc_info=True
        )
        return False


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
    from messages that already contain a substantive final answer. Only tools
    that are guaranteed side-effect free AND carry no interaction/UI function
    are stripped; effectful calls and interaction/UI carriers are preserved.

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

    async def aafter_model(
        self, state: dict[str, Any], runtime: Any
    ) -> dict[str, Any] | None:
        """Intercept completion attempts and inject verification when critical errors exist."""
        global _rejection_count, _forced_finish
        if not self._enabled or _forced_finish:
            return None

        messages = state.get("messages", [])
        if not messages:
            return None

        last_ai_msg = next(
            (msg for msg in reversed(messages) if isinstance(msg, AIMessage)), None
        )
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
                tc.get("name") in finish_tool_names
                for tc in last_ai_msg.tool_calls
                if isinstance(tc, dict)
            )
            if has_finish_tool:
                is_attempting_completion = True

        if not is_attempting_completion:
            # --- Mixed Message Guard ---
            if last_ai_msg.content and last_ai_msg.tool_calls:
                content_str = (
                    last_ai_msg.content
                    if isinstance(last_ai_msg.content, str)
                    else str(last_ai_msg.content)
                )
                if _is_substantive_final_response(content_str):
                    has_non_strippable = any(
                        is_mutating_tool(str(tc.get("name", "")))
                        or str(tc.get("name", "")) in _INTERACTION_UI_TOOLS
                        for tc in last_ai_msg.tool_calls
                        if isinstance(tc, dict)
                    )
                    if not has_non_strippable:
                        # 防假完成：用户请求外部/新鲜数据但会话中尚无成功证据时，
                        # 保留只读工具调用让 Agent 真正获取数据，避免未核实内容直接到达用户。
                        from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
                            get_loop_guard,
                        )

                        guard = get_loop_guard()
                        window_records = list(guard._window)
                        filtered = [
                            r for r in window_records if not r.tool_name.startswith("_")
                        ]
                        requires_evidence = (
                            build_external_evidence_reason(
                                messages=messages,
                                records=filtered,
                            )
                            is not None
                        )
                        if requires_evidence:
                            return None
                        logger.info(
                            "[CompletionGuard] Mixed message detected: content is substantive "
                            "final response with %d read-only tool_calls — stripping to terminate early.",
                            len(last_ai_msg.tool_calls),
                        )
                        patched = deepcopy(last_ai_msg)
                        patched.tool_calls = []
                        return {"messages": [patched]}
            return None

        from myrm_agent_harness.agent.middlewares.tool_interceptor_middleware import (
            get_loop_guard,
        )

        guard = get_loop_guard()
        records = list(guard._window)
        filtered_records = [r for r in records if not r.tool_name.startswith("_")]

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
        evidence_reason = build_external_evidence_reason(
            messages=messages,
            records=filtered_records,
        )
        deliverable_write_reason: str | None = None
        if last_ai_msg.content:
            content_str = (
                last_ai_msg.content
                if isinstance(last_ai_msg.content, str)
                else str(last_ai_msg.content)
            )
            deliverable_write_reason = check_deliverable_write_claim(
                content_str, filtered_records
            )
        if evidence_reason is not None:
            has_critical_errors = True
        if deliverable_write_reason is not None:
            has_critical_errors = True

        if not has_critical_errors:
            return None

        # --- INDEPENDENT RE-RUN (temporal violation only) ---
        # Only triggered when the critical error is a temporal violation: code was
        # modified AFTER the last successful verification. Other critical errors
        # (no verification, failed verification, empty tests, execution failures)
        # must NOT be bypassed by independent re-run.
        if evidence_reason is None:
            has_code_writes = any(
                get_tool_group(r.tool_name) == ToolGroup.WRITE
                and _is_code_file(str(r.args.get("path", "")))
                for r in filtered_records
            )
            if has_code_writes and _has_post_verification_code_write(
                filtered_records, _CODE_EXTENSIONS
            ):
                rerun_cmd = _find_last_verification_cmd(filtered_records)
                if rerun_cmd:
                    rerun_passed = await _rerun_verification_in_sandbox(rerun_cmd)
                    if rerun_passed:
                        logger.info(
                            "[CompletionGuard] Independent re-run of '%s' passed — allowing completion.",
                            rerun_cmd,
                        )
                        return None

        # --- CRITICAL BLOCKING MODE ---
        current_rejections = _rejection_count

        if current_rejections >= self._max_rejections:
            logger.error(
                "[CompletionGuard] Max rejections (%d) reached. Allowing agent to finish despite critical errors.",
                self._max_rejections,
            )
            _forced_finish = True
            tool_call_id = f"call_{uuid.uuid4().hex[:24]}"
            forced_args: dict[str, object] = {
                "workspace_root": (str(workspace_root) if workspace_root else ""),
                "force_fail": True,
            }
            if evidence_reason is not None:
                forced_args["evidence_reason"] = evidence_reason
            if deliverable_write_reason is not None:
                forced_args["deliverable_write_reason"] = deliverable_write_reason
            patched = deepcopy(last_ai_msg)
            patched.tool_calls = [
                {
                    "name": COMPLETION_CHECK_TOOL_NAME,
                    "args": forced_args,
                    "id": tool_call_id,
                    "type": "tool_call",
                }
            ]
            return {"messages": [patched]}

        _rejection_count = current_rejections + 1
        logger.warning(
            "[CompletionGuard] Critical errors found. Blocking completion (rejection %d/%d).",
            current_rejections + 1,
            self._max_rejections,
        )

        tool_call_id = f"call_{uuid.uuid4().hex[:24]}"
        tool_args: dict[str, object] = {
            "workspace_root": str(workspace_root) if workspace_root else ""
        }
        if evidence_reason is not None:
            tool_args["evidence_reason"] = evidence_reason
        if deliverable_write_reason is not None:
            tool_args["deliverable_write_reason"] = deliverable_write_reason
        patched = deepcopy(last_ai_msg)
        patched.tool_calls = [
            {
                "name": COMPLETION_CHECK_TOOL_NAME,
                "args": tool_args,
                "id": tool_call_id,
                "type": "tool_call",
            }
        ]
        return {"messages": [patched]}


__all__ = [
    "COMPLETION_CHECK_TOOL_NAME",
    "CompletionGuard",
    "classify_verification",
    "is_mutating_tool",
    "reset_completion_guard",
]
