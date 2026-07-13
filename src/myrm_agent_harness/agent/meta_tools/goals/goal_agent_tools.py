"""Goal tools for the agent.

[INPUT]
- langchain_core.tools::tool (POS: LangChain tool decorator)
- agent.goals.types::GoalStatus (POS: Goal status enum)

[OUTPUT]
- update_goal_tool: Tool to mark goal as complete.
- create_goal_tools: Factory function to create goal tools.

[POS]
Provides the LLM completion tool for the Goal engine. Objective reminders are
handled by goal_focus_middleware on user-initiated turns; continuation prompts
cover auto-continue turns.
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

    @tool("update_goal_status_tool")
    async def update_goal_status(status: str) -> str:
        """Update the active goal's status.

        Args:
            status: MUST be "complete". Use this ONLY when the objective has ACTUALLY been achieved
                   and NO required work remains. Do not mark a goal complete merely because the budget
                   is nearly exhausted or because you are stopping work.
        """
        if status.lower() != "complete":
            return "Error: You can only update the status to 'complete'. Pausing or changing budget is controlled by the user."

        goal = await goal_provider.get_active_goal(session_id)
        if not goal:
            return "Error: No active goal to update."

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

            await goal_provider.update_status(goal.goal_id, GoalStatus.COMPLETE)
            return f"Successfully marked goal {goal.goal_id} as COMPLETE. You have achieved the objective."
        except Exception as e:
            return f"Error updating goal: {e}"

    return [update_goal_status]
