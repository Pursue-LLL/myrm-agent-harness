"""Council Deliberation Pipeline state machine for multi-model consensus (Item 65).

[INPUT]
- Deliberation session requests, blind proposals, cross-critiques, and rebuttal responses.

[OUTPUT]
- CouncilSession lifecycle management, phase transitions, and final consensus synthesis.

[POS]
- Harness orchestration layer for multi-agent council deliberation.
"""

from __future__ import annotations

import time
import uuid

from myrm_agent_harness.agent.sub_agents.council.consensus_synthesizer import ConsensusSynthesizer
from myrm_agent_harness.agent.sub_agents.council.types import (
    CouncilProposal,
    CouncilSession,
    CritiqueItem,
    DeliberationPhase,
)

PHASE_ORDER: list[DeliberationPhase] = [
    DeliberationPhase.BLIND_PROPOSAL,
    DeliberationPhase.CROSS_CRITIQUE,
    DeliberationPhase.REBUTTAL,
    DeliberationPhase.CONSENSUS_SYNTHESIS,
    DeliberationPhase.FINALIZED,
]


class CouncilDeliberationPipeline:
    """Orchestrates structured 5-phase multi-model deliberation and consensus arbitration."""

    def __init__(self) -> None:
        self._sessions: dict[str, CouncilSession] = {}

    def create_session(self, session_id: str, topic: str) -> CouncilSession:
        """Create a new council deliberation session starting in blind proposal phase."""
        session = CouncilSession(
            session_id=session_id,
            deliberation_topic=topic,
            phase=DeliberationPhase.BLIND_PROPOSAL,
            proposals={},
            critiques=[],
            consensus=None,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> CouncilSession | None:
        """Retrieve an active council deliberation session."""
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[CouncilSession]:
        """List all tracked deliberation sessions."""
        return list(self._sessions.values())

    def submit_proposal(self, session_id: str, proposal: CouncilProposal) -> CouncilSession:
        """Submit an independent blind proposal to the session."""
        session = self._require_session(session_id)
        session.proposals[proposal.proposal_id] = proposal
        session.updated_at = time.time()
        return session

    def submit_critique(self, session_id: str, critique: CritiqueItem) -> CouncilSession:
        """Append an anonymous cross-model critique targeting a specific proposal."""
        session = self._require_session(session_id)
        if not critique.critique_id:
            critique.critique_id = f"critique_{uuid.uuid4().hex[:8]}"
        session.critiques.append(critique)
        session.updated_at = time.time()
        return session

    def submit_rebuttal(
        self,
        session_id: str,
        critique_id: str,
        rebuttal_text: str,
    ) -> CouncilSession:
        """Add a defense rebuttal to an existing critique point."""
        session = self._require_session(session_id)
        for c in session.critiques:
            if c.critique_id == critique_id:
                c.defense_rebuttal = rebuttal_text
                break
        session.updated_at = time.time()
        return session

    def advance_phase(
        self,
        session_id: str,
        target_phase: DeliberationPhase | None = None,
    ) -> CouncilSession:
        """Advance the session to the next phase in order or to a specific target phase."""
        session = self._require_session(session_id)
        if target_phase is not None:
            session.phase = target_phase
        else:
            current_idx = PHASE_ORDER.index(session.phase)
            if current_idx < len(PHASE_ORDER) - 1:
                session.phase = PHASE_ORDER[current_idx + 1]

        # Trigger synthesis if entering synthesis or finalized phase
        if session.phase in (DeliberationPhase.CONSENSUS_SYNTHESIS, DeliberationPhase.FINALIZED):
            session.consensus = ConsensusSynthesizer.synthesize(
                topic=session.deliberation_topic,
                proposals=list(session.proposals.values()),
                critiques=session.critiques,
            )

        session.updated_at = time.time()
        return session

    def clear(self) -> None:
        """Clear all session states (used for test isolation)."""
        self._sessions.clear()

    def _require_session(self, session_id: str) -> CouncilSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Deliberation session '{session_id}' not found.")
        return session
