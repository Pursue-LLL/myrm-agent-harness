"""Core implementation of Dual-Branching Session Fork and In-Place Turn Rewind Engine.

Provides tree-structured DAG conversation tracking, "New Session From Here" deep cloning,
"Edit From Here" non-destructive version branching, and active timeline projection.
"""

from __future__ import annotations

import logging
import threading
import uuid

from .dual_branching_types import (
    BranchDescriptor,
    ForkCloneResult,
    TreeNodeMessage,
    VersionNavigationInfo,
)

logger = logging.getLogger(__name__)


class DualBranchingSessionEngine:
    """Manages dual-posture branching DAG conversation trees and version navigations."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # session_id -> {message_id -> TreeNodeMessage}
        self._messages: dict[str, dict[str, TreeNodeMessage]] = {}
        # session_id -> {parent_id -> list[message_id]}
        self._children: dict[str, dict[str | None, list[str]]] = {}
        # session_id -> {branch_id -> BranchDescriptor}
        self._branches: dict[str, dict[str, BranchDescriptor]] = {}
        # session_id -> active_branch_id
        self._active_branch: dict[str, str] = {}
        # session_id -> {branch_id -> head_message_id}
        self._branch_heads: dict[str, dict[str, str]] = {}

    def create_session(self, session_id: str) -> str:
        """Initialize an empty DAG conversation tree for the session."""
        with self._lock:
            if session_id not in self._messages:
                self._messages[session_id] = {}
                self._children[session_id] = {}
                self._branches[session_id] = {}
                self._branch_heads[session_id] = {}

                main_branch = "branch-main"
                self._active_branch[session_id] = main_branch
                self._branches[session_id][main_branch] = BranchDescriptor(
                    branch_id=main_branch,
                    forked_from_message_id=None,
                    name="Main Line",
                )
            return self._active_branch[session_id]

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        parent_id: str | None = None,
    ) -> TreeNodeMessage:
        """Append a new message node to the session's active branch."""
        with self._lock:
            self.create_session(session_id)
            active_branch = self._active_branch[session_id]

            # If parent_id not specified, attach to current branch head
            if parent_id is None:
                parent_id = self._branch_heads[session_id].get(active_branch)

            msg_id = f"msg-{uuid.uuid4().hex[:12]}"
            node = TreeNodeMessage(
                message_id=msg_id,
                session_id=session_id,
                role=role,
                content=content,
                parent_id=parent_id,
                branch_id=active_branch,
            )

            self._messages[session_id][msg_id] = node
            if parent_id not in self._children[session_id]:
                self._children[session_id][parent_id] = []
            self._children[session_id][parent_id].append(msg_id)
            self._branch_heads[session_id][active_branch] = msg_id

            return node

    def new_session_from_here(
        self,
        source_session_id: str,
        cutoff_message_id: str,
        new_session_id: str,
    ) -> ForkCloneResult:
        """Posture 1: Fork an independent session cloning all ancestral turns up to cutoff."""
        with self._lock:
            if source_session_id not in self._messages:
                raise KeyError(f"Source session '{source_session_id}' not found.")
            if cutoff_message_id not in self._messages[source_session_id]:
                raise KeyError(f"Cutoff message '{cutoff_message_id}' not found in source session.")

            # Trace ancestry upwards from cutoff node to root
            lineage: list[TreeNodeMessage] = []
            curr_id: str | None = cutoff_message_id
            while curr_id is not None:
                msg = self._messages[source_session_id][curr_id]
                lineage.append(msg)
                curr_id = msg.parent_id

            # Reverse to maintain chronological order
            lineage.reverse()

            # Create destination session and import ancestral messages
            self.create_session(new_session_id)
            cloned_nodes: list[TreeNodeMessage] = []
            new_parent_id: str | None = None

            for old_node in lineage:
                cloned = self.append_message(
                    session_id=new_session_id,
                    role=old_node.role,
                    content=old_node.content,
                    parent_id=new_parent_id,
                )
                cloned_nodes.append(cloned)
                new_parent_id = cloned.message_id

            logger.info(
                "Forked session '%s' from '%s' at '%s' (%d messages cloned)",
                new_session_id,
                source_session_id,
                cutoff_message_id,
                len(cloned_nodes),
            )

            return ForkCloneResult(
                source_session_id=source_session_id,
                new_session_id=new_session_id,
                cutoff_message_id=cutoff_message_id,
                cloned_message_count=len(cloned_nodes),
                cloned_messages=tuple(cloned_nodes),
            )

    def edit_from_here(
        self,
        session_id: str,
        target_message_id: str,
        new_role: str,
        new_content: str,
    ) -> TreeNodeMessage:
        """Posture 2: Fork a non-destructive version branch in-place, keeping original history intact."""
        with self._lock:
            if session_id not in self._messages:
                raise KeyError(f"Session '{session_id}' not found.")
            if target_message_id not in self._messages[session_id]:
                raise KeyError(f"Target message '{target_message_id}' not found.")

            target_msg = self._messages[session_id][target_message_id]
            parent_id = target_msg.parent_id

            # Spawn a new branch for this variation
            branch_index = len(self._branches[session_id]) + 1
            new_branch_id = f"branch-v{branch_index}-{uuid.uuid4().hex[:6]}"
            desc = BranchDescriptor(
                branch_id=new_branch_id,
                forked_from_message_id=parent_id,
                name=f"Branch v{branch_index}",
            )
            self._branches[session_id][new_branch_id] = desc
            self._active_branch[session_id] = new_branch_id

            # Append the modified message under the same parent
            msg_id = f"msg-{uuid.uuid4().hex[:12]}"
            new_node = TreeNodeMessage(
                message_id=msg_id,
                session_id=session_id,
                role=new_role,
                content=new_content,
                parent_id=parent_id,
                branch_id=new_branch_id,
            )

            self._messages[session_id][msg_id] = new_node
            if parent_id not in self._children[session_id]:
                self._children[session_id][parent_id] = []
            self._children[session_id][parent_id].append(msg_id)
            self._branch_heads[session_id][new_branch_id] = msg_id

            logger.info(
                "In-place edit spawned branch '%s' under parent '%s', original '%s' preserved",
                new_branch_id,
                parent_id,
                target_message_id,
            )

            return new_node

    def switch_active_branch(self, session_id: str, branch_id: str) -> None:
        """Switch the session's active branch pointer."""
        with self._lock:
            if session_id not in self._branches:
                raise KeyError(f"Session '{session_id}' not found.")
            if branch_id not in self._branches[session_id]:
                raise KeyError(f"Branch '{branch_id}' not found in session '{session_id}'.")
            self._active_branch[session_id] = branch_id

    def get_active_branch_id(self, session_id: str) -> str:
        """Query currently active branch ID."""
        with self._lock:
            if session_id not in self._active_branch:
                raise KeyError(f"Session '{session_id}' not found.")
            return self._active_branch[session_id]

    def get_active_projected_timeline(self, session_id: str) -> tuple[TreeNodeMessage, ...]:
        """Project linear timeline from active branch head up to root."""
        with self._lock:
            if session_id not in self._messages:
                return ()

            active_branch = self._active_branch.get(session_id)
            if not active_branch:
                return ()

            head_id = self._branch_heads[session_id].get(active_branch)
            if not head_id:
                return ()

            timeline: list[TreeNodeMessage] = []
            curr_id: str | None = head_id
            while curr_id is not None:
                msg = self._messages[session_id].get(curr_id)
                if msg is None:
                    break
                timeline.append(msg)
                curr_id = msg.parent_id

            timeline.reverse()
            return tuple(timeline)

    def get_version_navigation_for_node(
        self,
        session_id: str,
        parent_id: str | None,
    ) -> VersionNavigationInfo:
        """Compute version navigation pagination (e.g. Version 1/2 ◀ ▶) for sibling branches."""
        with self._lock:
            if session_id not in self._children:
                return VersionNavigationInfo(
                    parent_id=parent_id,
                    current_version_index=0,
                    total_versions=0,
                    available_branch_ids=(),
                    active_branch_id="",
                    active_message_id=None,
                )

            sibling_ids = self._children[session_id].get(parent_id, [])
            total = len(sibling_ids)
            if total == 0:
                return VersionNavigationInfo(
                    parent_id=parent_id,
                    current_version_index=0,
                    total_versions=0,
                    available_branch_ids=(),
                    active_branch_id=self._active_branch.get(session_id, ""),
                    active_message_id=None,
                )

            # Discover which sibling belongs to the active branch
            active_branch = self._active_branch.get(session_id, "")
            current_index = 1
            active_msg_id: str | None = None
            branch_ids: list[str] = []

            for idx, msg_id in enumerate(sibling_ids, start=1):
                msg = self._messages[session_id][msg_id]
                branch_ids.append(msg.branch_id)
                if msg.branch_id == active_branch:
                    current_index = idx
                    active_msg_id = msg_id

            if active_msg_id is None and sibling_ids:
                # Default to latest sibling
                current_index = total
                active_msg_id = sibling_ids[-1]

            return VersionNavigationInfo(
                parent_id=parent_id,
                current_version_index=current_index,
                total_versions=total,
                available_branch_ids=tuple(branch_ids),
                active_branch_id=active_branch,
                active_message_id=active_msg_id,
            )
