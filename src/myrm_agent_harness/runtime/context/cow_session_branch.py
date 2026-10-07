"""Instant Session Forking and Copy-on-Write (CoW) State Branching Engine.

Enables O(1) instantaneous session branching from any conversational turn,
avoiding full history deep-copying while providing transparent virtual
projected views across immutable ancestor lineages and delta mutations.

[INPUT]
- runtime.context.cow_session_branch_types::BranchMessageEntry, CoWArtifactRecord, ProjectedSessionView,
  SessionBranchDescriptor (POS: Type definitions for Instant Session Forking and Copy-on-Write (CoW) State
  Branching.)

[OUTPUT]
- CoWSessionBranchManager: Manages session fork trees with copy-on-write message and artifact stores.

[POS]
Instant Session Forking and Copy-on-Write (CoW) State Branching Engine.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from threading import RLock

from myrm_agent_harness.runtime.context.cow_session_branch_types import (
    BranchMessageEntry,
    CoWArtifactRecord,
    ProjectedSessionView,
    SessionBranchDescriptor,
)

__all__ = [
    "BranchMessageEntry",
    "CoWArtifactRecord",
    "CoWSessionBranchManager",
    "ProjectedSessionView",
    "SessionBranchDescriptor",
]


class CoWSessionBranchManager:
    """Manages session fork trees with copy-on-write message and artifact stores."""

    def __init__(self) -> None:
        self._lock = RLock()
        # session_id -> descriptor
        self._branches: dict[str, SessionBranchDescriptor] = {}
        # session_id -> local message deltas
        self._message_deltas: dict[str, list[BranchMessageEntry]] = {}
        # session_id -> {artifact_id: CoWArtifactRecord} (local overrides only)
        self._artifact_overrides: dict[str, dict[str, CoWArtifactRecord]] = {}

    def create_root_session(
        self,
        session_id: str,
        initial_messages: Sequence[BranchMessageEntry] | None = None,
        branch_label: str = "main",
    ) -> SessionBranchDescriptor:
        """Initializes a root session branch with depth 0."""
        with self._lock:
            if session_id in self._branches:
                raise ValueError(f"Session '{session_id}' already exists.")

            descriptor = SessionBranchDescriptor(
                session_id=session_id,
                parent_session_id=None,
                fork_point_turn_id=None,
                branch_label=branch_label,
                created_at=time.time(),
                depth=0,
            )
            self._branches[session_id] = descriptor
            self._message_deltas[session_id] = list(initial_messages or [])
            self._artifact_overrides[session_id] = {}
            return descriptor

    def fork_session(
        self,
        parent_session_id: str,
        fork_point_turn_id: str,
        new_session_id: str,
        branch_label: str = "branch",
    ) -> SessionBranchDescriptor:
        """Performs O(1) instant session forking at a specific turn without deep-copying."""
        with self._lock:
            if parent_session_id not in self._branches:
                raise KeyError(f"Parent session '{parent_session_id}' does not exist.")
            if new_session_id in self._branches:
                raise ValueError(f"Session '{new_session_id}' already exists.")

            # Validate fork_point_turn_id exists in the parent's projected view
            parent_view = self._build_projected_view_unlocked(parent_session_id)
            turn_ids = {msg.turn_id for msg in parent_view.messages}
            if fork_point_turn_id not in turn_ids:
                raise ValueError(
                    f"Fork point turn '{fork_point_turn_id}' not found in parent session history."
                )

            parent_desc = self._branches[parent_session_id]
            descriptor = SessionBranchDescriptor(
                session_id=new_session_id,
                parent_session_id=parent_session_id,
                fork_point_turn_id=fork_point_turn_id,
                branch_label=branch_label,
                created_at=time.time(),
                depth=parent_desc.depth + 1,
            )

            self._branches[new_session_id] = descriptor
            self._message_deltas[new_session_id] = []
            self._artifact_overrides[new_session_id] = {}
            return descriptor

    def append_message(self, session_id: str, message: BranchMessageEntry) -> None:
        """Appends a local mutation message to the specified branch."""
        with self._lock:
            if session_id not in self._branches:
                raise KeyError(f"Session '{session_id}' does not exist.")
            self._message_deltas[session_id].append(message)

    def upsert_artifact(
        self,
        session_id: str,
        artifact_id: str,
        content: str,
    ) -> CoWArtifactRecord:
        """Writes an artifact in copy-on-write isolation for the given session branch."""
        with self._lock:
            if session_id not in self._branches:
                raise KeyError(f"Session '{session_id}' does not exist.")

            # Determine previous version across ancestor inheritance or local overrides
            prev_record = self._resolve_artifact_unlocked(session_id, artifact_id)
            next_version = (prev_record.version + 1) if prev_record is not None else 1

            new_record = CoWArtifactRecord(
                artifact_id=artifact_id,
                version=next_version,
                content=content,
                updated_at=time.time(),
                origin_session_id=session_id,
            )
            self._artifact_overrides[session_id][artifact_id] = new_record
            return new_record

    def get_projected_view(self, session_id: str) -> ProjectedSessionView:
        """Retrieves transparent composite view merging ancestor chain and local mutations."""
        with self._lock:
            if session_id not in self._branches:
                raise KeyError(f"Session '{session_id}' does not exist.")
            return self._build_projected_view_unlocked(session_id)

    def list_child_branches(self, parent_session_id: str) -> tuple[SessionBranchDescriptor, ...]:
        """Lists all directly derived child branches from a parent session."""
        with self._lock:
            children = [
                desc
                for desc in self._branches.values()
                if desc.parent_session_id == parent_session_id
            ]
            return tuple(sorted(children, key=lambda c: c.created_at))

    def get_branch_hierarchy_tree(self, root_session_id: str) -> dict[str, object]:
        """Builds a hierarchical tree dictionary representing branch lineage for UI rendering."""
        with self._lock:
            if root_session_id not in self._branches:
                raise KeyError(f"Root session '{root_session_id}' does not exist.")

            def _build_node(sid: str) -> dict[str, object]:
                desc = self._branches[sid]
                children = [
                    _build_node(child_desc.session_id)
                    for child_desc in self.list_child_branches(sid)
                ]
                return {
                    "session_id": sid,
                    "branch_label": desc.branch_label,
                    "depth": desc.depth,
                    "fork_point_turn_id": desc.fork_point_turn_id,
                    "children": children,
                }

            return _build_node(root_session_id)

    # --- Internal unlocked helpers ---

    def _build_projected_view_unlocked(self, session_id: str) -> ProjectedSessionView:
        """Traverses the ancestor lineage path and splices messages up to fork points."""
        lineage_descriptors: list[SessionBranchDescriptor] = []
        curr_id: str | None = session_id
        visited: set[str] = set()

        while curr_id is not None:
            if curr_id in visited:
                raise RuntimeError(f"Detected cyclical branch lineage at session '{curr_id}'.")
            visited.add(curr_id)
            desc = self._branches[curr_id]
            lineage_descriptors.append(desc)
            curr_id = desc.parent_session_id

        # Reverse so we iterate from root -> ... -> target
        lineage_descriptors.reverse()

        collected_messages: list[BranchMessageEntry] = []
        inherited_count = 0

        # Process all ancestors except target
        for i in range(len(lineage_descriptors) - 1):
            parent_desc = lineage_descriptors[i]
            child_desc = lineage_descriptors[i + 1]
            fork_turn = child_desc.fork_point_turn_id

            deltas = self._message_deltas[parent_desc.session_id]
            for msg in deltas:
                collected_messages.append(msg)
                if msg.turn_id == fork_turn:
                    break

        inherited_count = len(collected_messages)

        # Append target's local deltas
        target_desc = lineage_descriptors[-1]
        local_deltas = self._message_deltas[target_desc.session_id]
        collected_messages.extend(local_deltas)
        local_count = len(local_deltas)

        # Resolve CoW artifacts across lineage
        artifacts_map: dict[str, CoWArtifactRecord] = {}
        for desc in lineage_descriptors:
            for art_id, art_rec in self._artifact_overrides[desc.session_id].items():
                artifacts_map[art_id] = art_rec

        lineage_path = tuple(d.session_id for d in lineage_descriptors)

        return ProjectedSessionView(
            session_id=session_id,
            branch_label=target_desc.branch_label,
            messages=tuple(collected_messages),
            artifacts=artifacts_map,
            inherited_turns_count=inherited_count,
            local_turns_count=local_count,
            total_turns_count=inherited_count + local_count,
            lineage_path=lineage_path,
        )

    def _resolve_artifact_unlocked(
        self, session_id: str, artifact_id: str
    ) -> CoWArtifactRecord | None:
        """Finds the most recent version of an artifact traversing upwards through ancestors."""
        curr_id: str | None = session_id
        while curr_id is not None:
            overrides = self._artifact_overrides.get(curr_id, {})
            if artifact_id in overrides:
                return overrides[artifact_id]
            desc = self._branches.get(curr_id)
            curr_id = desc.parent_session_id if desc else None
        return None
