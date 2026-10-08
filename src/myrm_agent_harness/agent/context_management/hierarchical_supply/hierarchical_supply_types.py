"""Domain models and contracts for hierarchical progressive disclosure enterprise context supply.

[INPUT]
- None (Self-contained domain models inspired by Qwen Office Enterprise Context philosophy).

[OUTPUT]
- HierarchyLevel: L1 Backbone, L2 Cohort/Relation, L3 Detail Leaf enumeration.
- HierarchyNode: Individual contextual node in the business topology graph.
- HierarchyTree: Full indexed graph of hierarchical enterprise context.
- ProgressiveDisclosureConfig: Capacity thresholds and auto-folding policies.
- DisclosureExpansionResult: Outcome record of runtime expansion and branch folding.
- AssembledSupplyContext: Final rendered prompt context with tier accounting.

[POS]
Domain layer establishing three-tier enterprise context organization and progressive disclosure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class HierarchyLevel(str, Enum):
    """Abstraction tiers for enterprise context supply."""

    L1_BACKBONE = "L1_BACKBONE"
    L2_COHORT = "L2_COHORT"
    L3_DETAIL = "L3_DETAIL"


@dataclass(frozen=True)
class HierarchyNode:
    """A single node in the enterprise context topology tree."""

    node_id: str
    title: str
    level: HierarchyLevel
    summary: str
    full_content: str
    parent_id: str | None = None
    children_ids: Sequence[str] = field(default_factory=tuple)
    is_expanded: bool = False
    is_completed: bool = False
    token_estimate: int = 0


@dataclass(frozen=True)
class HierarchyTree:
    """Indexed collection of contextual nodes forming an enterprise knowledge tree."""

    root_node_ids: Sequence[str]
    nodes: Mapping[str, HierarchyNode]


@dataclass(frozen=True)
class ProgressiveDisclosureConfig:
    """Thresholds governing runtime progressive context hydration and auto-folding."""

    max_active_l3_nodes: int = 3
    auto_fold_completed_branches: bool = True
    max_assembled_tokens: int = 6000


@dataclass(frozen=True)
class DisclosureExpansionResult:
    """Result of expanding or folding nodes during progressive disclosure."""

    node_id: str
    target_level: HierarchyLevel
    expanded_text: str
    tokens_added: int
    folded_nodes: Sequence[str]


@dataclass(frozen=True)
class AssembledSupplyContext:
    """Rendered context payload combining active L1/L2/L3 tiers with token statistics."""

    assembled_prompt: str
    active_l1_count: int
    active_l2_count: int
    active_l3_count: int
    total_tokens: int
