"""Visual Frame Context Pruning and Latency Squeezing Suite (Item 203).

Provides multimodal sliding-window image eviction, base64 payload dehydration,
and structured semantic action-state summary replacement for long-horizon Computer Use.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.visual_pruner.visual_pruner_engine import (
    VisualFramePruningEngine,
)
from myrm_agent_harness.agent.context_management.visual_pruner.visual_pruner_types import (
    PrunedFrameFootprint,
    VisualPruningConfig,
    VisualPruningMode,
    VisualPruningResult,
)

__all__ = [
    "PrunedFrameFootprint",
    "VisualFramePruningEngine",
    "VisualPruningConfig",
    "VisualPruningMode",
    "VisualPruningResult",
]
