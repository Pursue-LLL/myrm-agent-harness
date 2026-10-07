"""Context Gap Auto Probe and Intent-Driven Proactive Recall Gate (Item 210).

Proactively identifies references to pruned or compacted historical entities,
generating deterministic nudge injections to prompt autonomous history tool invocation.
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
