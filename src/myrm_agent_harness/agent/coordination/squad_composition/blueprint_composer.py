"""Orchestrator Squad Blueprint Composer and Model-Deferred Materializer (Item 34).

Generates multi-agent roster blueprints with SOUL-level system prompts from high-level goals
and executes Phase-2 model-deferred materialization.

[INPUT]
- __future__
- logging
- uuid
- budget_allocator
- types

[OUTPUT]
- logger
- SquadBlueprintComposer

[POS]
Orchestrator Squad Blueprint Composer and Model-Deferred Materializer (Item 34).
"""

from __future__ import annotations

import logging
import uuid

from .budget_allocator import SquadBudgetAllocator
from .types import (
    MaterializedMember,
    MaterializedSquad,
    MemberBlueprint,
    ModelDeferredChoice,
    SquadBlueprint,
    SquadRoleTier,
    StopCondition,
)

logger = logging.getLogger(__name__)


def _generate_soul_prompt(
    role_key: str,
    display_name: str,
    role_tier: SquadRoleTier,
    goal: str,
) -> str:
    """Generate a comprehensive SOUL-level system prompt for a squad member."""
    base = (
        f"# SOUL Profile: {display_name} ({role_key})\n\n"
        f"## 1. Identity & Objective\n"
        f"You are {display_name}, specialized in {role_tier.value.upper()} duties.\n"
        f"Squad Global Goal: {goal}\n\n"
        f"## 2. Operating Protocol & Boundaries\n"
    )

    if role_tier == SquadRoleTier.ORCHESTRATOR:
        return base + (
            "- Lead task decomposition, delegate subtasks to squad teammates via @mentions.\n"
            "- Never implement deep code yourself; focus exclusively on routing, verification, and convergence.\n"
            "- Track compute budget and stop immediately when all objectives are verified.\n"
        )
    elif role_tier == SquadRoleTier.CODER:
        return base + (
            "- Implement concrete source code, tests, and configurations with high quality.\n"
            "- Strictly obey PEP8, zero Any types, and ensure files remain <= 400 lines.\n"
            "- Report completion status with structured diffs back to the orchestrator.\n"
        )
    elif role_tier == SquadRoleTier.REVIEWER:
        return base + (
            "- Execute independent correctness, test coverage, and security checks.\n"
            "- Provide constructive findings with exact file line numbers and remediation suggestions.\n"
            "- Approve only when 0 errors and 0 warnings are verified.\n"
        )
    elif role_tier == SquadRoleTier.RESEARCHER:
        return base + (
            "- Investigate codebases, specifications, and external documentation.\n"
            "- Produce concise, evidence-driven summaries with exact file references.\n"
            "- Avoid speculative reasoning without verifying concrete files.\n"
        )
    else:
        return base + (
            "- Execute specialized domain tasks aligned with the squad's objective.\n"
            "- Provide structured feedback and collaborate smoothly with teammates.\n"
        )


class SquadBlueprintComposer:
    """Composes team roster blueprints and executes Phase-2 Model-Deferred materialization."""

    @classmethod
    def compose_blueprint(
        cls,
        goal_description: str,
        total_budget_tokens: int = 150000,
        total_max_cost_usd: float = 2.00,
        max_descendants_per_run: int = 8,
    ) -> SquadBlueprint:
        """Analyze high-level user goal and generate a structured multi-agent roster blueprint."""
        cleaned_goal = goal_description.strip()
        if not cleaned_goal:
            raise ValueError("Goal description cannot be empty")

        squad_id = f"squad_{uuid.uuid4().hex[:10]}"
        lower_goal = cleaned_goal.lower()

        # Step 1: Always compose Orchestrator
        orchestrator_bp = MemberBlueprint(
            role_key="orchestrator",
            display_name="Squad Conductor",
            handle="@conductor",
            role_tier=SquadRoleTier.ORCHESTRATOR,
            role_description="Decomposes goal, delegates tasks, and verifies delivery",
            soul_system_prompt=_generate_soul_prompt(
                "orchestrator", "Squad Conductor", SquadRoleTier.ORCHESTRATOR, cleaned_goal
            ),
            required_tools=("delegate_task", "send_teammate_message", "view_file"),
            required_skills=("multiagent-orchestration", "goal-decomposer"),
            suggested_model_tier="reasoning",
            stop_condition=StopCondition(max_turns=15, max_tool_calls=40, allow_failure=False),
        )

        members_list: list[MemberBlueprint] = [orchestrator_bp]

        # Step 2: Detect needed roles based on intent keywords
        has_research = any(w in lower_goal for w in ("research", "search", "investigate", "doc", "survey"))
        has_coder = any(w in lower_goal for w in ("code", "implement", "build", "refactor", "bug", "feature", "api"))
        has_review = any(w in lower_goal for w in ("review", "test", "audit", "security", "check", "verify"))

        # Pair coder and reviewer for engineering closed-loop delivery; default to trinity
        if has_coder or has_review or (not has_research):
            has_coder = True
            has_review = True

        if has_research:
            members_list.append(
                MemberBlueprint(
                    role_key="researcher",
                    display_name="Scout Investigator",
                    handle="@scout",
                    role_tier=SquadRoleTier.RESEARCHER,
                    role_description="Codebase exploration, documentation audit, and technical scouting",
                    soul_system_prompt=_generate_soul_prompt(
                        "researcher", "Scout Investigator", SquadRoleTier.RESEARCHER, cleaned_goal
                    ),
                    required_tools=("view_file", "search_code", "list_dir"),
                    required_skills=("code-research", "evidence-retrieval"),
                    suggested_model_tier="fast",
                    stop_condition=StopCondition(max_turns=8, max_tool_calls=25, allow_failure=True),
                )
            )

        if has_coder:
            members_list.append(
                MemberBlueprint(
                    role_key="coder",
                    display_name="Core Engineer",
                    handle="@engineer",
                    role_tier=SquadRoleTier.CODER,
                    role_description="Code implementation, test creation, and bug remediation",
                    soul_system_prompt=_generate_soul_prompt(
                        "coder", "Core Engineer", SquadRoleTier.CODER, cleaned_goal
                    ),
                    required_tools=("view_file", "replace_file_content", "write_to_file", "run_command"),
                    required_skills=("clean-code", "refactoring-specialist"),
                    suggested_model_tier="balanced",
                    stop_condition=StopCondition(max_turns=12, max_tool_calls=35, allow_failure=False),
                )
            )

        if has_review:
            members_list.append(
                MemberBlueprint(
                    role_key="reviewer",
                    display_name="Quality Guardian",
                    handle="@guardian",
                    role_tier=SquadRoleTier.REVIEWER,
                    role_description="Architecture review, edge-case analysis, and verification",
                    soul_system_prompt=_generate_soul_prompt(
                        "reviewer", "Quality Guardian", SquadRoleTier.REVIEWER, cleaned_goal
                    ),
                    required_tools=("view_file", "run_command"),
                    required_skills=("code-review", "security-audit"),
                    suggested_model_tier="fast",
                    stop_condition=StopCondition(max_turns=8, max_tool_calls=20, allow_failure=False),
                )
            )

        # Step 3: Run Budget Allocator across raw members
        budgeted_members = SquadBudgetAllocator.allocate_budget(
            members=tuple(members_list),
            total_budget_tokens=total_budget_tokens,
            total_max_cost_usd=total_max_cost_usd,
        )

        # Step 4: Validate Safety
        is_safe, msg = SquadBudgetAllocator.validate_squad_safety(
            budgeted_members, max_descendants_per_run
        )
        if not is_safe:
            raise ValueError(f"Squad safety check failed: {msg}")

        logger.info(
            "Composed squad blueprint '%s' with %d members for goal: %s",
            squad_id,
            len(budgeted_members),
            cleaned_goal[:60],
        )

        return SquadBlueprint(
            squad_id=squad_id,
            goal_description=cleaned_goal,
            members=budgeted_members,
            total_budget_tokens=total_budget_tokens,
            total_max_cost_usd=total_max_cost_usd,
            max_descendants_per_run=max_descendants_per_run,
        )

    @classmethod
    def materialize_squad(
        cls,
        blueprint: SquadBlueprint,
        model_choices: dict[str, ModelDeferredChoice],
        default_model_id: str = "gpt-4o-mini",
    ) -> MaterializedSquad:
        """Phase 2: Bind user-confirmed models to blueprint roles and materialize the squad."""
        materialized_members: list[MaterializedMember] = []
        orchestrator_bot_id: str = ""

        for bp in blueprint.members:
            choice = model_choices.get(bp.role_key)
            selected_model = choice.selected_model_id if choice else default_model_id
            custom_extra = choice.custom_instructions if choice else ""

            bot_id = f"bot_{bp.role_key}_{uuid.uuid4().hex[:8]}"
            if bp.role_tier == SquadRoleTier.ORCHESTRATOR:
                orchestrator_bot_id = bot_id

            final_prompt = bp.soul_system_prompt
            if custom_extra.strip():
                final_prompt += f"\n\n## Custom User Instructions\n{custom_extra.strip()}"

            mat_member = MaterializedMember(
                role_key=bp.role_key,
                bot_id=bot_id,
                handle=bp.handle,
                display_name=bp.display_name,
                role_tier=bp.role_tier,
                selected_model_id=selected_model,
                allocated_budget_tokens=bp.budget_tokens,
                allocated_max_cost_usd=bp.max_cost_usd,
                system_prompt=final_prompt,
                tools=bp.required_tools,
                skills=bp.required_skills,
                stop_condition=bp.stop_condition,
            )
            materialized_members.append(mat_member)

        logger.info(
            "Materialized squad '%s' with %d active members (orchestrator: %s)",
            blueprint.squad_id,
            len(materialized_members),
            orchestrator_bot_id,
        )

        return MaterializedSquad(
            squad_id=blueprint.squad_id,
            orchestrator_bot_id=orchestrator_bot_id,
            members=tuple(materialized_members),
            total_budget_tokens=blueprint.total_budget_tokens,
            total_max_cost_usd=blueprint.total_max_cost_usd,
            status="active",
        )
