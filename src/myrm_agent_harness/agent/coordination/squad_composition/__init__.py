"""Orchestrator Bot Auto Squad Composition & Model-Deferred Wizard (Item 34).

Exports domain types, budget allocator, and blueprint composer for automatic
squad generation from high-level goals.

[INPUT]
- __future__
- blueprint_composer
- budget_allocator
- types

[OUTPUT]
- (模块级副作用与注册)

[POS]
Orchestrator Bot Auto Squad Composition & Model-Deferred Wizard (Item 34).
"""

from __future__ import annotations

from .blueprint_composer import SquadBlueprintComposer
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

__all__ = [
    "MaterializedMember",
    "MaterializedSquad",
    "MemberBlueprint",
    "ModelDeferredChoice",
    "SquadBlueprint",
    "SquadBlueprintComposer",
    "SquadBudgetAllocator",
    "SquadRoleTier",
    "StopCondition",
]
