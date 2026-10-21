"""Data types and schemas for Multi-Human Multi-Agent Live Document Co-Authoring Ledger.

[INPUT]
- dataclasses
- enum
- time
- typing

[OUTPUT]
- CollaboratorType
- BlockType
- DeltaOperation
- ArbitrationStrategy
- CollaboratorProfile
- DocumentBlock
- DeltaEntry
- StagingProposal
- ConflictRecord
- ArbitrationVerdict

[POS]
Data types and schemas for Multi-Human Multi-Agent Live Document Co-Authoring Ledger.

"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Optional


class CollaboratorType(str, Enum):
    """Collaborator classification: human participant or autonomous AI agent."""

    HUMAN = "human"
    AGENT = "agent"


class BlockType(str, Enum):
    """Semantic block type in the live document."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    CODE = "code"
    TABLE = "table"
    BULLET_LIST = "bullet_list"


class DeltaOperation(str, Enum):
    """Atomic delta operations for collaborative document state machine."""

    INSERT_BLOCK = "insert_block"
    UPDATE_BLOCK = "update_block"
    DELETE_BLOCK = "delete_block"
    REORDER_BLOCKS = "reorder_blocks"


class ArbitrationStrategy(str, Enum):
    """Conflict arbitration strategies for simultaneous multi-party mutations."""

    HUMAN_PRIORITY = "human_priority"
    TIMESTAMP_LWW = "timestamp_lww"
    ISOLATED_STAGING_PROPOSAL = "isolated_staging_proposal"


@dataclass
class CollaboratorProfile:
    """Participant in tripartite collaboration (Human-to-Human, Human-to-Agent, Agent-to-Agent)."""

    collaborator_id: str
    collaborator_type: CollaboratorType
    name: str
    principal_human_id: Optional[str] = None
    role_description: str = ""
    joined_at: float = field(default_factory=time.time)


@dataclass
class DocumentBlock:
    """Granular live block in co-authored document."""

    block_id: str
    block_type: BlockType
    content: str
    version: int = 1
    last_author_id: str = ""
    last_updated_at: float = field(default_factory=time.time)
    lease_holder_id: Optional[str] = None
    lease_expires_at: Optional[float] = None


@dataclass
class DeltaEntry:
    """Immutable ledger entry recording granular change with intent attribution."""

    delta_id: str
    document_id: str
    block_id: str
    operation: DeltaOperation
    author_id: str
    author_type: CollaboratorType
    principal_human_id: Optional[str] = None
    prev_content: str = ""
    new_content: str = ""
    intent_reason: str = ""
    timestamp: float = field(default_factory=time.time)
    applied: bool = True


@dataclass
class StagingProposal:
    """Isolated staging proposal for contested block rewrites without overriding."""

    proposal_id: str
    block_id: str
    author_id: str
    content: str
    intent_reason: str
    status: str = "pending"
    created_at: float = field(default_factory=time.time)


@dataclass
class ConflictRecord:
    """Audit record when two or more agents/humans mutate the same block concurrently."""

    conflict_id: str
    block_id: str
    competing_delta_ids: list[str] = field(default_factory=list)
    competing_authors: list[str] = field(default_factory=list)
    detected_at: float = field(default_factory=time.time)
    resolved: bool = False
    resolution_strategy: ArbitrationStrategy = ArbitrationStrategy.HUMAN_PRIORITY
    resolution_summary: str = ""


@dataclass
class ArbitrationVerdict:
    """Final consensus arbitration output with winning content and staging branches."""

    resolved: bool
    winning_content: str
    strategy: ArbitrationStrategy
    summary: str
    staging_proposals: list[StagingProposal] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
