"""Live Document Co-Authoring Ledger state machine with granular attribution trace.

[INPUT]
- copy
- time
- uuid
- typing
- types

[OUTPUT]
- LiveDocumentCoAuthoringLedger

[POS]
Live Document Co-Authoring Ledger state machine with granular attribution trace.

"""

import copy
import time
import uuid
from typing import Dict, List, Optional
from .types import (
    BlockType,
    CollaboratorProfile,
    CollaboratorType,
    DeltaEntry,
    DeltaOperation,
    DocumentBlock,
)


class LiveDocumentCoAuthoringLedger:
    """State machine ledger coordinating simultaneous human and agent document edits."""

    def __init__(self, document_id: str, title: str = "Untitled Collaborative Doc") -> None:
        self.document_id = document_id
        self.title = title
        self._blocks: Dict[str, DocumentBlock] = {}
        self._block_order: List[str] = []
        self._collaborators: Dict[str, CollaboratorProfile] = {}
        self._deltas: List[DeltaEntry] = []

    def register_collaborator(self, profile: CollaboratorProfile) -> None:
        """Register a human user or AI agent into the tripartite collaborative space."""
        self._collaborators[profile.collaborator_id] = profile

    def get_collaborator(self, collaborator_id: str) -> Optional[CollaboratorProfile]:
        """Look up collaborator profile."""
        return self._collaborators.get(collaborator_id)

    def list_collaborators(self) -> List[CollaboratorProfile]:
        """List all registered collaborators."""
        return list(self._collaborators.values())

    def init_document(self, blocks: List[DocumentBlock]) -> None:
        """Initialize document with starting blocks."""
        self._blocks.clear()
        self._block_order.clear()
        for b in blocks:
            self._blocks[b.block_id] = copy.deepcopy(b)
            self._block_order.append(b.block_id)

    def get_block(self, block_id: str) -> Optional[DocumentBlock]:
        """Retrieve block by id."""
        return self._blocks.get(block_id)

    def list_blocks(self) -> List[DocumentBlock]:
        """Return ordered blocks."""
        return [self._blocks[bid] for bid in self._block_order if bid in self._blocks]

    def acquire_block_lease(
        self, block_id: str, author_id: str, duration_seconds: float = 30.0
    ) -> bool:
        """Acquire lease lock on block. Grants lock if unheld, expired, or held by same author."""
        block = self._blocks.get(block_id)
        if not block:
            return False

        now = time.time()
        if (
            block.lease_holder_id is None
            or (block.lease_expires_at is not None and block.lease_expires_at < now)
            or block.lease_holder_id == author_id
        ):
            block.lease_holder_id = author_id
            block.lease_expires_at = now + duration_seconds
            return True

        return False

    def release_block_lease(self, block_id: str, author_id: str) -> bool:
        """Release lease lock if held by author."""
        block = self._blocks.get(block_id)
        if not block:
            return False

        if block.lease_holder_id == author_id:
            block.lease_holder_id = None
            block.lease_expires_at = None
            return True

        return False

    def is_block_locked(self, block_id: str, author_id: str) -> bool:
        """Check if block is currently locked by another author."""
        block = self._blocks.get(block_id)
        if not block or not block.lease_holder_id:
            return False

        now = time.time()
        if block.lease_expires_at and block.lease_expires_at < now:
            return False

        return block.lease_holder_id != author_id

    def apply_delta(
        self,
        block_id: str,
        operation: DeltaOperation,
        author_id: str,
        new_content: str,
        intent_reason: str = "",
        block_type: BlockType = BlockType.PARAGRAPH,
    ) -> DocumentBlock:
        """Apply a granular atomic delta operation to document and record attribution."""
        collab = self._collaborators.get(author_id)
        author_type = collab.collaborator_type if collab else CollaboratorType.HUMAN
        principal = collab.principal_human_id if collab else None

        if self.is_block_locked(block_id, author_id):
            raise PermissionError(
                f"Block {block_id} is currently locked by another author ({self._blocks[block_id].lease_holder_id})"
            )

        now = time.time()
        prev_content = ""

        if operation == DeltaOperation.INSERT_BLOCK:
            if block_id in self._blocks:
                raise ValueError(f"Block {block_id} already exists")
            block = DocumentBlock(
                block_id=block_id,
                block_type=block_type,
                content=new_content,
                version=1,
                last_author_id=author_id,
                last_updated_at=now,
            )
            self._blocks[block_id] = block
            self._block_order.append(block_id)

        elif operation == DeltaOperation.UPDATE_BLOCK:
            block = self._blocks.get(block_id)
            if not block:
                raise ValueError(f"Block {block_id} not found")
            prev_content = block.content
            block.content = new_content
            block.version += 1
            block.last_author_id = author_id
            block.last_updated_at = now

        elif operation == DeltaOperation.DELETE_BLOCK:
            block = self._blocks.get(block_id)
            if not block:
                raise ValueError(f"Block {block_id} not found")
            prev_content = block.content
            del self._blocks[block_id]
            if block_id in self._block_order:
                self._block_order.remove(block_id)

        elif operation == DeltaOperation.REORDER_BLOCKS:
            # new_content contains comma-separated block_ids
            new_order = [b.strip() for b in new_content.split(",") if b.strip() in self._blocks]
            if len(new_order) == len(self._blocks):
                self._block_order = new_order
            block = self._blocks.get(block_id) or DocumentBlock(
                block_id=block_id, block_type=block_type, content=new_content, last_updated_at=now
            )

        else:
            raise ValueError(f"Unsupported operation: {operation}")

        # Append to immutable ledger
        delta_entry = DeltaEntry(
            delta_id=f"delta-{uuid.uuid4().hex[:8]}",
            document_id=self.document_id,
            block_id=block_id,
            operation=operation,
            author_id=author_id,
            author_type=author_type,
            principal_human_id=principal,
            prev_content=prev_content,
            new_content=new_content,
            intent_reason=intent_reason,
            timestamp=now,
            applied=True,
        )
        self._deltas.append(delta_entry)
        return block

    def get_deltas(
        self, block_id: Optional[str] = None, author_id: Optional[str] = None
    ) -> List[DeltaEntry]:
        """Query immutable ledger entries with optional filters."""
        res = self._deltas
        if block_id:
            res = [d for d in res if d.block_id == block_id]
        if author_id:
            res = [d for d in res if d.author_id == author_id]
        return list(res)

    def get_author_contributions(self) -> Dict[str, int]:
        """Aggregate edit count per author for attribution transparent ledger."""
        counts: Dict[str, int] = {}
        for d in self._deltas:
            counts[d.author_id] = counts.get(d.author_id, 0) + 1
        return counts

    def render_markdown(self) -> str:
        """Render ordered blocks into full markdown document."""
        sections: List[str] = [f"# {self.title}\n"]
        for bid in self._block_order:
            block = self._blocks.get(bid)
            if not block:
                continue
            if block.block_type == BlockType.HEADING:
                sections.append(f"## {block.content}")
            elif block.block_type == BlockType.CODE:
                sections.append(f"```\n{block.content}\n```")
            elif block.block_type == BlockType.BULLET_LIST:
                items = [f"- {line}" for line in block.content.split("\n") if line.strip()]
                sections.append("\n".join(items))
            else:
                sections.append(block.content)
        return "\n\n".join(sections)
