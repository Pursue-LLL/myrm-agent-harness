"""Goal tools for the agent.

[INPUT]
- langchain_core.tools::tool (POS: LangChain tool decorator)
- agent.goals.types::GoalStatus (POS: Goal status enum)
- agent.goals.finalizer::finalize_goal_complete (POS: SSOT COMPLETE path)

[OUTPUT]
- complete_goal_tool: Tool to mark goal as complete.
- create_goal_tools: Factory function to create goal tools.

[POS]
Provides the LLM completion tool for the Goal engine. Objective reminders are
handled by goal_focus_middleware on user-initiated turns; continuation prompts
cover auto-continue turns. Semantic Judge is the primary completion path; this
tool is for explicit agent declaration after work is truly done.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool, tool

if TYPE_CHECKING:
    from myrm_agent_harness.agent.goals.protocols import GoalProvider

logger = logging.getLogger(__name__)


def create_goal_tools(goal_provider: GoalProvider, session_id: str) -> list[BaseTool]:
    """Create goal tools bound to a specific session and provider."""

    @tool("complete_goal_tool")
    async def complete_goal() -> str:
        """Mark the active goal as fully complete.

        Use ONLY when the objective has ACTUALLY been achieved and NO required work remains.
        Do not call this merely because the budget is nearly exhausted or because you are
        stopping work. The semantic judge may also mark completion automatically.
        """
        goal = await goal_provider.get_active_goal(session_id)
        if not goal:
            return "Error: No active goal to complete."

        try:
            from myrm_agent_harness.agent.goals.types import GoalStatus

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
                    if goal and getattr(goal, "verification_retries", 0) >= max_retries:
                        await goal_provider.update_status(goal.goal_id, GoalStatus.NEEDS_HUMAN_REVIEW)
                        return f"Error: Verification failed {max_retries} times. Goal has been paused for human review. Reason: {result.reason}\nLogs:\n{result.error_logs}"
                    return f"Error: Verification failed. You MUST fix this before completing. Reason: {result.reason}\nLogs:\n{result.error_logs}"

            from myrm_agent_harness.agent.goals.finalizer import finalize_goal_complete

            await finalize_goal_complete(
                goal_provider,
                goal,
                source="agent_tool",
                defer_terminal_callback=True,
            )
            return f"Successfully marked goal {goal.goal_id} as COMPLETE. You have achieved the objective."
        except Exception as e:
            return f"Error completing goal: {e}"

    return [complete_goal]
