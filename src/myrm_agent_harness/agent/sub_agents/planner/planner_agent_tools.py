"""Planner Tool — wraps PlannerAgent as a LangChain Tool.

[INPUT]
- agent.sub_agents.planner::PlannerAgent, PlannerConfig (POS: Planner sub-agent)
- toolkits.storage.base::StorageProvider (POS: storage protocol/interface)
- langchain_core.language_models::BaseChatModel (POS: LangChain LLM base class)
- langchain_core.tools::tool (POS: LangChain tool decorator)

[OUTPUT]
- create_planner_tool: factory function to create Planner tool

[POS]
Wraps PlannerAgent as a LangChain Tool so the main Agent can invoke planning.
Lives inside `agent/sub_agents/planner/` alongside the core planner implementation.

Example:
    >>> from myrm_agent_harness.agent.sub_agents.planner.planner_agent_tools import create_planner_tool
    >>> planner_tool = create_planner_tool(llm, storage)
    >>> result = await planner_tool.ainvoke({"action": "create", "task_description": "Build a web scraper"})
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from langchain_core.callbacks import dispatch_custom_event
from langchain_core.tools import tool

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.sub_agents.planner.config import PlannerConfig
    from myrm_agent_harness.toolkits.storage.base import StorageProvider

logger = logging.getLogger(__name__)


def create_planner_tool(
    llm: BaseChatModel,
    storage_backend: StorageProvider,
    planner_llm: BaseChatModel | None = None,
    planner_config: PlannerConfig | None = None,
    available_skills: list[tuple[str, str]] | None = None,
) -> BaseTool:
    """Create planner tool (wraps PlannerAgent)

    Wraps PlannerAgent sub-agent as a LangChain tool for main agent use.

    Args:
        llm: Main agent's language model (as fallback)
        storage_backend: Storage backend for saving plans
        planner_llm: Planner-specific language model (optional)
        planner_config: Planner configuration (optional)
        available_skills: List of (name, description) tuples for skill awareness.
            When provided, the Planner can reference these skills in plan steps.

    Returns:
        Planner tool (LangChain BaseTool)

    Example:
        >>> from myrm_agent_harness.agent.sub_agents.planner.planner_agent_tools import create_planner_tool
        >>> from myrm_agent_harness.toolkits.storage import StorageProvider
        >>> from myrm_agent_harness.agent.sub_agents.planner.config import PlannerConfig
        >>>
        >>> storage = StorageBackend.local("./workspace")
        >>> config = PlannerConfig(enable_3_strike=True, output_format="markdown")
        >>> planner = create_planner_tool(llm, storage, planner_config=config)
        >>>
        >>> # Using different model for planning
        >>> planner = create_planner_tool(llm, storage, planner_llm=haiku_llm)
    """
    from myrm_agent_harness.agent.sub_agents.planner.agent import PlannerAgent
    from myrm_agent_harness.agent.sub_agents.planner.config import (
        PlannerConfig,
        SkillSummary,
    )
    from myrm_agent_harness.agent.sub_agents.planner.storage import PlannerStorage

    _planner_llm = planner_llm or llm
    _config = planner_config or PlannerConfig()

    if available_skills:
        _config.available_skills = [SkillSummary(name=n, description=d) for n, d in available_skills]

    _storage = PlannerStorage(storage_backend, prefix=_config.storage_prefix)
    _planner = PlannerAgent(_planner_llm, _storage, _config)

    def _emit_plan_events(plan: object) -> None:
        """Emit TASKS_STEPS events for the plan to render as a tree in the UI."""
        # We use duck-typing to avoid circular imports if needed
        try:
            # Emit the root plan node
            dispatch_custom_event(
                "tasks_steps",
                {
                    "step_key": "planner_root",
                    "is_plan": True,
                    "status": "in_progress",
                    "data": [{"text": getattr(plan, "goal", "Task Plan")}],
                },
            )

            # Emit DAG structure via custom event
            nodes = []
            edges = []
            steps = getattr(plan, "steps", [])
            for step in steps:
                step_id = getattr(step, "step_id", "")
                status = getattr(step, "status", "pending")
                desc = getattr(step, "description", "")
                expected = getattr(step, "expected_output", "")
                risk = getattr(step, "risk_level", "low")
                deps = getattr(step, "dependencies", [])

                if step_id and desc:
                    nodes.append({
                        "id": step_id,
                        "data": {
                            "label": desc,
                            "status": status,
                            "expected_output": expected,
                            "risk_level": risk
                        }
                    })
                    for dep in deps:
                        edges.append({
                            "id": f"e_{dep}_{step_id}",
                            "source": dep,
                            "target": step_id
                        })

            dispatch_custom_event(
                "dag_state_update",
                {
                    "nodes": nodes,
                    "edges": edges
                }
            )

            # Emit each step as a child of the root
            steps = getattr(plan, "steps", [])
            for step in steps:
                step_id = getattr(step, "step_id", "")
                status = getattr(step, "status", "pending")
                desc = getattr(step, "description", "")
                if step_id and desc:
                    # Map status to UI status
                    ui_status = status
                    if status == "in_progress":
                        ui_status = "running"
                    elif status == "completed":
                        ui_status = "success"
                    elif status == "skipped":
                        ui_status = "skipped"

                    dispatch_custom_event(
                        "tasks_steps",
                        {
                            "step_key": f"plan_step_{step_id}",
                            "parent_step_key": "planner_root",
                            "is_plan": True,
                            "status": ui_status,
                            "data": [{"text": desc}],
                        },
                    )
        except Exception as e:
            logger.warning("Failed to emit plan events: %s", e)

    @tool
    async def planner_tool(
        action: Literal["create", "update", "get"],
        task_description: str | None = None,
        completed_step_id: str | None = None,
        feedback: str | None = None,
        alignment_check: str | None = None,
    ) -> str:
        """Task planner — decomposes complex tasks into dependency-aware steps.

        ## SHOULD plan

        1. Multi-file / multi-module changes (≥3 files or ≥2 modules)
        2. Architectural decisions (new patterns, API design, component boundaries)
        3. Unclear or ambiguous requirements needing investigation
        4. Multiple valid approaches with trade-offs to evaluate
        5. Risky operations (migrations, breaking changes, permissions)

        ## Should NOT plan (execute directly)

        1. Single-file, well-scoped fixes (typo, obvious bug, style)
        2. User already provided step-by-step instructions
        3. Read-only queries (search, read, answer)

        GOOD: "Add authentication to the app" → plan (multi-file, architectural)
        BAD:  "Fix typo in README" → just do it

        Args:
            action: Action type
                - "create": Create new plan (requires task_description)
                - "update": Update existing plan (optional completed_step_id, feedback, and alignment_check)
                - "get": Get current plan
            task_description: Task description (required for create)
            completed_step_id: Completed step ID (for update)
            feedback: Execution feedback (for update, e.g., issues encountered)
            alignment_check: Cognitive Alignment Check (REQUIRED for update when marking a step complete).
                You MUST summarize the changes made in this step and explicitly explain how they align
                with the original overall goal. If you detect any specification drift, state it here
                and propose corrections in the feedback parameter.

        Returns:
            Plan in configured format (line/markdown/json)

        Example:
            # Create plan
            planner_tool(action="create", task_description="Build a Python web scraper")

            # Mark step complete with alignment check
            planner_tool(
                action="update",
                completed_step_id="step_1",
                alignment_check="I successfully scraped the target URL. This aligns with the original goal of extracting product data because the raw HTML is now available for parsing."
            )

            # Update with feedback
            planner_tool(
                action="update",
                completed_step_id="step_2",
                feedback="Target site requires login, need to adjust approach",
                alignment_check="Attempted to parse data but hit a login wall. This deviates from the goal as we cannot get the data yet. Proposing a new step to handle auth."
            )

            # Get current plan
            planner_tool(action="get")
        """
        if action == "create":
            if not task_description:
                return "Error: task_description is required for creating a plan"

            plan = await _planner.create_plan(task_description)
            _emit_plan_events(plan)

            # Return in configured format
            if _config.output_format == "json":
                return plan.model_dump_json(indent=2)
            elif _config.output_format == "markdown":
                return plan.to_markdown()
            else:  # line format (default)
                return plan.to_line_format()

        if action == "update":
            current_plan = await _planner.get_current_plan()
            if not current_plan:
                return "Error: No existing plan found. Please create a plan first using action='create'"

            if completed_step_id and not alignment_check:
                return "Error: alignment_check is REQUIRED when marking a step as complete. You must explain how your changes align with the original goal to prevent specification drift."

            # 极致性能优化: Cognitive Forcing Function
            # 我们强制主智能体生成 alignment_check(生成 Token 即思考), 从而将其注意力拉回全局目标。
            # 但我们**不**将其传入 update_plan 触发 Planner 子智能体的重规划(避免 O(N) 的 LLM 调用延迟)。
            # 只有当主智能体显式提供 feedback(遇到问题)时, 才触发重规划。
            updated_plan = await _planner.update_plan(
                current_plan,
                completed_step_id,
                feedback,
            )
            _emit_plan_events(updated_plan)

            # Return ONLY a short summary to preserve prompt cache
            return updated_plan.to_summary()

        if action == "get":
            current_plan = await _planner.get_current_plan()
            if not current_plan:
                return "No plan exists. Use action='create' to create a new plan."
            _emit_plan_events(current_plan)

            # Return in configured format
            if _config.output_format == "json":
                return current_plan.model_dump_json(indent=2)
            elif _config.output_format == "markdown":
                return current_plan.to_markdown()
            else:  # line format (default)
                return current_plan.to_line_format()

        return f"Error: Unknown action: {action}"

    return planner_tool


__all__ = ["create_planner_tool"]
