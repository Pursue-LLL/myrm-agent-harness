"""Planner Agent - Independent Task Planning Sub-agent

A dedicated sub-agent for task planning with its own LLM and context.

Design principles (based on Manus):
1. Independent agent with own system prompt and context
2. Can use different model than main agent (e.g., lighter Haiku)
3. Structured output with Pydantic schemas
4. External reviewer perspective on tasks

Key features:
- Task planning and tracking
- 3-Strike Protocol for error handling
- Shadow sync (multiple output formats)
- Scratchpad pattern for context management

[INPUT]
- toolkits.storage::StorageProvider (POS: Planner Storage Adapter)

[OUTPUT]
- PlannerAgent: Planner sub-agent

[POS]
Planner Agent - Independent Task Planning Sub-agent
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage, SystemMessage

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from myrm_agent_harness.agent.sub_agents.planner.config import PlannerConfig
    from myrm_agent_harness.agent.sub_agents.planner.schemas import Plan
    from myrm_agent_harness.agent.sub_agents.planner.storage import PlannerStorage

# Import Plan at runtime to avoid circular dependency issues
from myrm_agent_harness.agent.sub_agents.planner.schemas import Plan

logger = logging.getLogger(__name__)


class PlannerAgent:
    """Planner sub-agent

    An independent agent focused on task planning.
    Uses its own LLM and storage, separate from main agent.

    Args:
        llm: Language model for planning
        storage: Storage adapter for persisting plans
        config: Planner configuration

    Example:
        >>> from myrm_agent_harness.agent.sub_agents.planner import (
        ...     PlannerAgent, PlannerConfig, PlannerStorage
        ... )
        >>> from myrm_agent_harness.toolkits.storage import StorageProvider
        >>>
        >>> storage_backend = StorageBackend.local("./workspace")
        >>> planner_storage = PlannerStorage(storage_backend)
        >>> config = PlannerConfig(enable_3_strike=True)
        >>>
        >>> planner = PlannerAgent(llm, planner_storage, config)
        >>> plan = await planner.create_plan("Build a web scraper")
    """

    def __init__(
        self,
        llm: BaseChatModel,
        storage: PlannerStorage,
        config: PlannerConfig | None = None,
    ):
        """Initialize planner agent

        Args:
            llm: Language model for planning
            storage: Storage adapter
            config: Configuration (uses defaults if not provided)
        """
        self.llm = llm
        self.storage = storage
        self.config = config or self._default_config()

        from myrm_agent_harness.agent.sub_agents.planner.prompts import (
            UPDATE_PLAN_PROMPT,
            get_planner_system_prompt,
        )

        base_prompt = get_planner_system_prompt(self.config.system_prompt)
        self.system_prompt = self._append_skill_awareness(base_prompt)
        self.update_prompt_template = self.config.update_prompt or UPDATE_PLAN_PROMPT

    @staticmethod
    def _default_config() -> PlannerConfig:
        """Get default config"""
        from myrm_agent_harness.agent.sub_agents.planner.config import PlannerConfig

        return PlannerConfig()

    def _append_skill_awareness(self, base_prompt: str) -> str:
        """Append available skills section to the system prompt.

        When skills are provided, the Planner can reference them in step
        descriptions so the executor knows which skill to load via
        ``skill_select_tool``.
        """
        skills = self.config.available_skills
        if not skills:
            return base_prompt

        lines = [
            "\n\n## Available Skills",
            "The executor has access to the following skills (loaded via skill_select_tool, NOT regular tools).",
            "When a step can benefit from a skill, mention it by name in the step description.",
            "",
        ]
        for s in skills:
            lines.append(f"- **{s.name}**: {s.description}")

        return base_prompt + "\n".join(lines)

    async def _save_plan_if_enabled(self, plan: Plan) -> None:
        """Save plan if shadow sync is enabled

        Args:
            plan: Plan to save
        """
        if self.config.enable_shadow_sync:
            await self.storage.save_plan(plan)

    def _handle_error_escalation(self, plan: Plan) -> None:
        """Handle error escalation (3-Strike Protocol)

        Checks errors in the plan and escalates those that exceed retry threshold.
        Adds escalation notes to the plan.

        Args:
            plan: Plan to check for error escalation
        """
        for error in plan.errors_encountered:
            if plan.should_escalate_error(error):
                # Auto-escalate
                error.escalated_to_user = True

                # Add escalation note
                escalation_note = (
                    f"\n\n**Error Escalation (3-Strike Protocol)**\n"
                    f"Step '{error.step_id}' has failed {error.retry_count} times.\n"
                    f"Attempted methods:\n"
                )
                for idx, method in enumerate(error.attempt_history, 1):
                    escalation_note += f" {idx}. {method}\n"
                escalation_note += "\nRecommendation: Seek user help or adjust plan to skip this step."

                plan.notes = (plan.notes or "") + escalation_note

                logger.warning(f" Error escalated: {error.error_type} (retry {error.retry_count} times)")

    async def create_plan(
        self,
        task_description: str | list[dict[str, Any]],
        reference_plans: str = "",
    ) -> Plan:
        """Create new plan from text or multimodal content.

        Args:
            task_description: Plain text or multimodal content parts (text + images).
            reference_plans: Optional few-shot reference from historical successful plans.
                Injected into HumanMessage to preserve SystemMessage prompt cache.

        Returns:
            Structured plan object

        Raises:
            ValueError: If LLM returns unexpected type
        """
        log_preview = task_description[:50] if isinstance(task_description, str) else "[multimodal]"
        logger.warning(" PlannerAgent: Creating plan - %s...", log_preview)

        structured_llm = self.llm.with_structured_output(Plan)

        prefix = "Please create a plan for the following task:\n\n"
        if reference_plans:
            prefix = f"{reference_plans}\n\n---\n\n{prefix}"

        if isinstance(task_description, str):
            human_content: str | list[dict[str, Any]] = f"{prefix}{task_description}"
        else:
            human_content = [
                {"type": "text", "text": prefix},
                *task_description,
            ]

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=human_content),
        ]

        plan = await structured_llm.ainvoke(messages)

        if not isinstance(plan, Plan):
            msg = f"Planner returned unexpected type: {type(plan)}"
            raise ValueError(msg)

        # Ensure current_step_id is set
        if not plan.current_step_id and plan.steps:
            plan.current_step_id = plan.steps[0].step_id

        logger.warning(" PlannerAgent: Plan created with %d steps", len(plan.steps))

        # Save plan if shadow sync enabled
        await self._save_plan_if_enabled(plan)

        return plan

    async def update_plan(
        self,
        current_plan: Plan,
        completed_step_id: str | None = None,
        feedback: str | None = None,
    ) -> Plan:
        """Update existing plan

        Supports 3-Strike Protocol for error handling.

        Args:
            current_plan: Current plan
            completed_step_id: Completed step ID (optional)
            feedback: Execution feedback (optional)

        Returns:
            Updated plan object

        Raises:
            ValueError: If LLM returns unexpected type
        """
        from myrm_agent_harness.agent.sub_agents.planner.prompts import (
            get_update_plan_prompt,
        )

        logger.warning(f" PlannerAgent: Updating plan - Completed: {completed_step_id}")

        # If only marking completed without feedback, no LLM call needed
        if completed_step_id and not feedback:
            current_plan.mark_step_completed(completed_step_id)
            logger.warning(" PlannerAgent: Step %s marked complete", completed_step_id)
            await self._save_plan_if_enabled(current_plan)
            return current_plan

        # With feedback, need LLM to re-evaluate plan
        structured_llm = self.llm.with_structured_output(Plan)

        prompt = get_update_plan_prompt(
            current_plan=current_plan.model_dump_json(indent=2),
            completed_step_id=completed_step_id,
            feedback=feedback,
            custom_prompt=self.update_prompt_template,
        )

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=prompt),
        ]

        updated_plan = await structured_llm.ainvoke(messages)

        if not isinstance(updated_plan, Plan):
            msg = f"Planner returned unexpected type: {type(updated_plan)}"
            raise ValueError(msg)

        # Check if errors need escalation (3-Strike Protocol)
        if self.config.enable_3_strike:
            self._handle_error_escalation(updated_plan)

        logger.warning(" PlannerAgent: Plan updated")
        await self._save_plan_if_enabled(updated_plan)

        return updated_plan

    async def get_current_plan(self) -> Plan | None:
        """Get current plan from storage

        Returns:
            Plan object if exists, None otherwise
        """
        return await self.storage.load_plan()

    async def delete_plan(self) -> bool:
        """Delete current plan

        Returns:
            True if plan was deleted
        """
        return await self.storage.delete_plan()


__all__ = ["PlannerAgent"]
