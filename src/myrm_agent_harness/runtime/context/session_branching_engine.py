from __future__ import annotations

import time
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence

from myrm_agent_harness.runtime.context.session_branching_types import (
    BranchDescriptor,
    BranchHistoricalTurn,
    BranchNavigatorView,
    ForkSessionResult,
    RewindMode,
    RewindSessionResult,
)


class SessionBranchingEngine:
    """Core engine for arbitrary checkpoint session forking, timeline rewinding, and lineage tracking."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[BranchHistoricalTurn]] = {}
        self._descriptors: dict[str, BranchDescriptor] = {}
        self._children_map: defaultdict[str, list[str]] = defaultdict(list)

    def register_session(
        self,
        session_id: str,
        initial_turns: Sequence[BranchHistoricalTurn] | None = None,
        branch_name: str = "main",
        workspace_root: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> BranchDescriptor:
        """Register a base or root session in the engine."""
        self._sessions[session_id] = list(initial_turns or [])
        descriptor = BranchDescriptor(
            session_id=session_id,
            branch_name=branch_name,
            parent_session_id=None,
            fork_point_message_id=None,
            fork_point_turn_index=0,
            created_at_ms=int(time.time() * 1000),
            workspace_root=workspace_root,
            metadata=dict(metadata or {}),
        )
        self._descriptors[session_id] = descriptor
        return descriptor

    def append_turn(self, session_id: str, turn: BranchHistoricalTurn) -> None:
        """Append a completed turn to an active session."""
        if session_id not in self._sessions:
            raise KeyError(f"Session '{session_id}' not found.")
        self._sessions[session_id].append(turn)

    def get_session_turns(self, session_id: str) -> list[BranchHistoricalTurn]:
        """Retrieve copy of all active turns in a session."""
        if session_id not in self._sessions:
            raise KeyError(f"Session '{session_id}' not found.")
        return list(self._sessions[session_id])

    def get_descriptor(self, session_id: str) -> BranchDescriptor | None:
        """Retrieve descriptor of a session branch."""
        return self._descriptors.get(session_id)

    def fork_session(
        self,
        parent_session_id: str,
        fork_point_message_id: str,
        branch_name: str | None = None,
        new_workspace_root: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> ForkSessionResult:
        """Fork an existing session at a specific message checkpoint to spawn an independent branch."""
        if parent_session_id not in self._sessions:
            raise KeyError(f"Parent session '{parent_session_id}' not found.")

        parent_turns = self._sessions[parent_session_id]
        fork_idx = -1
        for idx, turn in enumerate(parent_turns):
            if turn.message_id == fork_point_message_id:
                fork_idx = idx
                break

        if fork_idx == -1:
            raise ValueError(
                f"Fork point message '{fork_point_message_id}' not found in parent session '{parent_session_id}'."
            )

        # Clone history up to and including the target fork message
        cloned_turns = [
            BranchHistoricalTurn(
                message_id=t.message_id,
                role=t.role,
                content=t.content,
                tool_calls=list(t.tool_calls),
                created_at_ms=t.created_at_ms,
            )
            for t in parent_turns[: fork_idx + 1]
        ]

        child_session_id = f"sess_{uuid.uuid4().hex[:8]}"
        existing_children = self._children_map[parent_session_id]
        b_name = branch_name or f"branch_{len(existing_children) + 1}"

        descriptor = BranchDescriptor(
            session_id=child_session_id,
            branch_name=b_name,
            parent_session_id=parent_session_id,
            fork_point_message_id=fork_point_message_id,
            fork_point_turn_index=fork_idx + 1,
            created_at_ms=int(time.time() * 1000),
            workspace_root=new_workspace_root,
            metadata=dict(metadata or {}),
        )

        self._sessions[child_session_id] = cloned_turns
        self._descriptors[child_session_id] = descriptor
        self._children_map[parent_session_id].append(child_session_id)

        return ForkSessionResult(
            new_session_id=child_session_id,
            branch_descriptor=descriptor,
            cloned_turns=cloned_turns,
        )

    def rewind_session(
        self,
        session_id: str,
        target_message_id: str,
        mode: RewindMode = RewindMode.IN_PLACE_TRUNCATE,
    ) -> RewindSessionResult:
        """Rewind a session timeline to target message via in-place truncation or staging fork."""
        if session_id not in self._sessions:
            raise KeyError(f"Session '{session_id}' not found.")

        turns = self._sessions[session_id]
        target_idx = -1
        for idx, turn in enumerate(turns):
            if turn.message_id == target_message_id:
                target_idx = idx
                break

        if target_idx == -1:
            raise ValueError(
                f"Target rewind message '{target_message_id}' not found in session '{session_id}'."
            )

        if mode == RewindMode.STAGING_BRANCH:
            fork_res = self.fork_session(
                parent_session_id=session_id,
                fork_point_message_id=target_message_id,
                branch_name=f"staging_rewind_{uuid.uuid4().hex[:4]}",
            )
            return RewindSessionResult(
                session_id=session_id,
                mode=mode,
                target_message_id=target_message_id,
                active_turns=list(turns),
                truncated_turns=[],
                created_staging_session_id=fork_res.new_session_id,
            )

        # IN_PLACE_TRUNCATE: truncate turns following target_idx
        active = list(turns[: target_idx + 1])
        truncated = list(turns[target_idx + 1 :])
        self._sessions[session_id] = active

        return RewindSessionResult(
            session_id=session_id,
            mode=mode,
            target_message_id=target_message_id,
            active_turns=active,
            truncated_turns=truncated,
            created_staging_session_id=None,
        )

    def get_navigator_view(self, session_id: str) -> BranchNavigatorView:
        """Construct multi-branch switcher perspective for UI navigation (e.g. Branch 2/3)."""
        current_desc = self._descriptors.get(session_id)
        if current_desc is None:
            raise KeyError(f"Session '{session_id}' not found.")

        parent_id = current_desc.parent_session_id
        if parent_id is not None:
            # Sibling branches are all children of the same parent
            sibling_ids = self._children_map.get(parent_id, [session_id])
        else:
            # Root branch: siblings are root itself
            sibling_ids = [session_id]

        sibling_descriptors = [
            self._descriptors[sid] for sid in sibling_ids if sid in self._descriptors
        ]

        # Calculate current 1-based index among siblings
        current_idx = 1
        for idx, sid in enumerate(sibling_ids):
            if sid == session_id:
                current_idx = idx + 1
                break

        children_ids = self._children_map.get(session_id, [])
        children_descriptors = [
            self._descriptors[cid] for cid in children_ids if cid in self._descriptors
        ]

        return BranchNavigatorView(
            current_session_id=session_id,
            current_branch_name=current_desc.branch_name,
            total_sibling_branches=len(sibling_descriptors),
            current_sibling_index=current_idx,
            sibling_branches=sibling_descriptors,
            parent_session_id=parent_id,
            children_branches=children_descriptors,
        )
