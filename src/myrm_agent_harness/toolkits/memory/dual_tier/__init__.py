"""Dual-tier memory block engine package.

Decouples global macro mental models (HyperMemoryBlock) from session-bound
transient working memories (LocalMemoryBlock).

[INPUT]
- toolkits.memory.dual_tier.attention::MemoryAttentionRouter (POS: Memory Attention Fusion layer inspired by
  Fast Weight Programming (Metis / arXiv:2607.26760).)
- toolkits.memory.dual_tier.engine::DualTierBlockEngine (POS: Dual-tier engine isolating global mental
  models from transient session details.)
- toolkits.memory.dual_tier.models::AttentionFusionContext, DistillationCandidate, DistillationResult,
  HyperMemoryBlock, LocalMemoryBlock (POS: Dual-tier memory block architecture foundation schemas inspired
  by Metis (arXiv:2607.26760).)

[OUTPUT]
- Package facade re-exporting 7 public names: AttentionFusionContext, DistillationCandidate,
  DistillationResult, DualTierBlockEngine, HyperMemoryBlock, LocalMemoryBlock, MemoryAttentionRouter

[POS]
Dual-tier memory block engine package.
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
