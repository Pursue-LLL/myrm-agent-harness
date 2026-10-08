"""Context Gap Auto Probe and Intent-Driven Proactive Recall Gate (Item 210).

Proactively identifies references to pruned or compacted historical entities,
generating deterministic nudge injections to prompt autonomous history tool invocation.

[INPUT]
- agent.context_management.proactive_recall.proactive_recall_engine::ContextGapAutoProbeEngine (POS: Core
  engine for Context Gap Auto Probe and Intent-Driven Proactive Recall Gate (Item 210).)
- agent.context_management.proactive_recall.proactive_recall_types::ContextGapDetection, EntityType,
  PrunedEntityRecord, ProactiveRecallNudgeConfig, ProactiveRecallProbeResult (POS: Strongly typed contracts
  for Context Gap Auto Probe and Proactive Recall Gate (Item 210).)

[OUTPUT]
- Re-exports: ContextGapAutoProbeEngine, ContextGapDetection, EntityType, PrunedEntityRecord,
  ProactiveRecallNudgeConfig, ProactiveRecallProbeResult

[POS]
Context Gap Auto Probe and Intent-Driven Proactive Recall Gate (Item 210).
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.proactive_recall.proactive_recall_engine import (
    ContextGapAutoProbeEngine,
)
from myrm_agent_harness.agent.context_management.proactive_recall.proactive_recall_types import (
    ContextGapDetection,
    EntityType,
    PrunedEntityRecord,
    ProactiveRecallNudgeConfig,
    ProactiveRecallProbeResult,
)

__all__ = [
    "ContextGapAutoProbeEngine",
    "ContextGapDetection",
    "EntityType",
    "PrunedEntityRecord",
    "ProactiveRecallNudgeConfig",
    "ProactiveRecallProbeResult",
]
