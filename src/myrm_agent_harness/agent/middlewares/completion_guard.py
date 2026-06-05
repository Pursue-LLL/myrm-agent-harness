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
- agent.security.guards.loop_guard_types::CallRecord, ToolGroup, SuccessLevel (POS: loop types)

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

from myrm_agent_harness.agent.security.guards.loop_guard_types import (
    CallRecord,
    SuccessLevel,
    ToolGroup,
    VerificationCategory,
    get_tool_group,
)

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
        "bash_tool",
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
    }
)

_rejection_count: int = 0

_VERIFICATION_PATTERNS: dict[str, VerificationCategory] = {
    "pytest": VerificationCategory.TEST,
    "python -m pytest": VerificationCategory.TEST,
    "npm test": VerificationCategory.TEST,
    "npm run test": VerificationCategory.TEST,
    "npx jest": VerificationCategory.TEST,
    "yarn test": VerificationCategory.TEST,
    "bun test": VerificationCategory.TEST,
    "pnpm test": VerificationCategory.TEST,
    "pnpm run test": VerificationCategory.TEST,
    "deno test": VerificationCategory.TEST,
    "cargo test": VerificationCategory.TEST,
    "go test": VerificationCategory.TEST,
    "dotnet test": VerificationCategory.TEST,
    "mvn test": VerificationCategory.TEST,
    "gradle test": VerificationCategory.TEST,
    "vitest": VerificationCategory.TEST,
    "unittest": VerificationCategory.TEST,
    "python": VerificationCategory.TEST,
    "node": VerificationCategory.TEST,
    "ts-node": VerificationCategory.TEST,
    "bun run": VerificationCategory.TEST,
    "deno run": VerificationCategory.TEST,
    "go run": VerificationCategory.TEST,
    "ruby": VerificationCategory.TEST,
    "php": VerificationCategory.TEST,
    "gcc": VerificationCategory.BUILD,
    "g++": VerificationCategory.BUILD,
    "javac": VerificationCategory.BUILD,
    "java": VerificationCategory.TEST,
    "ruff check": VerificationCategory.LINT,
    "ruff format": VerificationCategory.LINT,
    "eslint": VerificationCategory.LINT,
    "flake8": VerificationCategory.LINT,
    "pylint": VerificationCategory.LINT,
    "biome check": VerificationCategory.LINT,
    "biome lint": VerificationCategory.LINT,
    "prettier": VerificationCategory.LINT,
    "black": VerificationCategory.LINT,
    "isort": VerificationCategory.LINT,
    "clippy": VerificationCategory.LINT,
    "golangci-lint": VerificationCategory.LINT,
    "mypy": VerificationCategory.TYPECHECK,
    "pyright": VerificationCategory.TYPECHECK,
    "tsc": VerificationCategory.TYPECHECK,
    "npx tsc": VerificationCategory.TYPECHECK,
    "cargo build": VerificationCategory.BUILD,
    "npm run build": VerificationCategory.BUILD,
    "yarn build": VerificationCategory.BUILD,
    "pnpm run build": VerificationCategory.BUILD,
    "bun run build": VerificationCategory.BUILD,
    "make build": VerificationCategory.BUILD,
    "go build": VerificationCategory.BUILD,
    "dotnet build": VerificationCategory.BUILD,
    "gradle build": VerificationCategory.BUILD,
}


def _is_command_at_boundary(cmd: str, pattern: str) -> bool:
    """Check if pattern matches at a word boundary (followed by space or end-of-string)."""
    return cmd == pattern or cmd.startswith(pattern + " ")


def classify_verification(tool_args: dict[str, object]) -> VerificationCategory | None:
    """Detect if a bash command is a verification action (test/lint/typecheck/build).

    Uses word-boundary matching to minimise false positives. For example,
    ``pip install pytest`` will NOT match because ``pytest`` does not appear
    at a command boundary, and ``npm test-helper`` will NOT match ``npm test``
    because the pattern is followed by ``-`` instead of a space or end-of-string.
    """
    command = str(tool_args.get("command", "")).strip()
    if not command:
        return None
    cmd_lower = command.lower()
    for pattern, category in sorted(_VERIFICATION_PATTERNS.items(), key=lambda x: len(x[0]), reverse=True):
        if _is_command_at_boundary(cmd_lower, pattern):
            return category
        for sep in (" && ", "; "):
            idx = cmd_lower.find(sep + pattern)
            if idx >= 0:
                tail = cmd_lower[idx + len(sep) :]
                if _is_command_at_boundary(tail, pattern):
                    return category
    return None


def reset_completion_guard() -> None:
    """Reset guard state — call at the start of each agent run."""
    global _rejection_count
    _rejection_count = 0


def _build_checklist(records: list[CallRecord], workspace_root: str | None = None) -> tuple[str, bool]:
    """Generate a verification checklist from LoopGuard CallRecords.

    Groups tool calls by semantic category and produces targeted
    verification items based on what the Agent actually did.

    Internal tool records (``_``-prefixed) are filtered out first.
    ``has_critical_errors`` is True only when code files were modified
    without passing verification — this drives the CRITICAL blocking path.

    Returns:
        Tuple of (checklist_string, has_critical_errors)
    """
    records = [r for r in records if not r.tool_name.startswith("_")]

    groups: dict[ToolGroup, list[CallRecord]] = {}
    for rec in records:
        grp = get_tool_group(rec.tool_name)
        groups.setdefault(grp, []).append(rec)

    verifications = [r for r in records if r.verification_type is not None]
    failed_verifications = [r for r in verifications if r.success_level == SuccessLevel.FAILURE]

    items: list[str] = []
    has_critical_errors = False
    has_writes = ToolGroup.WRITE in groups

    if has_writes:
        write_records = groups[ToolGroup.WRITE]
        write_tools = {r.tool_name for r in write_records}

        # Check if any written file is a code file that requires testing
        has_code_writes = False
        code_extensions = {
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".rs",
            ".go",
            ".java",
            ".cpp",
            ".c",
            ".h",
            ".hpp",
            ".cs",
            ".php",
            ".rb",
            ".swift",
        }
        for rec in write_records:
            path = str(rec.args.get("path", "")).lower()
            if any(path.endswith(ext) for ext in code_extensions):
                has_code_writes = True
                break

        if not verifications:
            if has_code_writes:
                has_critical_errors = True
                items.append(
                    f"CRITICAL: Code files were modified ({', '.join(sorted(write_tools))}) but NO verification "
                    "(tests, lint, type-check) was executed. You MUST run relevant checks before finishing."
                )
            else:
                items.append(
                    f" Files were modified ({', '.join(sorted(write_tools))}) but NO verification was executed. "
                    "If these are text/data files, please manually confirm they meet the requirements."
                )
        elif failed_verifications:
            has_critical_errors = True
            failed_types = {r.verification_type.value for r in failed_verifications if r.verification_type}
            items.append(
                f"CRITICAL: Verification failed for: {', '.join(sorted(failed_types))}. You MUST fix failing checks before finishing."
            )
        else:
            verified_types = {r.verification_type.value for r in verifications if r.verification_type}
            items.append(
                f"File modifications ({', '.join(sorted(write_tools))}) verified via "
                f"{', '.join(sorted(verified_types))} — confirm results match expectations."
            )

    if ToolGroup.BROWSER in groups:
        browser_tools = {r.tool_name for r in groups[ToolGroup.BROWSER]}
        items.append(
            f"Verify browser interactions ({', '.join(sorted(browser_tools))}) "
            "produced expected results — take a snapshot to confirm page state."
        )
    elif has_writes:
        frontend_render_exts: frozenset[str] = frozenset(
            {".tsx", ".jsx", ".vue", ".svelte", ".astro", ".css", ".scss", ".less", ".html"}
        )
        non_render_path_segments: frozenset[str] = frozenset(
            {
                "test",
                "tests",
                "spec",
                "specs",
                "__tests__",
                "__test__",
                "store",
                "stores",
                "service",
                "services",
                "util",
                "utils",
                "hook",
                "hooks",
                "api",
                "types",
                "constants",
                "schemas",
                "mocks",
                "mock",
            }
        )
        non_render_filename_patterns: tuple[str, ...] = (
            ".test.",
            ".spec.",
            ".d.ts",
            ".config.",
            ".stories.",
        )

        def _is_non_render_path(p: str) -> bool:
            segments = set(p.replace("\\", "/").split("/"))
            if segments & non_render_path_segments:
                return True
            filename = p.rsplit("/", 1)[-1]
            return any(pat in filename for pat in non_render_filename_patterns)

        has_render_file_writes = any(
            any(path_lower.endswith(ext) for ext in frontend_render_exts) and not _is_non_render_path(path_lower)
            for rec in groups[ToolGroup.WRITE]
            if (path_lower := str(rec.args.get("path", "")).lower())
        )
        if has_render_file_writes:
            items.append(
                "WARNING: Frontend rendering files were modified but NO browser "
                "verification was performed. Consider using browser tools to "
                "visually confirm the changes render correctly."
            )

        code_exts = {".py", ".ts", ".tsx", ".go", ".rs"}
        has_code_symbol_writes = any(
            any(str(rec.args.get("path", "")).lower().endswith(ext) for ext in code_exts)
            for rec in groups[ToolGroup.WRITE]
        )
        used_impact = any(r.tool_name == "code_impact_tool" for r in records)
        if has_code_symbol_writes and not used_impact:
            items.append(
                "WARNING: Code files were modified but NO code_impact_tool analysis was performed. "
                "Consider running impact analysis before finalizing changes."
            )

    reported_failures: set[str] = set()

    if ToolGroup.EXECUTE in groups:
        exec_tools = {r.tool_name for r in groups[ToolGroup.EXECUTE]}
        failures = [r for r in groups[ToolGroup.EXECUTE] if r.success_level == SuccessLevel.FAILURE]
        item = f"Verify execution results from {', '.join(sorted(exec_tools))} match expectations."
        if failures:
            reported_failures.update(r.tool_name for r in failures)
            if has_writes:
                has_critical_errors = True
                item = f"CRITICAL: {len(failures)} execution(s) failed in {', '.join(sorted(exec_tools))}. You MUST resolve them."
            else:
                item = f"WARNING: {len(failures)} execution(s) had failures in {', '.join(sorted(exec_tools))}. Review if they affect the answer."
        items.append(item)

    other_failures = [
        r for r in records if r.success_level == SuccessLevel.FAILURE and r.tool_name not in reported_failures
    ]
    if other_failures:
        failed_tools = {r.tool_name for r in other_failures}
        if has_writes:
            has_critical_errors = True
            items.append(
                f"CRITICAL: Address {len(other_failures)} unresolved failure(s) in: {', '.join(sorted(failed_tools))}."
            )
        else:
            items.append(
                f"WARNING: {len(other_failures)} failure(s) in {', '.join(sorted(failed_tools))}. Review if they affect the answer."
            )

    if not items:
        items.append("Confirm the response fully addresses the user's request.")

    lines = ["Before providing your final answer, verify the following:"]

    # Check for incomplete plan steps
    if workspace_root:
        try:
            from myrm_agent_harness.agent.sub_agents.planner import PlannerStorage
            from myrm_agent_harness.toolkits.storage.local import (
                LocalStorageBackend,
            )

            storage_provider = LocalStorageBackend(workspace_root)
            planner_storage = PlannerStorage(storage_provider, prefix="planner_")
            plan = planner_storage.load_plan()
            if plan:
                uncompleted_steps = [
                    step for step in plan.steps if step.status != "completed" and step.status != "skipped"
                ]
                if uncompleted_steps:
                    if has_writes:
                        has_critical_errors = True
                        lines.append("  CRITICAL: You have uncompleted steps in your Goal Plan!")
                    else:
                        lines.append("  WARNING: You have uncompleted steps in your Goal Plan.")
                    for step in uncompleted_steps:
                        lines.append(f" - Step {step.step_id}: {step.description} (Status: {step.status})")
                    if has_writes:
                        lines.append(
                            " You MUST complete these steps and call `planner_tool(action='update')` before finishing."
                        )
                    else:
                        lines.append(" Review if remaining steps are still needed for your answer.")
                    lines.append("")
        except Exception as e:
            logger.warning("[CompletionGuard] Failed to load plan for checklist: %s", e)

    for i, item in enumerate(items, 1):
        lines.append(f" {i}. {item}")
    lines.append("")
    lines.append("RULES:")
    lines.append('- "Looks correct" is NOT verification — run the actual check.')
    lines.append("- Tests you wrote need independent verification — confirm they catch real bugs.")
    lines.append('- "Should work" is NOT "verified" — execute and confirm.')
    lines.append("- If you cannot verify something, state what and why explicitly.")
    lines.append("")

    if has_critical_errors:
        lines.append(" STATUS: REJECTED. You have CRITICAL errors. You CANNOT finish the task until they are resolved.")
    else:
        lines.append(
            " STATUS: WARNINGS ONLY. If all checks pass, provide your final answer. If issues found, fix them first."
        )

    return "\n".join(lines), has_critical_errors


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
