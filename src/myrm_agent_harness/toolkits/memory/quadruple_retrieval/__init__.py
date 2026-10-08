"""Quadruple Parallel Retrieval and Reasoner Suite package.

[INPUT]
- models: ParsedTaskGoal, TaskGoal, RetrievalChannelKind, RetrievalChannelType, ReasonerDecisionKind,
          ChannelRecallHit, CandidateMemoryItem, UnifiedCandidateHit, RerankedMemoryHit,
          HarmonizedMemoryItem, QuadrupleRetrievalReport, HarmonizedRecallResult, QueryIntentType
- goal_parser: TaskGoalParser
- parallel_retriever: QuadrupleParallelRetriever, MemoryStoreItem
- reasoner: ReasonerReranker, ReasonerHarmonizer
- orchestrator: QuadrupleRetrievalOrchestrator

[OUTPUT]
- Public exports for quadruple parallel retrieval engine.

[POS]
Package init exporting goal-driven quadruple parallel retrieval and reasoner components.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.quadruple_retrieval.goal_parser import (
    TaskGoalParser,
)
from myrm_agent_harness.toolkits.memory.quadruple_retrieval.models import (
    CandidateMemoryItem,
    ChannelRecallHit,
    HarmonizedMemoryItem,
    HarmonizedRecallResult,
    ParsedTaskGoal,
    QuadrupleRetrievalReport,
    QueryIntentType,
    ReasonerDecisionKind,
    RerankedMemoryHit,
    RetrievalChannelKind,
    RetrievalChannelType,
    TaskGoal,
    UnifiedCandidateHit,
)
from myrm_agent_harness.toolkits.memory.quadruple_retrieval.orchestrator import (
    QuadrupleRetrievalOrchestrator,
)
from myrm_agent_harness.toolkits.memory.quadruple_retrieval.parallel_retriever import (
    MemoryStoreItem,
    QuadrupleParallelRetriever,
)
from myrm_agent_harness.toolkits.memory.quadruple_retrieval.reasoner import (
    ReasonerHarmonizer,
    ReasonerReranker,
)

__all__ = [
    "CandidateMemoryItem",
    "ChannelRecallHit",
    "HarmonizedMemoryItem",
    "HarmonizedRecallResult",
    "MemoryStoreItem",
    "ParsedTaskGoal",
    "QuadrupleParallelRetriever",
    "QuadrupleRetrievalOrchestrator",
    "QuadrupleRetrievalReport",
    "QueryIntentType",
    "ReasonerDecisionKind",
    "ReasonerHarmonizer",
    "ReasonerReranker",
    "RerankedMemoryHit",
    "RetrievalChannelKind",
    "RetrievalChannelType",
    "TaskGoal",
    "TaskGoalParser",
    "UnifiedCandidateHit",
]
