"""Goal tools for the agent.

[INPUT]
- langchain_core.tools::tool (POS: LangChain tool decorator)
- agent.goals.types::GoalStatus (POS: Goal status enum)
- agent.goals.finalizer::finalize_goal_complete (POS: SSOT COMPLETE path)
- utils.locale::is_chinese (POS: BCP-47 Chinese detection for description locale)

[OUTPUT]
- complete_goal_tool: Tool to mark goal as complete.
- create_goal_tools: Factory function to create goal tools.
- COMPLETE_GOAL_TOOL_DESCRIPTION_EN / _ZH: Tool description constants.
- resolve_complete_goal_tool_description: Dynamic description resolver.

[POS]
Provides the LLM completion tool for the Goal engine. Objective reminders are
handled by goal_focus_middleware on user-initiated turns; continuation prompts
cover auto-continue turns. Semantic Judge is the primary completion path; this
tool is for explicit agent declaration after work is truly done.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.utils.locale import is_chinese

if TYPE_CHECKING:
    from myrm_agent_harness.agent.goals.protocols import GoalProvider

logger = logging.getLogger(__name__)

COMPLETE_GOAL_TOOL_DESCRIPTION_EN: Final[str] = """
Mark the active long-term goal as fully complete.

## When to Call:
- Call ONLY when the entire objective has ACTUALLY been achieved and all required deliverables are verified.
- All planned subtasks/todos must be marked as completed.
- All defined acceptance criteria must be satisfied.

## Rules:
- Do NOT call this tool merely because budget/turns are running low or because you are blocked.
- Calling this tool triggers final verification and concludes the goal lifecycle.
""".strip()

COMPLETE_GOAL_TOOL_DESCRIPTION_ZH: Final[str] = """
将当前活跃的长期目标标记为完全完成。

## 调用时机：
- 仅在整个目标已真正达成、且所有必要交付物均已完成并验证无误时调用。
- 前置条件：所有规划的子任务/待办事项必须已标记为 completed 状态。
- 所有定义的验收标准（Acceptance Criteria）必须全部满足。

## 约束原则：
- 严禁因轮数耗尽、预算不足或遇到阻碍而提前调用此工具宣布完成。
- 调用本工具将触发最终验收门禁并正式结束目标生命周期。
""".strip()


def resolve_complete_goal_tool_description(locale: str | None = None) -> str:
    """Resolve LLM-facing complete_goal_tool description based on locale."""
    if is_chinese(locale):
        return COMPLETE_GOAL_TOOL_DESCRIPTION_ZH
    return COMPLETE_GOAL_TOOL_DESCRIPTION_EN


def create_goal_tools(
    goal_provider: GoalProvider,
    session_id: str,
    locale: str | None = None,
) -> list[BaseTool]:
    """Create goal tools bound to a specific session and provider."""

    @tool(
        "complete_goal_tool",
        description=resolve_complete_goal_tool_description(locale),
    )
    async def complete_goal() -> str:
        goal = await goal_provider.get_active_goal(session_id)
        if not goal:
            return "Error: No active goal to complete."

        try:
            from myrm_agent_harness.agent.goals.types import GoalStatus

            if getattr(goal, "status", None) == GoalStatus.COMPLETE:
                return f"Goal {goal.goal_id} is already completed."

            if getattr(goal, "acceptance_criteria", None):
                from myrm_agent_harness.agent.goals.verification import (
                    VerificationGatekeeper,
                )

                gatekeeper = VerificationGatekeeper(goal.acceptance_criteria)
                result = await gatekeeper.verify_all(goal_provider)
                if not result.passed:
                    max_retries = 3
                    await goal_provider.increment_verification_retries(goal.goal_id)
                    goal = await goal_provider.get_active_goal(session_id)
                    retries = getattr(goal, "verification_retries", 0) if goal else 1

                    # Build structured diagnostic matrix for all criteria
                    matrix_lines: list[str] = [
                        "### Goal Verification Diagnostic Matrix",
                        "| Criterion | Status | Details / Logs |",
                        "| :--- | :--- | :--- |",
                    ]
                    for r in result.per_criterion:
                        status_str = "PASSED" if r.passed else "FAILED"
                        detail_msg = (r.reason or "").replace("\n", " ")
                        if r.error_logs:
                            detail_msg += f" (Log: {r.error_logs.strip()[:200]})"
                        label = r.criterion_label or "Unnamed Criterion"
                        matrix_lines.append(f"| {label} | {status_str} | {detail_msg} |")

                    diagnostic_report = "\n".join(matrix_lines)

                    if goal and retries >= max_retries:
                        await goal_provider.update_status(goal.goal_id, GoalStatus.NEEDS_HUMAN_REVIEW)
                        return (
                            f"Error: Verification failed {max_retries} times. Goal has been paused for human review.\n\n"
                            f"{diagnostic_report}\n\n"
                            f"Reason: {result.reason}\nLogs:\n{result.error_logs}"
                        )

                    return (
                        f"Error: Verification failed (attempt {retries}/{max_retries}). You MUST fix the failed criteria before completing.\n\n"
                        f"{diagnostic_report}\n\n"
                        f"Reason: {result.reason}\nLogs:\n{result.error_logs}"
                    )

            from myrm_agent_harness.agent.goals.finalizer import finalize_goal_complete

            await finalize_goal_complete(
                goal_provider,
                goal,
                source="agent_tool",
                defer_terminal_callback=True,
            )
            return f"Successfully marked goal {goal.goal_id} as COMPLETE. You have achieved the objective."
        except Exception as e:
            logger.error("Goal completion failed: %s", e)
            return f"Error completing goal: {e}"

    return [complete_goal]
