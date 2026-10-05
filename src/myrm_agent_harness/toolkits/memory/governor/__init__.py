"""Anti-Semantic-Aliasing memory governor and capacity management package.

Guards against latent space concept mixing across workspaces and manages
long-horizon memory capacity saturation (inspired by Metis / arXiv:2607.26760).
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
