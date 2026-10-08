# [INPUT]: None
# [OUTPUT]: AdaptiveBranchFoldingSentry, AssembledSupplyContext, DisclosureExpansionResult, HierarchicalContextTreeBuilder, HierarchicalLevel, HierarchicalNode, HierarchicalProgressiveDisclosureContextSupplySuite, HierarchyLevel, HierarchyNode, HierarchyTree, ProgressiveDisclosureConfig
# [POS]: agent/context_management/hierarchical_supply/__init__.py

"""Public contracts and facade for hierarchical progressive disclosure enterprise context supply.

[INPUT]
- None (Facade exports).

[OUTPUT]
- AdaptiveBranchFoldingSentry: Sentry monitoring active L3 ceilings and folding surplus nodes.
- AssembledSupplyContext: Consolidated multi-tier prompt payload.
- DisclosureExpansionResult: Result record of node expansion and branch folding.
- HierarchicalContextTreeBuilder: Builder constructing indexed context trees.
- HierarchyLevel: L1 Backbone, L2 Cohort, L3 Detail tiers.
- HierarchyNode: Individual contextual node.
- HierarchicalProgressiveDisclosureContextSupplySuite: Unified facade suite.
- HierarchyTree: Full tree graph of business context.
- ProgressiveDisclosureConfig: Threshold configuration.

[POS]
Modular subpackage in agent/context_management establishing Qwen Office Enterprise Context supply pattern.
"""

from __future__ import annotations

from .adaptive_branch_folding_sentry import AdaptiveBranchFoldingSentry
from .hierarchical_context_tree_builder import HierarchicalContextTreeBuilder
from .hierarchical_progressive_disclosure_suite import (
    HierarchicalProgressiveDisclosureContextSupplySuite,
)
from .hierarchical_supply_types import (
    AssembledSupplyContext,
    DisclosureExpansionResult,
    HierarchyLevel,
    HierarchyNode,
    HierarchyTree,
    ProgressiveDisclosureConfig,
)

__all__ = [
    "AdaptiveBranchFoldingSentry",
    "AssembledSupplyContext",
    "DisclosureExpansionResult",
    "HierarchicalContextTreeBuilder",
    "HierarchicalProgressiveDisclosureContextSupplySuite",
    "HierarchyLevel",
    "HierarchyNode",
    "HierarchyTree",
    "ProgressiveDisclosureConfig",
]
