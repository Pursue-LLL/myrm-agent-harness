"""Council of Agents Multi-Model Deliberation Protocol package (Item 65).

[INPUT]
- Multi-model deliberation proposals, cross-critiques, and rebuttal responses.

[OUTPUT]
- CouncilSession lifecycle, multi-model deliberation pipeline, and consensus synthesizer.

[POS]
- Harness orchestration layer for multi-agent council deliberation and weighted consensus.
"""

from myrm_agent_harness.agent.sub_agents.council.consensus_synthesizer import ConsensusSynthesizer
from myrm_agent_harness.agent.sub_agents.council.deliberation_pipeline import CouncilDeliberationPipeline
from myrm_agent_harness.agent.sub_agents.council.types import (
    ConsensusVerdict,
    CouncilMemberTier,
    CouncilProposal,
    CouncilSession,
    CritiqueItem,
    CritiqueSeverity,
    DeliberationPhase,
)

__all__ = [
    "ConsensusSynthesizer",
    "ConsensusVerdict",
    "CouncilDeliberationPipeline",
    "CouncilMemberTier",
    "CouncilProposal",
    "CouncilSession",
    "CritiqueItem",
    "CritiqueSeverity",
    "DeliberationPhase",
]
