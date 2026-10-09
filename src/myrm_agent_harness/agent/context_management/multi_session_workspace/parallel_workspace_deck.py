"""Parallel multi-session workspace deck and grid viewport coordinator.

[INPUT]
- workspace_types: GridLayoutType, MultiSessionWorkspaceConfig, SlotRoleTag,
  WorkspaceDeckState, WorkspaceSlot.

[OUTPUT]
- ParallelWorkspaceDeck: Coordinates parallel session slots across 1x2, 2x2,
  and tabbed split-view layouts, isolating execution focus.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.multi_session_workspace
- Module: parallel_workspace_deck.py
"""

from typing import Dict, List, Optional, Sequence

from myrm_agent_harness.agent.context_management.multi_session_workspace.workspace_types import (
    GridLayoutType,
    MultiSessionWorkspaceConfig,
    SlotRoleTag,
    WorkspaceDeckState,
    WorkspaceSlot,
)


class ParallelWorkspaceDeck:
    """Coordinates parallel multi-session viewports to prevent single-thread UI lock-in."""

    def __init__(self, config: Optional[MultiSessionWorkspaceConfig] = None) -> None:
        self._config = config or MultiSessionWorkspaceConfig()
        self._layout_type: GridLayoutType = GridLayoutType.SINGLE
        self._slots: Dict[str, WorkspaceSlot] = {}
        self._active_slot_id: str = "slot-0"

        # Initialize default slot
        self._slots["slot-0"] = WorkspaceSlot(
            slot_id="slot-0",
            assigned_session_id=None,
            is_focused=True,
            slot_title="Main Session",
            role_tag=SlotRoleTag.PRIMARY_WORKER,
        )

    def reconfigure_layout(
        self,
        new_layout: GridLayoutType,
        initial_sessions: Optional[Sequence[str]] = None,
    ) -> WorkspaceDeckState:
        """Restructures the viewport grid layout and accommodates active sessions.

        Args:
            new_layout: Target grid layout mode.
            initial_sessions: Optional list of session IDs to dock into allocated slots.

        Returns:
            Snapshot of the newly arranged workspace deck state.
        """
        self._layout_type = new_layout

        required_slots = 1
        if new_layout in (GridLayoutType.SPLIT_HORIZONTAL, GridLayoutType.SPLIT_VERTICAL):
            required_slots = 2
        elif new_layout == GridLayoutType.QUAD_GRID:
            required_slots = min(4, self._config.max_slots_allowed)
        elif new_layout == GridLayoutType.TABBED:
            required_slots = min(max(1, len(initial_sessions or [])), self._config.max_slots_allowed)

        # Preserve existing assigned sessions if possible
        existing_assigned: List[Optional[str]] = [
            slot.assigned_session_id for slot in self._slots.values() if slot.assigned_session_id
        ]
        if initial_sessions:
            existing_assigned = list(initial_sessions)

        new_slots: Dict[str, WorkspaceSlot] = {}
        for idx in range(required_slots):
            slot_id = f"slot-{idx}"
            sess_id = existing_assigned[idx] if idx < len(existing_assigned) else None
            role = SlotRoleTag.PRIMARY_WORKER if idx == 0 else SlotRoleTag.INTERACTIVE_COPILOT
            is_focused = idx == 0
            new_slots[slot_id] = WorkspaceSlot(
                slot_id=slot_id,
                assigned_session_id=sess_id,
                is_focused=is_focused,
                slot_title=f"Viewport {idx + 1}" if idx > 0 else "Primary Worker",
                role_tag=role,
            )

        self._slots = new_slots
        self._active_slot_id = "slot-0"
        return self.get_state_snapshot()

    def dock_session(
        self,
        slot_id: str,
        session_id: str,
        slot_title: Optional[str] = None,
        role_tag: Optional[SlotRoleTag] = None,
    ) -> WorkspaceDeckState:
        """Docks a session into a specific slot in the workspace.

        Args:
            slot_id: Target viewport identifier.
            session_id: Session identifier to dock.
            slot_title: Optional friendly title.
            role_tag: Role classification for the docked session.

        Returns:
            Updated workspace deck snapshot.
        """
        if slot_id not in self._slots:
            # Create slot dynamically if under max allowed limit
            if len(self._slots) < self._config.max_slots_allowed:
                self._slots[slot_id] = WorkspaceSlot(
                    slot_id=slot_id,
                    assigned_session_id=session_id,
                    is_focused=False,
                    slot_title=slot_title or f"Session {session_id[:8]}",
                    role_tag=role_tag or SlotRoleTag.INTERACTIVE_COPILOT,
                )
            else:
                return self.get_state_snapshot()
        else:
            current = self._slots[slot_id]
            self._slots[slot_id] = WorkspaceSlot(
                slot_id=slot_id,
                assigned_session_id=session_id,
                is_focused=current.is_focused,
                slot_title=slot_title or current.slot_title,
                role_tag=role_tag or current.role_tag,
            )

        return self.get_state_snapshot()

    def focus_slot(self, slot_id: str) -> WorkspaceDeckState:
        """Sets the active focused slot."""
        if slot_id not in self._slots:
            return self.get_state_snapshot()

        self._active_slot_id = slot_id
        for sid, slot in list(self._slots.items()):
            self._slots[sid] = WorkspaceSlot(
                slot_id=slot.slot_id,
                assigned_session_id=slot.assigned_session_id,
                is_focused=(sid == slot_id),
                slot_title=slot.slot_title,
                role_tag=slot.role_tag,
            )

        return self.get_state_snapshot()

    def release_session(self, session_id: str) -> WorkspaceDeckState:
        """Undocks a session from any slot it occupies."""
        for sid, slot in list(self._slots.items()):
            if slot.assigned_session_id == session_id:
                self._slots[sid] = WorkspaceSlot(
                    slot_id=slot.slot_id,
                    assigned_session_id=None,
                    is_focused=slot.is_focused,
                    slot_title="Empty Slot",
                    role_tag=slot.role_tag,
                )
        return self.get_state_snapshot()

    def get_state_snapshot(self) -> WorkspaceDeckState:
        """Returns the current state snapshot of the parallel workspace deck."""
        slots_seq = tuple(self._slots.values())
        active_count = sum(1 for s in slots_seq if s.assigned_session_id is not None)
        return WorkspaceDeckState(
            layout_type=self._layout_type,
            slots=slots_seq,
            active_slot_id=self._active_slot_id,
            total_active_sessions=active_count,
        )
