"""Goal tools for the agent.

[INPUT]
- langchain_core.tools::tool (POS: LangChain tool decorator)
- agent.goals.types::GoalStatus (POS: Goal status enum)

[OUTPUT]
- get_goal_tool: Tool to get current goal status.
- update_goal_tool: Tool to mark goal as complete.
- create_goal_tools: Factory function to create goal tools.

[POS]
Provides tools for the LLM to interact with the Goal engine.
Crucially, update_goal only allows marking the goal as COMPLETE.
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

    @tool("get_goal_status_tool")
    async def get_goal_status() -> str:
        """Get the current active goal for this session, including its objective, budget, and usage.

        Use this to remind yourself of the overall objective and check how much budget remains.
        """
        goal = await goal_provider.get_active_goal(session_id)
        if not goal:
            return "No active goal for this session."

        budget_info = []
        if goal.budget:
            if goal.budget.max_tokens is not None:
                budget_info.append(f"Tokens: {goal.tokens_used} / {goal.budget.max_tokens}")
            if goal.budget.max_usd is not None:
                budget_info.append(f"Cost: ${goal.cost_usd:.4f} / ${goal.budget.max_usd:.4f}")
            if goal.budget.max_time_seconds is not None:
                budget_info.append(f"Time: {goal.time_used_seconds}s / {goal.budget.max_time_seconds}s")

        budget_str = ", ".join(budget_info) if budget_info else "No budget limits"

        return f"""Active Goal:
ID: {goal.goal_id}
Objective: {goal.objective}
Status: {goal.status.value}
Budget/Usage: {budget_str}
"""

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

    return [get_goal_status, update_goal_status]
