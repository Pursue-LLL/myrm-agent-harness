"""Dynamic compute budget allocation and fan-out gating engine (Item 34).

Splits total token budget and USD spending ceiling across squad members according to
their role tiers and enforces fan-out bounds to prevent runaway execution.

[INPUT]
- __future__
- logging
- types

[OUTPUT]
- logger
- DEFAULT_ROLE_WEIGHTS
- SquadBudgetAllocator

[POS]
Dynamic compute budget allocation and fan-out gating engine (Item 34).
"""

from __future__ import annotations

import logging

from .types import MemberBlueprint, SquadRoleTier, StopCondition

logger = logging.getLogger(__name__)

# Relative compute weight per role tier
DEFAULT_ROLE_WEIGHTS: dict[SquadRoleTier, float] = {
    SquadRoleTier.ORCHESTRATOR: 0.35,
    SquadRoleTier.CODER: 0.35,
    SquadRoleTier.REVIEWER: 0.15,
    SquadRoleTier.RESEARCHER: 0.15,
    SquadRoleTier.SPECIALIST: 0.20,
}


class SquadBudgetAllocator:
    """Allocates token and monetary budgets across squad members and enforces safety guards."""

    @classmethod
    def allocate_budget(
        cls,
        members: tuple[MemberBlueprint, ...],
        total_budget_tokens: int,
        total_max_cost_usd: float,
    ) -> tuple[MemberBlueprint, ...]:
        """Proportionately allocate compute quotas based on member role tiers."""
        if not members:
            return ()

        if total_budget_tokens <= 0:
            raise ValueError(f"Total budget tokens must be positive, got {total_budget_tokens}")
        if total_max_cost_usd <= 0:
            raise ValueError(f"Total max cost USD must be positive, got {total_max_cost_usd}")

        # Compute total weight
        raw_weights = [DEFAULT_ROLE_WEIGHTS.get(m.role_tier, 0.20) for m in members]
        sum_weights = sum(raw_weights) or 1.0

        allocated_members: list[MemberBlueprint] = []
        tokens_allocated_so_far = 0
        usd_allocated_so_far = 0.0

        for i, (m, weight) in enumerate(zip(members, raw_weights, strict=False)):
            ratio = weight / sum_weights

            if i == len(members) - 1:
                # Last member absorbs remaining tokens and USD to guarantee exact balance
                role_tokens = max(1000, total_budget_tokens - tokens_allocated_so_far)
                role_usd = max(0.01, round(total_max_cost_usd - usd_allocated_so_far, 2))
            else:
                role_tokens = max(1000, int(total_budget_tokens * ratio))
                role_usd = max(0.01, round(total_max_cost_usd * ratio, 2))
                tokens_allocated_so_far += role_tokens
                usd_allocated_so_far += role_usd

            # Scale stop conditions adaptively according to allocated quota
            turns_bound = min(25, max(5, role_tokens // 4000))
            tools_bound = min(60, max(10, turns_bound * 3))

            stop_cond = StopCondition(
                max_turns=turns_bound,
                max_tool_calls=tools_bound,
                allow_failure=m.stop_condition.allow_failure,
            )

            updated = MemberBlueprint(
                role_key=m.role_key,
                display_name=m.display_name,
                handle=m.handle,
                role_tier=m.role_tier,
                role_description=m.role_description,
                soul_system_prompt=m.soul_system_prompt,
                required_tools=m.required_tools,
                required_skills=m.required_skills,
                budget_tokens=role_tokens,
                max_cost_usd=role_usd,
                stop_condition=stop_cond,
                suggested_model_tier=m.suggested_model_tier,
            )
            allocated_members.append(updated)

        logger.info(
            "Allocated squad budget across %d members: %d tokens, $%.2f USD",
            len(allocated_members),
            total_budget_tokens,
            total_max_cost_usd,
        )
        return tuple(allocated_members)

    @classmethod
    def validate_squad_safety(
        cls,
        members: tuple[MemberBlueprint, ...],
        max_descendants_per_run: int = 8,
    ) -> tuple[bool, str]:
        """Validate safety invariants: bounded squad size and singular orchestrator."""
        if not members:
            return False, "Squad cannot be empty"

        if len(members) > max_descendants_per_run:
            return (
                False,
                f"Squad size {len(members)} exceeds max descendants limit {max_descendants_per_run}",
            )

        orchestrator_count = sum(1 for m in members if m.role_tier == SquadRoleTier.ORCHESTRATOR)
        if orchestrator_count != 1:
            return (
                False,
                f"Squad must have exactly 1 orchestrator, found {orchestrator_count}",
            )

        # Unique role keys
        role_keys = {m.role_key for m in members}
        if len(role_keys) != len(members):
            return False, "Duplicate role_key detected among squad members"

        return True, "Squad configuration is valid and safe"
