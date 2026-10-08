"""Sub-agent subsystem — lifecycle management, cross-examination, and configuration loading.

Configuration Architecture:
- Framework layer: Provides loading mechanism (config_loader.py)
- Business layer: Provides configuration content and policy

Configuration Loading:
- Business layer explicitly provides configuration directory path
- Framework layer loads and validates YAML files
- See business layer configs/subagents/_ARCH.md for format details
"""

from .cross_examination import (
    AdoptionChoice,
    AdoptionReceipt,
    AgentExecutionOutput,
    AgentRoleTarget,
    ConsensusDeltaHighlighter,
    CrossExamArbitrationReport,
    CrossExamConsensus,
    CrossExamDivergence,
    IntentCategory,
    IntentRoutingDecision,
    OmniAgentDispatcherSuite,
    OmniAgentUnifiedDispatcherAndSplitCrossExaminationSuite,
    OneClickArbitrator,
    SplitCrossExaminationEngine,
    UnifiedIntentDispatcher,
)

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
