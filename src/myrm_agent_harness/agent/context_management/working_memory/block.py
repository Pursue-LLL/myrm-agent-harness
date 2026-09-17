"""Local Working Memory Block implementation.

Provides a fast, zero-LLM in-memory workbench maintaining active goals,
subtasks, execution scratchpad entries, and transient error traps.
Enforces Prompt Cache safety by formatting workbench state strictly for
injection at Dynamic Turn Tail rather than mutating static system prompt prefixes.
"""

from __future__ import annotations

import contextvars
from typing import Literal

from myrm_agent_harness.agent.context_management.working_memory.types import (
    LocalWorkingState,
    SubtaskItem,
    SubtaskStatus,
    TrapRecord,
)

_WORKING_STATE_VAR: contextvars.ContextVar[LocalWorkingState | None] = contextvars.ContextVar(
    "local_working_memory_state", default=None
)


class LocalWorkingMemoryBlock:
    """Zero-overhead in-memory working board scoped to the active execution run."""

    @classmethod
    def get_state(cls) -> LocalWorkingState | None:
        """Retrieve the current coroutine-local working state if initialized."""
        return _WORKING_STATE_VAR.get()

    @classmethod
    def initialize(cls, goal: str, initial_subtasks: list[str] | None = None) -> LocalWorkingState:
        """Initialize or replace the working state for the active execution run."""
        subtasks: list[SubtaskItem] = []
        if initial_subtasks:
            for idx, title in enumerate(initial_subtasks, start=1):
                subtasks.append(SubtaskItem(id=f"step-{idx}", title=title, status=SubtaskStatus.PENDING))

        state = LocalWorkingState(
            goal=goal.strip(),
            status="active",
            subtasks=subtasks,
            traps=[],
            scratchpad={},
            active_turn=1,
        )
        _WORKING_STATE_VAR.set(state)
        return state

    @classmethod
    def add_subtask(cls, title: str, subtask_id: str | None = None) -> SubtaskItem | None:
        """Add a new subtask to the active working state."""
        state = cls.get_state()
        if state is None:
            return None

        resolved_id = subtask_id or f"step-{len(state.subtasks) + 1}"
        item = SubtaskItem(id=resolved_id, title=title.strip(), status=SubtaskStatus.PENDING)
        state.subtasks.append(item)
        return item

    @classmethod
    def update_subtask(
        cls,
        subtask_id: str,
        status: SubtaskStatus,
        notes: str = "",
    ) -> bool:
        """Update the status and optional notes of an existing subtask."""
        state = cls.get_state()
        if state is None:
            return False

        for item in state.subtasks:
            if item.id == subtask_id:
                item.status = status
                if notes:
                    item.notes = notes.strip()
                return True
        return False

    @classmethod
    def record_trap(
        cls,
        fingerprint: str,
        avoidance_rule: str,
        tool_name: str | None = None,
    ) -> None:
        """Register a transient error trap to prevent immediate failure recurrence."""
        state = cls.get_state()
        if state is None:
            return

        # Deduplicate by fingerprint
        for trap in state.traps:
            if trap.fingerprint == fingerprint:
                trap.avoidance_rule = avoidance_rule
                trap.occurred_turn = state.active_turn
                return

        state.traps.append(
            TrapRecord(
                fingerprint=fingerprint,
                avoidance_rule=avoidance_rule,
                tool_name=tool_name,
                occurred_turn=state.active_turn,
            )
        )

    @classmethod
    def set_scratchpad(cls, key: str, value: str) -> None:
        """Store a lightweight transient key-value memo."""
        state = cls.get_state()
        if state is not None:
            state.scratchpad[key.strip()] = value.strip()

    @classmethod
    def get_scratchpad(cls, key: str) -> str | None:
        """Retrieve a transient key-value memo."""
        state = cls.get_state()
        if state is None:
            return None
        return state.scratchpad.get(key.strip())

    @classmethod
    def advance_turn(cls) -> int:
        """Increment the internal turn counter."""
        state = cls.get_state()
        if state is not None:
            state.active_turn += 1
            return state.active_turn
        return 0

    @classmethod
    def set_status(cls, status: Literal["active", "interrupted", "completed", "failed"]) -> None:
        """Update overall execution status."""
        state = cls.get_state()
        if state is not None:
            state.status = status

    @classmethod
    def format_turn_tail_markdown(cls, max_traps: int = 3) -> str:
        """Format a compact, cache-friendly markdown workbench for dynamic turn tail injection.

        Ensures prompt-cache stability: injected ONLY in the dynamic suffix of the current
        turn, keeping system prompt prefixes byte-identical.
        """
        state = cls.get_state()
        if state is None or not state.goal:
            return ""

        lines: list[str] = [
            "<working_board>",
            f"**Goal**: {state.goal}",
        ]

        if state.subtasks:
            lines.append("**Subtasks**:")
            for item in state.subtasks:
                if item.status == SubtaskStatus.COMPLETED:
                    prefix = "[x]"
                elif item.status == SubtaskStatus.IN_PROGRESS:
                    prefix = "[>]"
                elif item.status == SubtaskStatus.FAILED:
                    prefix = "[!]"
                elif item.status == SubtaskStatus.SKIPPED:
                    prefix = "[-]"
                else:
                    prefix = "[ ]"

                note_suffix = f" ({item.notes})" if item.notes else ""
                lines.append(f"- {prefix} {item.id}: {item.title}{note_suffix}")

        if state.traps:
            recent_traps = state.traps[-max_traps:]
            lines.append("**Avoidance Traps**:")
            for trap in recent_traps:
                tool_label = f"[{trap.tool_name}] " if trap.tool_name else ""
                lines.append(f"- ⚠️ {tool_label}{trap.avoidance_rule}")

        lines.append("</working_board>")
        return "\n".join(lines)

    @classmethod
    def to_dict(cls) -> dict[str, object]:
        """Serialize state for persistent checkpoint or frontend transmission."""
        state = cls.get_state()
        if state is None:
            return {}

        return {
            "goal": state.goal,
            "status": state.status,
            "active_turn": state.active_turn,
            "subtasks": [
                {
                    "id": item.id,
                    "title": item.title,
                    "status": str(item.status),
                    "notes": item.notes,
                }
                for item in state.subtasks
            ],
            "traps": [
                {
                    "fingerprint": trap.fingerprint,
                    "avoidance_rule": trap.avoidance_rule,
                    "tool_name": trap.tool_name,
                    "occurred_turn": trap.occurred_turn,
                }
                for trap in state.traps
            ],
            "scratchpad": dict(state.scratchpad),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> LocalWorkingState:
        """Restore state from serialized snapshot (e.g. session resume)."""
        goal = str(data.get("goal", ""))
        status = str(data.get("status", "active"))
        if status not in ("active", "interrupted", "completed", "failed"):
            status = "active"

        raw_subtasks = data.get("subtasks")
        subtasks: list[SubtaskItem] = []
        if isinstance(raw_subtasks, list):
            for sub_obj in raw_subtasks:
                if isinstance(sub_obj, dict):
                    subtasks.append(
                        SubtaskItem(
                            id=str(sub_obj.get("id", "")),
                            title=str(sub_obj.get("title", "")),
                            status=SubtaskStatus(str(sub_obj.get("status", SubtaskStatus.PENDING))),
                            notes=str(sub_obj.get("notes", "")),
                        )
                    )

        raw_traps = data.get("traps")
        traps: list[TrapRecord] = []
        if isinstance(raw_traps, list):
            for trap_obj in raw_traps:
                if isinstance(trap_obj, dict):
                    tool_val = trap_obj.get("tool_name")
                    traps.append(
                        TrapRecord(
                            fingerprint=str(trap_obj.get("fingerprint", "")),
                            avoidance_rule=str(trap_obj.get("avoidance_rule", "")),
                            tool_name=str(tool_val) if tool_val is not None else None,
                            occurred_turn=int(trap_obj.get("occurred_turn", 0)),
                        )
                    )

        raw_scratch = data.get("scratchpad")
        scratchpad: dict[str, str] = {}
        if isinstance(raw_scratch, dict):
            scratchpad = {str(k): str(v) for k, v in raw_scratch.items()}

        state = LocalWorkingState(
            goal=goal,
            status=status,  # type: ignore[arg-type]
            subtasks=subtasks,
            traps=traps,
            scratchpad=scratchpad,
            active_turn=int(data.get("active_turn", 1)),
        )
        _WORKING_STATE_VAR.set(state)
        return state

    @classmethod
    def reset(cls) -> None:
        """Clear active working state for the current coroutine context."""
        _WORKING_STATE_VAR.set(None)
