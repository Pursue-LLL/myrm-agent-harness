"""Consensus (MoA) — multi-model collaborative reasoning.

Parallel-queries multiple reference LLMs on the same prompt, then
synthesises all responses through an aggregator LLM to produce a
single answer that surpasses any individual model.

Based on arXiv:2406.04692 "Mixture-of-Agents Enhances LLM Capabilities".
"""

from myrm_agent_harness.toolkits.llms.consensus.engine import (
    ConsensusEngine,
    ConsensusStreamEvent,
)
from myrm_agent_harness.toolkits.llms.consensus.types import (
    ConsensusConfig,
    ConsensusResult,
    ReferenceResponse,
)

__all__ = [
    "ConsensusConfig",
    "ConsensusEngine",
    "ConsensusResult",
    "ConsensusStreamEvent",
    "ReferenceResponse",
]
