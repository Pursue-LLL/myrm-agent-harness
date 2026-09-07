"""Agentic Codebase Slimming Subsystem Package.

[INPUT]
- .types::DeadCodeCandidate, DeadCodeScanReport, SlimmingLedger, SlimmingModuleTask, SlimmingRiskLevel, SlimmingTaskStatus, EquivalenceVerdict
- .scanner::DeadCodeTopologyScanner
- .guard::EquivalenceInvarianceGuard
- .pipeline::CodebaseSlimmingPipeline

[OUTPUT]
- Re-exports core domain models, scanner, guard, and pipeline orchestrator.

[POS]
Clean facade for codebase slimming, dead code pruning, and equivalence refactoring.
"""

from myrm_agent_harness.agent.sub_agents.codebase_slimming.guard import (
    EquivalenceInvarianceGuard,
)
from myrm_agent_harness.agent.sub_agents.codebase_slimming.pipeline import (
    CodebaseSlimmingPipeline,
)
from myrm_agent_harness.agent.sub_agents.codebase_slimming.scanner import (
    DeadCodeTopologyScanner,
)
from myrm_agent_harness.agent.sub_agents.codebase_slimming.types import (
    DeadCodeCandidate,
    DeadCodeScanReport,
    EquivalenceVerdict,
    SlimmingLedger,
    SlimmingModuleTask,
    SlimmingRiskLevel,
    SlimmingTaskStatus,
)

__all__ = [
    "CodebaseSlimmingPipeline",
    "DeadCodeCandidate",
    "DeadCodeScanReport",
    "DeadCodeTopologyScanner",
    "EquivalenceInvarianceGuard",
    "EquivalenceVerdict",
    "SlimmingLedger",
    "SlimmingModuleTask",
    "SlimmingRiskLevel",
    "SlimmingTaskStatus",
]
