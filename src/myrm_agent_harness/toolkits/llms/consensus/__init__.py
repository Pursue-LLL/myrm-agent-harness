"""Consensus (MoA) — multi-model collaborative reasoning.

Parallel-queries multiple reference LLMs on the same prompt, then
synthesises all responses through an aggregator LLM to produce a
single answer that surpasses any individual model.

Based on arXiv:2406.04692 "Mixture-of-Agents Enhances LLM Capabilities".
"""

from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import AdvisorFanoutRunner
from myrm_agent_harness.toolkits.llms.consensus.advisor_prompts import (
    ADVISOR_SYSTEM,
    build_advisor_injection_block,
)
from myrm_agent_harness.toolkits.llms.consensus.engine import (
    ConsensusEngine,
    ConsensusStreamEvent,
)
from myrm_agent_harness.toolkits.llms.consensus.moa_overlay_types import (
    MoAFanoutMode,
    MoAOverlayConfig,
)
from myrm_agent_harness.toolkits.llms.consensus.types import (
    ConsensusConfig,
    ConsensusResult,
    PrivacyFilterMode,
    PrivacyRedactor,
    ReferenceResponse,
)

__all__ = [
    "ADVISOR_SYSTEM",
    "AdvisorFanoutRunner",
    "ConsensusConfig",
    "ConsensusEngine",
    "ConsensusResult",
    "ConsensusStreamEvent",
    "MoAFanoutMode",
    "MoAOverlayConfig",
    "PrivacyFilterMode",
    "PrivacyRedactor",
    "ReferenceResponse",
    "build_advisor_injection_block",
]
