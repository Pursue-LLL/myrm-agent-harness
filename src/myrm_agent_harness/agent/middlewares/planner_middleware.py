"""Planner Middleware.

[INPUT]
- agent.sub_agents.planner.schemas::Plan (POS: Plan schema)
- langchain_core.messages::HumanMessage (POS: LangChain message types)

[OUTPUT]
- planner_middleware: Middleware to inject plan blueprint + anti-drift into HumanMessage.

[POS]
Middleware that injects the static blueprint and dynamic anti-drift reminder of the
current Plan into the last HumanMessage (via request.override, non-persistent).
All injections use HumanMessage to preserve SystemMessage hash stability for prompt caching.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.sub_agents.planner.schemas import Plan

logger = logging.getLogger(__name__)


def planner_middleware(
    get_plan_fn: Callable[[str | None], Awaitable[Plan | None]],
) -> Any:
    """Create a middleware that injects the plan blueprint into the last HumanMessage.

    Args:
        get_plan_fn: A function that returns the current Plan object, taking workspace_root as argument.

    Returns:
        The middleware function.
    """

    @wrap_model_call  # type: ignore[arg-type]
    async def _middleware(
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:

        context = (
            getattr(request.runtime, "context", None)
            if hasattr(request, "runtime") and request.runtime
            else None
        )
        workspace_root = None
        if isinstance(context, dict):
            workspace_root = context.get("workspace_root")

        plan = await get_plan_fn(str(workspace_root) if workspace_root else None)
        if not plan:
            return await handler(request)

        # Extract the static blueprint (ignoring dynamic status/errors)
        blueprint_lines = [
            "##  Goal Blueprint (Static)",
            f"**Goal:** {plan.goal}",
            f"**Reasoning:** {plan.reasoning}",
            "",
            "###  Phases",
        ]

        for i, step in enumerate(plan.steps, 1):
            deps_str = (
                f" (depends on: {', '.join(step.dependencies)})"
                if step.dependencies
                else ""
            )
            blueprint_lines.append(f"#### Phase {i}: {step.description}")
            blueprint_lines.append(f"- **Step ID:** `{step.step_id}`")
            blueprint_lines.append(f"- **Expected Output:** {step.expected_output}")
            if step.risk_level and step.risk_level != "low":
                blueprint_lines.append(f"- **Risk:** {step.risk_level}")
            if deps_str:
                blueprint_lines.append(f"- **Dependencies:** {deps_str}")
            blueprint_lines.append("")

        blueprint_lines.append(
            "**INSTRUCTIONS:**\n"
            "1. Follow the phases strictly in order.\n"
            "2. When you finish a phase, you MUST call `planner_tool(action='update', completed_step_id='<step_id>', feedback='<summary of work AND any key architectural decisions made>')` to mark it complete.\n"
            "3. Do not proceed to the next phase until the current one is marked complete via the tool."
        )

        blueprint_text = "\n".join(blueprint_lines)

        new_messages = list(request.messages)

        # --- Dynamic Anti-Drift Reminder (Transient) ---
        # Find the current active step
        uncompleted_steps = [
            s for s in plan.steps if s.status not in ("completed", "skipped")
        ]
        reminder_lines = []

        if uncompleted_steps:
            current_step = uncompleted_steps[0]

            completed_count = sum(
                1 for s in plan.steps if s.status in ("completed", "skipped")
            )
            total_count = len(plan.steps)
            progress_parts = []
            for s in plan.steps:
                if s.step_id == current_step.step_id:
                    progress_parts.append(f"{s.step_id} [current]")
                elif s.status == "completed":
                    progress_parts.append(f"{s.step_id} done")
                elif s.status == "skipped":
                    progress_parts.append(f"{s.step_id} skip")
                else:
                    progress_parts.append(s.step_id)

            reminder_lines.extend([
                " ANTI-DRIFT REMINDER (Current Focus)",
                f"You are currently working on Phase `{current_step.step_id}`: {current_step.description}",
                f"Expected Output: {current_step.expected_output}",
                f"Progress: [{completed_count}/{total_count}] {', '.join(progress_parts)}",
                "",
                "Stay focused on this specific phase. Do not drift to other tasks.",
                "Before finishing this phase, briefly summarize your work and confirm it aligns with the original goal.",
                f"Once this phase is complete and verified, you MUST call `planner_tool(action='update', completed_step_id='{current_step.step_id}', feedback='<summary of work AND any key architectural decisions made>')` before proceeding.",
            ])

        # --- Decision Log (Transient XML Injection) ---
        # Inject decisions using XML tags to prevent context compression amnesia
        # and ensure maximum instruction adherence from modern LLMs.
        active_decisions = [d for d in plan.decisions if d.status == "active"]
        if active_decisions:
            if reminder_lines:
                reminder_lines.append("\n")
            reminder_lines.extend([
                "<system_directives>",
                " <architectural_decisions>",
                " <!-- The following are key architectural decisions from previous phases. You MUST adhere to them. -->",
            ])
            for dec in active_decisions:
                reminder_lines.extend([
                    f" <decision id=\"{dec.id}\">",
                    f" <topic>{dec.topic}</topic>",
                    f" <content>{dec.decision}</content>",
                    f" <rationale>{dec.rationale}</rationale>",
                    " </decision>",
                ])
            reminder_lines.extend([
                " </architectural_decisions>",
                "</system_directives>",
            ])

        # Combine blueprint + anti-drift + decisions into a single HumanMessage injection.
        # All dynamic content goes to HumanMessage to keep SystemMessage hash stable (prompt cache).
        injection_parts: list[str] = [f"[SYSTEM INSTRUCTION]\n{blueprint_text}"]
        if reminder_lines:
            injection_parts.append("\n".join(reminder_lines))

        injection_text = "\n\n".join(injection_parts)

        last_human_msg_idx = -1
        for i in range(len(new_messages) - 1, -1, -1):
            if isinstance(new_messages[i], HumanMessage):
                last_human_msg_idx = i
                break

        if last_human_msg_idx != -1:
            last_msg = new_messages[last_human_msg_idx]
            if isinstance(last_msg.content, str):
                new_messages[last_human_msg_idx] = HumanMessage(
                    content=f"{last_msg.content}\n\n{injection_text}",
                    id=last_msg.id,
                )
            elif isinstance(last_msg.content, list):
                new_messages[last_human_msg_idx] = HumanMessage(
                    content=[*last_msg.content, {"type": "text", "text": f"\n\n{injection_text}"}],
                    id=last_msg.id,
                )
        else:
            new_messages.append(HumanMessage(content=injection_text))

        return await handler(request.override(messages=new_messages))

    return _middleware


__all__ = ["planner_middleware"]
