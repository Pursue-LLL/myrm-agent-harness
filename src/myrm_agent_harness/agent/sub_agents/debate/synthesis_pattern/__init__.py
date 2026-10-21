"""[INPUT] types.py, engine.py.
[OUTPUT] Public facade exports for Hierarchical Leader-Worker Debate & Synthesis Pattern.
[POS] Subagent debate synthesis pattern package root.
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.debate.synthesis_pattern.engine import (
    HierarchicalDebateSynthesisEngine,
)
from myrm_agent_harness.agent.sub_agents.debate.synthesis_pattern.types import (
    CandidateProposal,
    SynthesisParticipant,
    SynthesisPhase,
    SynthesisRole,
    SynthesisSubtask,
    SynthesisWorkflowState,
    TradeoffDimension,
    TradeoffMatrix,
)

__all__ = [
    "CandidateProposal",
    "HierarchicalDebateSynthesisEngine",
    "SynthesisParticipant",
    "SynthesisPhase",
    "SynthesisRole",
    "SynthesisSubtask",
    "SynthesisWorkflowState",
    "TradeoffDimension",
    "TradeoffMatrix",
]
