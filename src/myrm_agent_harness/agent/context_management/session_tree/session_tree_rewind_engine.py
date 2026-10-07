"""Manages session timeline branching, message cloning, and in-place rewind.

[INPUT]
- agent.context_management.session_tree.session_tree_types::ForkModeKind, ForkResult, RewindModeKind,
  RewindResult, SessionBranchNode, SessionMessageItem, SessionTreeTopology (POS: Types and models for session
  tree.)

[OUTPUT]
- SessionTreeRewindEngine: Manages session timeline branching, message cloning, and in-place rewind.

[POS]
Manages session timeline branching, message cloning, and in-place rewind.
"""

# ============================================================================
# Session Tree Fork & In-Place Message Rewind Engine (Item 162)
# Arbitrary timeline node branching, antecedent message slice cloning,
# in-place edit & rewind time-travel, and tree topology lineage tracking.
# ============================================================================

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Sequence

from .session_tree_types import (
    ForkModeKind,
    ForkResult,
    RewindModeKind,
    RewindResult,
    SessionBranchNode,
    SessionMessageItem,
    SessionTreeTopology,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionTreeRewindEngine:
    """Manages session timeline branching, message cloning, and in-place rewind."""

    def __init__(self) -> None:
        self._session_messages: dict[str, list[SessionMessageItem]] = {}
        self._archived_messages: dict[str, list[SessionMessageItem]] = {}
        self._branches: dict[str, SessionBranchNode] = {}
        self._session_root_map: dict[str, str] = {}

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, str] | None = None,
    ) -> SessionMessageItem:
        """Append an immutable message to a session timeline."""
        msgs = self._session_messages.setdefault(session_id, [])
        seq_idx = len(msgs) + 1
        msg_id = f"msg-{uuid.uuid4().hex[:12]}"
        now_iso = _utc_now_iso()

        item = SessionMessageItem(
            message_id=msg_id,
            session_id=session_id,
            role=role,
            content=content,
            sequence_index=seq_idx,
            created_at_iso=now_iso,
            metadata=dict(metadata or {}),
        )
        msgs.append(item)

        # Ensure session is registered in root map
        if session_id not in self._session_root_map:
            self._session_root_map[session_id] = session_id
            root_branch = SessionBranchNode(
                branch_id=f"branch-{session_id}",
                session_id=session_id,
                branch_name="main",
                parent_session_id=None,
                forked_from_message_id=None,
                created_at_iso=now_iso,
                is_active=True,
            )
            self._branches[session_id] = root_branch

        return item

    def get_messages(self, session_id: str) -> tuple[SessionMessageItem, ...]:
        """Get all active chronological messages in a session."""
        return tuple(self._session_messages.get(session_id, []))

    def fork_at_message(
        self,
        source_session_id: str,
        target_message_id: str,
        new_branch_name: str,
        fork_mode: ForkModeKind = ForkModeKind.DEEP_CLONE,
    ) -> ForkResult:
        """Fork a new independent session branch from an arbitrary message node."""
        source_msgs = self._session_messages.get(source_session_id)
        if not source_msgs:
            raise KeyError(f"Source session '{source_session_id}' has no messages.")

        # Find target anchor message index
        target_idx: int = -1
        for idx, m in enumerate(source_msgs):
            if m.message_id == target_message_id:
                target_idx = idx
                break

        if target_idx == -1:
            raise KeyError(
                f"Target message '{target_message_id}' not found in session '{source_session_id}'."
            )

        # Slice antecedent messages up to and including target node
        antecedent_slice = source_msgs[: target_idx + 1]
        new_session_id = f"session-fork-{uuid.uuid4().hex[:12]}"
        now_iso = _utc_now_iso()

        cloned_msgs: list[SessionMessageItem] = []
        if fork_mode == ForkModeKind.DEEP_CLONE:
            for seq, old_msg in enumerate(antecedent_slice, start=1):
                cloned = SessionMessageItem(
                    message_id=f"msg-{uuid.uuid4().hex[:12]}",
                    session_id=new_session_id,
                    role=old_msg.role,
                    content=old_msg.content,
                    sequence_index=seq,
                    created_at_iso=now_iso,
                    metadata=dict(old_msg.metadata),
                )
                cloned_msgs.append(cloned)
        else:
            # Shallow reference
            cloned_msgs = list(antecedent_slice)

        self._session_messages[new_session_id] = cloned_msgs

        # Maintain root lineage
        root_id = self._session_root_map.get(source_session_id, source_session_id)
        self._session_root_map[new_session_id] = root_id

        branch_node = SessionBranchNode(
            branch_id=f"branch-{new_session_id}",
            session_id=new_session_id,
            branch_name=new_branch_name,
            parent_session_id=source_session_id,
            forked_from_message_id=target_message_id,
            created_at_iso=now_iso,
            is_active=True,
        )
        self._branches[new_session_id] = branch_node

        logger.info(
            "Forked session '%s' at message '%s' -> new branch '%s' (%s, %d messages)",
            source_session_id,
            target_message_id,
            new_branch_name,
            new_session_id,
            len(cloned_msgs),
        )

        return ForkResult(
            new_session_id=new_session_id,
            parent_session_id=source_session_id,
            fork_message_id=target_message_id,
            cloned_messages_count=len(cloned_msgs),
            branch_node=branch_node,
        )

    def rewind_to_message(
        self,
        session_id: str,
        target_message_id: str,
        rewind_mode: RewindModeKind = RewindModeKind.TRUNCATE_AND_ARCHIVE,
    ) -> RewindResult:
        """Rewind timeline in-place to edit target prompt and truncate subsequent history."""
        msgs = self._session_messages.get(session_id)
        if not msgs:
            raise KeyError(f"Session '{session_id}' has no messages.")

        target_idx: int = -1
        for idx, m in enumerate(msgs):
            if m.message_id == target_message_id:
                target_idx = idx
                break

        if target_idx == -1:
            raise KeyError(
                f"Target message '{target_message_id}' not found in session '{session_id}'."
            )

        target_message = msgs[target_idx]
        restored_prompt_text = target_message.content

        # Truncate target message and everything following it
        kept_msgs = msgs[:target_idx]
        removed_msgs = msgs[target_idx:]

        if rewind_mode == RewindModeKind.TRUNCATE_AND_ARCHIVE:
            archived = self._archived_messages.setdefault(session_id, [])
            archived.extend(removed_msgs)

        self._session_messages[session_id] = kept_msgs

        logger.info(
            "Rewound session '%s' to message '%s' (removed %d messages, %d kept)",
            session_id,
            target_message_id,
            len(removed_msgs),
            len(kept_msgs),
        )

        return RewindResult(
            rewound_session_id=session_id,
            target_message_id=target_message_id,
            removed_messages_count=len(removed_msgs),
            archived_message_ids=tuple(m.message_id for m in removed_msgs),
            restored_prompt_text=restored_prompt_text,
        )

    def get_tree_topology(self, session_id: str) -> SessionTreeTopology:
        """Construct multi-branch version graph topology for session lineage."""
        root_id = self._session_root_map.get(session_id, session_id)
        lineage_branches: list[SessionBranchNode] = []

        for b_sess_id, branch_node in self._branches.items():
            if self._session_root_map.get(b_sess_id) == root_id:
                lineage_branches.append(branch_node)

        # Sort branches deterministically by created_at_iso
        lineage_branches.sort(key=lambda b: b.created_at_iso)

        return SessionTreeTopology(
            root_session_id=root_id,
            branches=tuple(lineage_branches),
            active_session_id=session_id,
        )
