"""Conflict Arbitration and Isolated Staging Proposal Engine for Live Document Co-Authoring.

[INPUT]
- time
- uuid
- typing
- ledger_engine
- types

[OUTPUT]
- CoAuthoringConflictArbitrator

[POS]
Conflict Arbitration and Isolated Staging Proposal Engine for Live Document Co-Authoring.

"""

import time
import uuid
from typing import Dict, List, Optional
from .ledger_engine import LiveDocumentCoAuthoringLedger
from .types import (
    ArbitrationStrategy,
    ArbitrationVerdict,
    CollaboratorType,
    ConflictRecord,
    StagingProposal,
)


class CoAuthoringConflictArbitrator:
    """Arbitrates concurrent mutations between humans and AI agents without silent clobbering."""

    def __init__(self, ledger: LiveDocumentCoAuthoringLedger) -> None:
        self.ledger = ledger
        self._conflicts: Dict[str, ConflictRecord] = {}
        self._proposals: Dict[str, StagingProposal] = {}

    def detect_and_arbitrate(
        self,
        block_id: str,
        first_author_id: str,
        first_content: str,
        first_reason: str,
        second_author_id: str,
        second_content: str,
        second_reason: str,
        strategy: ArbitrationStrategy = ArbitrationStrategy.HUMAN_PRIORITY,
    ) -> ArbitrationVerdict:
        """Arbitrate between two competing updates targeted at the same block."""
        now = time.time()
        cid = f"conflict-{uuid.uuid4().hex[:8]}"

        author1 = self.ledger.get_collaborator(first_author_id)
        author2 = self.ledger.get_collaborator(second_author_id)

        type1 = author1.collaborator_type if author1 else CollaboratorType.HUMAN
        type2 = author2.collaborator_type if author2 else CollaboratorType.AGENT

        staging_proposals: List[StagingProposal] = []
        winning_content = ""
        summary = ""

        if strategy == ArbitrationStrategy.HUMAN_PRIORITY:
            if type1 == CollaboratorType.HUMAN and type2 == CollaboratorType.AGENT:
                winning_content = first_content
                # Demote agent's content to an isolated staging proposal
                prop = StagingProposal(
                    proposal_id=f"prop-{uuid.uuid4().hex[:8]}",
                    block_id=block_id,
                    author_id=second_author_id,
                    content=second_content,
                    intent_reason=second_reason,
                    status="pending",
                    created_at=now,
                )
                staging_proposals.append(prop)
                self._proposals[prop.proposal_id] = prop
                summary = f"Human author ({first_author_id}) prioritized over Agent ({second_author_id}). Agent content saved as Staging Proposal."

            elif type2 == CollaboratorType.HUMAN and type1 == CollaboratorType.AGENT:
                winning_content = second_content
                prop = StagingProposal(
                    proposal_id=f"prop-{uuid.uuid4().hex[:8]}",
                    block_id=block_id,
                    author_id=first_author_id,
                    content=first_content,
                    intent_reason=first_reason,
                    status="pending",
                    created_at=now,
                )
                staging_proposals.append(prop)
                self._proposals[prop.proposal_id] = prop
                summary = f"Human author ({second_author_id}) prioritized over Agent ({first_author_id}). Agent content saved as Staging Proposal."

            else:
                # Both human or both agent: fallback to last-write or combine
                winning_content = second_content
                summary = f"Equal tier ({type1.value} vs {type2.value}): Second author prioritized."

        elif strategy == ArbitrationStrategy.ISOLATED_STAGING_PROPOSAL:
            # Neither directly overwrites: both are isolated into proposals
            p1 = StagingProposal(
                proposal_id=f"prop-{uuid.uuid4().hex[:8]}",
                block_id=block_id,
                author_id=first_author_id,
                content=first_content,
                intent_reason=first_reason,
                status="pending",
                created_at=now,
            )
            p2 = StagingProposal(
                proposal_id=f"prop-{uuid.uuid4().hex[:8]}",
                block_id=block_id,
                author_id=second_author_id,
                content=second_content,
                intent_reason=second_reason,
                status="pending",
                created_at=now,
            )
            staging_proposals.extend([p1, p2])
            self._proposals[p1.proposal_id] = p1
            self._proposals[p2.proposal_id] = p2
            existing = self.ledger.get_block(block_id)
            winning_content = existing.content if existing else first_content
            summary = "Both competing mutations isolated as staging proposals to prevent clobbering."

        else:  # TIMESTAMP_LWW
            winning_content = second_content
            summary = f"Timestamp Last-Write-Wins: Author ({second_author_id}) applied."

        record = ConflictRecord(
            conflict_id=cid,
            block_id=block_id,
            competing_authors=[first_author_id, second_author_id],
            detected_at=now,
            resolved=True,
            resolution_strategy=strategy,
            resolution_summary=summary,
        )
        self._conflicts[cid] = record

        return ArbitrationVerdict(
            resolved=True,
            winning_content=winning_content,
            strategy=strategy,
            summary=summary,
            staging_proposals=staging_proposals,
            timestamp=now,
        )

    def list_proposals(self, block_id: Optional[str] = None) -> List[StagingProposal]:
        """List active staging proposals."""
        res = list(self._proposals.values())
        if block_id:
            res = [p for p in res if p.block_id == block_id]
        return res

    def list_conflicts(self) -> List[ConflictRecord]:
        """List all conflict history records."""
        return list(self._conflicts.values())

    def accept_proposal(self, proposal_id: str, reviewer_id: str) -> Optional[StagingProposal]:
        """Accept an isolated staging proposal and merge it into the active block."""
        prop = self._proposals.get(proposal_id)
        if not prop:
            return None

        prop.status = "accepted"
        # Apply accepted proposal to ledger
        from .types import DeltaOperation

        self.ledger.apply_delta(
            block_id=prop.block_id,
            operation=DeltaOperation.UPDATE_BLOCK,
            author_id=reviewer_id,
            new_content=prop.content,
            intent_reason=f"Accepted staging proposal {proposal_id} by {prop.author_id}: {prop.intent_reason}",
        )
        return prop
