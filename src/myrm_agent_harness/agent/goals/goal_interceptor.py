"""Goal Interception and Planning.

[INPUT]
- .protocol::GoalProvider (POS: Goal provider protocol)
- agent.sub_agents.planner::PlannerAgent, PlannerConfig, PlannerStorage (POS: Planner sub-agent)
- toolkits.storage.base::StorageProvider (POS: Storage provider)

[OUTPUT]
- intercept_goal_and_plan: Intercepts a goal request and generates a plan if missing.

[POS]
Handles the pre-execution phase of a goal. If a goal is active but has no plan,
it invokes the PlannerAgent to generate one before the main agent loop starts.
"""

import logging

from langchain_core.language_models import BaseChatModel
from langgraph.types import interrupt

from myrm_agent_harness.agent.goals.protocols import GoalProvider
from myrm_agent_harness.agent.goals.types import GoalStatus
from myrm_agent_harness.agent.sub_agents.planner import (
    PlannerAgent,
    PlannerConfig,
    PlannerStorage,
)
from myrm_agent_harness.toolkits.storage.base import StorageProvider

logger = logging.getLogger(__name__)


async def intercept_goal_and_plan(
    goal_provider: GoalProvider,
    session_id: str,
    query: str,
    llm: BaseChatModel,
    storage_provider: StorageProvider,
) -> None:
    """Check if an active goal exists and needs a plan. If so, generate it.

    This should be called before the main agent loop starts.
    """
    goal = await goal_provider.get_active_goal(session_id)
    if not goal:
        return

    # Check if a plan already exists for this session
    planner_storage = PlannerStorage(storage_provider, prefix="planner_")
    existing_plan = await planner_storage.load_plan()

    if existing_plan:
        logger.info("Goal %s already has a plan. Skipping generation.", goal.goal_id)
        return

    logger.info("Goal %s has no plan. Generating one now...", goal.goal_id)

    try:
        config = PlannerConfig()
        planner = PlannerAgent(llm, planner_storage, config)

        task_desc = f"Goal Objective: {goal.objective}\n\nCurrent Request: {query}"

        await planner.create_plan(task_desc)
        logger.info(
            "Successfully generated plan for goal %s. Suspending for user approval.",
            goal.goal_id,
        )

        await goal_provider.update_status(goal.goal_id, GoalStatus.PENDING_APPROVAL)

        if goal.auto_approve:
            logger.info(
                "Goal %s has auto_approve=True. Skipping approval interrupt.",
                goal.goal_id,
            )
            await goal_provider.update_status(goal.goal_id, GoalStatus.ACTIVE)
            return

        interrupt({
            "type": "goal_approval_required",
            "goal_id": goal.goal_id,
            "message": "Plan generated. Waiting for user approval.",
        })

    except Exception as e:
        logger.error("Failed to generate plan for goal %s: %s", goal.goal_id, e)
        # Roll back to CANCELLED so the frontend doesn't show a stale
        # "waiting for approval" state with no plan to approve.
        try:
            await goal_provider.update_status(goal.goal_id, GoalStatus.CANCELLED)
        except Exception:
            logger.warning(
                "Failed to roll back goal %s status after plan generation error",
                goal.goal_id,
                exc_info=True,
            )
        raise RuntimeError(
            f"Goal execution aborted because plan generation failed: {e}"
        ) from e

__all__ = ["intercept_goal_and_plan"]
