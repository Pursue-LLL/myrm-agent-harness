"""Anti-Semantic-Aliasing memory governor and capacity management package.

Guards against latent space concept mixing across workspaces and manages
long-horizon memory capacity saturation (inspired by Metis / arXiv:2607.26760).

[INPUT]
- toolkits.memory.governor.capacity_manager::MemoryCapacityManager (POS: Governance engine maintaining
  bounded memory capacity and maximum epistemic density.)
- toolkits.memory.governor.discriminator::AntiSemanticAliasingDiscriminator (POS: Orthogonal verification
  gate preventing cross-domain memory leakage and semantic aliasing.)
- toolkits.memory.governor.models::AliasingDecision, CapacityGovernorMetrics, DiscriminatedCandidate,
  EvictionReport, GovernedMemoryEntry, MemorySourceAnchor (POS: Foundational data contracts for
  anti-aliasing defense and capacity saturation governance.)

[OUTPUT]
- Package facade re-exporting 8 public names: AliasingDecision, AntiSemanticAliasingDiscriminator,
  CapacityGovernorMetrics, DiscriminatedCandidate, EvictionReport, GovernedMemoryEntry,
  MemoryCapacityManager, MemorySourceAnchor

[POS]
Anti-Semantic-Aliasing memory governor and capacity management package.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.governor.capacity_manager import (
    MemoryCapacityManager,
)
from myrm_agent_harness.toolkits.memory.governor.discriminator import (
    AntiSemanticAliasingDiscriminator,
)
from myrm_agent_harness.toolkits.memory.governor.models import (
    AliasingDecision,
    CapacityGovernorMetrics,
    DiscriminatedCandidate,
    EvictionReport,
    GovernedMemoryEntry,
    MemorySourceAnchor,
)

__all__ = [
    "AliasingDecision",
    "AntiSemanticAliasingDiscriminator",
    "CapacityGovernorMetrics",
    "DiscriminatedCandidate",
    "EvictionReport",
    "GovernedMemoryEntry",
    "MemoryCapacityManager",
    "MemorySourceAnchor",
]
