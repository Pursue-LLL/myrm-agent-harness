"""Dual-tier memory block engine package.

Decouples global macro mental models (HyperMemoryBlock) from session-bound
transient working memories (LocalMemoryBlock).
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.dual_tier.attention import (
    MemoryAttentionRouter,
)
from myrm_agent_harness.toolkits.memory.dual_tier.engine import (
    DualTierBlockEngine,
)
from myrm_agent_harness.toolkits.memory.dual_tier.models import (
    AttentionFusionContext,
    DistillationCandidate,
    DistillationResult,
    HyperMemoryBlock,
    LocalMemoryBlock,
)

__all__ = [
    "AttentionFusionContext",
    "DistillationCandidate",
    "DistillationResult",
    "DualTierBlockEngine",
    "HyperMemoryBlock",
    "LocalMemoryBlock",
    "MemoryAttentionRouter",
]
