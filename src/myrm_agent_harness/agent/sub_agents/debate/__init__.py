"""[INPUT] None.
[OUTPUT] Public facade exports for Multi-Agent Debate Workroom & Kanban Integration.
[POS] Subagent debate package root.
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.debate.kanban_bridge import DebateKanbanBridge
from myrm_agent_harness.agent.sub_agents.debate.manager import MultiAgentDebateManager
from myrm_agent_harness.agent.sub_agents.debate.synthesis_pattern import (
    CandidateProposal,
    HierarchicalDebateSynthesisEngine,
    SynthesisParticipant,
    SynthesisPhase,
    SynthesisRole,
    SynthesisSubtask,
    SynthesisWorkflowState,
    TradeoffDimension,
    TradeoffMatrix,
)
from myrm_agent_harness.agent.sub_agents.debate.types import (
    DebateParticipant,
    DebatePhase,
    DebateRole,
    DebateRoomState,
    DebateSubtask,
    DebateSubtaskStatus,
    DebateTurn,
)

__all__ = [
    "CandidateProposal",
    "DebateKanbanBridge",
    "DebateParticipant",
    "DebatePhase",
    "DebateRole",
    "DebateRoomState",
    "DebateSubtask",
    "DebateSubtaskStatus",
    "DebateTurn",
    "HierarchicalDebateSynthesisEngine",
    "MultiAgentDebateManager",
    "SynthesisParticipant",
    "SynthesisPhase",
    "SynthesisRole",
    "SynthesisSubtask",
    "SynthesisWorkflowState",
    "TradeoffDimension",
    "TradeoffMatrix",
]
