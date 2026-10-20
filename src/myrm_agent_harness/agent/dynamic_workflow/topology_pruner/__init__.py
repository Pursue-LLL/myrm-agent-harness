"""Model-tier adaptive topology pruning facade.

[INPUT]
- types::(
    ModelIntelligenceTier,
    PruningDecisionKind,
    PruningStrategy,
    TaskComplexityLevel,
    TopologyPruningEvaluation,
  )
- pruner::(ModelTierAdaptiveTopologyPruner, get_topology_pruner)

[OUTPUT]
- __all__: Exported public symbols for topology pruning.

[POS]
Harness facade for adaptive orchestration simplification and pruning.
"""

from __future__ import annotations

from myrm_agent_harness.agent.dynamic_workflow.topology_pruner.pruner import (
    ModelTierAdaptiveTopologyPruner,
    get_topology_pruner,
)
from myrm_agent_harness.agent.dynamic_workflow.topology_pruner.types import (
    ModelIntelligenceTier,
    PruningDecisionKind,
    PruningStrategy,
    TaskComplexityLevel,
    TopologyPruningEvaluation,
)

__all__ = [
    "ModelIntelligenceTier",
    "ModelTierAdaptiveTopologyPruner",
    "PruningDecisionKind",
    "PruningStrategy",
    "TaskComplexityLevel",
    "TopologyPruningEvaluation",
    "get_topology_pruner",
]
