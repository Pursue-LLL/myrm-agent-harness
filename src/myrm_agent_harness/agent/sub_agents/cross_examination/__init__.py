"""Omni-agent unified dispatch and split cross-examination package.

[INPUT]
- None (Package root exports).

[OUTPUT]
- AdoptionChoice: Modes for adopting cross-examination conclusions.
- AdoptionReceipt: Structured adoption result ready for workspace memory injection.
- AgentExecutionOutput: Output payload of a single candidate agent.
- AgentRoleTarget: Standard specialized agent archetypes.
- ConsensusDeltaHighlighter: Analyzes heterogeneous agent outputs, computes common ground, highlights deltas.
- CrossExamArbitrationReport: Full cross-examination analysis with synthesis.
- CrossExamConsensus: Common ground facts and shared recommendations across agents.
- CrossExamDivergence: Specific points of disagreement, positions, and severity.
- IntentCategory: High-level classification of user requests.
- IntentRoutingDecision: Routing decision with confidence, candidate agents, and cross-exam suggestion.
- OmniAgentDispatcherSuite: Convenient alias for the unified suite facade.
- OmniAgentUnifiedDispatcherAndSplitCrossExaminationSuite: Unified entry point facade for Item 314.
- OneClickArbitrator: Resolves user adoption choice into structured workspace context.
- SplitCrossExaminationEngine: Coordinates execution across 2-3 agents and synthesizes report.
- UnifiedIntentDispatcher: Sub-millisecond rule-and-heuristic intent classification engine.

[POS]
Package entry point for Item 314 OmniAgentUnifiedDispatcherAndSplitCrossExaminationSuite.
"""

from .consensus_delta_highlighter import ConsensusDeltaHighlighter
from .cross_exam_types import (
    AdoptionChoice,
    AdoptionReceipt,
    AgentExecutionOutput,
    AgentRoleTarget,
    CrossExamArbitrationReport,
    CrossExamConsensus,
    CrossExamDivergence,
    IntentCategory,
    IntentRoutingDecision,
)
from .omni_agent_dispatcher_and_cross_examination_suite import (
    OmniAgentDispatcherSuite,
    OmniAgentUnifiedDispatcherAndSplitCrossExaminationSuite,
)
from .one_click_arbitrator import OneClickArbitrator
from .split_cross_examination_engine import SplitCrossExaminationEngine
from .unified_intent_dispatcher import UnifiedIntentDispatcher

__all__ = [
    "AdoptionChoice",
    "AdoptionReceipt",
    "AgentExecutionOutput",
    "AgentRoleTarget",
    "ConsensusDeltaHighlighter",
    "CrossExamArbitrationReport",
    "CrossExamConsensus",
    "CrossExamDivergence",
    "IntentCategory",
    "IntentRoutingDecision",
    "OmniAgentDispatcherSuite",
    "OmniAgentUnifiedDispatcherAndSplitCrossExaminationSuite",
    "OneClickArbitrator",
    "SplitCrossExaminationEngine",
    "UnifiedIntentDispatcher",
]
