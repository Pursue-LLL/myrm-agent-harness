"""Deep Research module — multi-phase orchestrated research.

[INPUT]
- config (POS: DeepResearchConfig, DeepResearchPhase, ToolCategory, PhaseGuidance)
- orchestrator (POS: DeepResearchOrchestrator, DeepResearchResult)

[OUTPUT]
- DeepResearchConfig: orchestrator configuration
- DeepResearchPhase: lifecycle phase enum
- DeepResearchOrchestrator: async generator driving the research lifecycle
- DeepResearchResult: final result container
- PhaseGuidance: callback return type for cycle-level HITL

[POS]
Public API for the Deep Research system. Import everything from here.
"""

from .config import DeepResearchConfig, DeepResearchPhase, PhaseGuidance
from .orchestrator import DeepResearchOrchestrator, DeepResearchResult

__all__ = [
    "DeepResearchConfig",
    "DeepResearchOrchestrator",
    "DeepResearchPhase",
    "DeepResearchResult",
    "PhaseGuidance",
]
