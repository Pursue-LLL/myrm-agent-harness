"""Local Working Memory Block implementation.

[INPUT]
- context_management.working_memory.types::LocalWorkingState (POS: 工作台运行时强类型状态实体)
- context_management.working_memory.types::SubtaskItem (POS: 工作台子任务条目实体)

[OUTPUT]
- LocalWorkingMemoryBlock: 运行时零开销手边工作台，管理长程目标栈、子任务状态推进、避坑防线并生成 Turn-Tail Markdown

[POS]
- 执行引擎运行时工作台核心。基于 ContextVar 实现并发强隔离的手边工作区，严格遵从 Prompt Cache 规则仅在 Turn Tail 注入。
"""

from __future__ import annotations

import contextvars
import math
from typing import Literal

from myrm_agent_harness.agent.context_management.working_memory.types import (
    LocalWorkingState,
    SubtaskItem,
    SubtaskStatus,
    TrapRecord,
    WorkingMemoryFlushResult,
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
    def initialize(
        cls,
        goal: str,
        initial_subtasks: list[str] | None = None,
        prior_traps: list[dict[str, str]] | None = None,
    ) -> LocalWorkingState:
        """Initialize or replace the working state for the active execution run."""
        subtasks: list[SubtaskItem] = []
        if initial_subtasks:
            for idx, title in enumerate(initial_subtasks, start=1):
                subtasks.append(SubtaskItem(id=f"step-{idx}", title=title, status=SubtaskStatus.PENDING))

        traps: list[TrapRecord] = []
        if prior_traps:
            for trap_dict in prior_traps:
                fp = str(trap_dict.get("fingerprint", ""))
                rule = str(trap_dict.get("avoidance_rule", ""))
                t_name = trap_dict.get("tool_name")
                if fp and rule:
                    traps.append(
                        TrapRecord(
                            fingerprint=fp,
                            avoidance_rule=rule,
                            tool_name=str(t_name) if t_name else None,
                            occurred_turn=0,
                        )
                    )

        state = LocalWorkingState(
            goal=goal.strip(),
            status="active",
            subtasks=subtasks,
            traps=traps,
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
    def resolve_trap(cls, fingerprint: str) -> bool:
        """Mark a transient error trap as successfully avoided/resolved."""
        state = cls.get_state()
        if state is None:
            return False

        for trap in state.traps:
            if trap.fingerprint == fingerprint:
                trap.resolved = True
                return True
        return False

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
    def estimate_tokens(cls, state: LocalWorkingState | None = None) -> int:
        """Estimate token footprint of the working memory state.

        Uses standard character-to-token ratio (approx 3.2 chars/token across multilingual contexts)
        to avoid heavy tokenizer runtime dependencies while guaranteeing deterministic boundaries.
        """
        target_state = state if state is not None else cls.get_state()
        if target_state is None or not target_state.goal:
            return 0
        raw = (
            target_state.goal
            + "".join(f"{s.id}{s.title}{s.notes}" for s in target_state.subtasks)
            + "".join(f"{t.fingerprint}{t.avoidance_rule}{t.tool_name or ''}" for t in target_state.traps)
            + "".join(f"{k}{v}" for k, v in target_state.scratchpad.items())
        )
        return max(1, math.ceil(len(raw) / 3.2))

    @classmethod
    def flush_stale(
        cls,
        flush_ratio: float = 0.5,
        token_budget: int | None = None,
    ) -> WorkingMemoryFlushResult:
        """Purge completed subtasks and stale scratchpad entries to prevent context bloat.

        Prioritizes evicting oldest completed/skipped tasks, preserving the primary goal,
        in-progress steps, pending obligations, and failure traps. Never drops active steps.
        If token_budget is specified and current consumption is within budget, eviction is skipped.
        """
        state = cls.get_state()
        if state is None:
            return WorkingMemoryFlushResult()

        before = cls.estimate_tokens(state)
        if token_budget is not None and before <= token_budget:
            return WorkingMemoryFlushResult(
                evicted_subtasks_count=0,
                evicted_scratchpad_count=0,
                remaining_subtasks_count=len(state.subtasks),
                remaining_scratchpad_count=len(state.scratchpad),
                estimated_tokens_before=before,
                estimated_tokens_after=before,
            )

        completed_indices = [
            i
            for i, s in enumerate(state.subtasks)
            if s.status in (SubtaskStatus.COMPLETED, SubtaskStatus.SKIPPED)
        ]
        ratio = max(0.0, min(1.0, flush_ratio))
        num_subtasks_to_evict = max(1, math.ceil(len(completed_indices) * ratio)) if completed_indices else 0
        evict_indices = set(completed_indices[:num_subtasks_to_evict])

        new_subtasks = [s for i, s in enumerate(state.subtasks) if i not in evict_indices]
        evicted_subtasks = len(state.subtasks) - len(new_subtasks)
        state.subtasks = new_subtasks

        evicted_scratch_count = 0
        current_tokens = cls.estimate_tokens(state)
        should_evict_scratch = (
            token_budget is not None and current_tokens > token_budget
        ) or (token_budget is None and bool(state.scratchpad) and ratio > 0.0)

        if should_evict_scratch and state.scratchpad:
            keys = list(state.scratchpad.keys())
            num_vars_to_evict = max(1, math.ceil(len(keys) * ratio))
            for k in keys[:num_vars_to_evict]:
                state.scratchpad.pop(k, None)
                evicted_scratch_count += 1

        after = cls.estimate_tokens(state)
        return WorkingMemoryFlushResult(
            evicted_subtasks_count=evicted_subtasks,
            evicted_scratchpad_count=evicted_scratch_count,
            remaining_subtasks_count=len(state.subtasks),
            remaining_scratchpad_count=len(state.scratchpad),
            estimated_tokens_before=before,
            estimated_tokens_after=after,
        )

    @classmethod
    def format_turn_tail_markdown(
        cls,
        max_traps: int = 3,
        token_budget: int = 500,
    ) -> str:
        """Format a compact, cache-friendly markdown workbench for dynamic turn tail injection.

        Ensures prompt-cache stability: injected ONLY in the dynamic suffix of the current
        turn, keeping system prompt prefixes byte-identical. Protects against context bloat
        via sliding collapse of older completed subtasks when estimated tokens exceed token_budget.
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

            completed_indices = [
                i
                for i, s in enumerate(state.subtasks)
                if s.status in (SubtaskStatus.COMPLETED, SubtaskStatus.SKIPPED)
            ]
            current_est = cls.estimate_tokens(state)

            if current_est > token_budget and len(completed_indices) > 1:
                collapse_count = len(completed_indices) - 1
                hidden_indices = set(completed_indices[:collapse_count])
                lines.append(f"- ✓ [{collapse_count} prior completed subtasks collapsed]")
                visible_subtasks = [s for i, s in enumerate(state.subtasks) if i not in hidden_indices]
            else:
                visible_subtasks = state.subtasks

            for item in visible_subtasks:
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
                if trap.resolved:
                    icon = "✅ [Resolved] "
                elif trap.occurred_turn == 0:
                    icon = "🛡️ [Prior] "
                else:
                    icon = "⚠️ "
                lines.append(f"- {icon}{tool_label}{trap.avoidance_rule}")

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
                    "resolved": trap.resolved,
                }
                for trap in state.traps
            ],
            "scratchpad": dict(state.scratchpad),
            "consolidated": state.consolidated,
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
                            resolved=bool(trap_obj.get("resolved", False)),
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
            consolidated=bool(data.get("consolidated", False)),
        )
        _WORKING_STATE_VAR.set(state)
        return state

    @classmethod
    def reset(cls) -> None:
        """Clear active working state for the current coroutine context."""
        _WORKING_STATE_VAR.set(None)

    @classmethod
    def to_snapshot(cls) -> object | None:
        """Convert current working state into a neutral WorkingMemorySnapshot for consolidation."""
        state = cls.get_state()
        if state is None:
            return None
        from myrm_agent_harness.toolkits.memory.consolidation import (
            ConsolidationSubtask,
            ConsolidationTrap,
            WorkingMemorySnapshot,
        )

        return WorkingMemorySnapshot(
            goal=state.goal,
            active_turn=state.active_turn,
            status=state.status,
            subtasks=[
                ConsolidationSubtask(
                    title=item.title,
                    completed=(item.status == SubtaskStatus.COMPLETED),
                )
                for item in state.subtasks
            ],
            traps=[
                ConsolidationTrap(
                    fingerprint=trap.fingerprint,
                    avoidance_rule=trap.avoidance_rule,
                    tool_name=trap.tool_name,
                    occurred_turn=trap.occurred_turn,
                    resolved=trap.resolved,
                )
                for trap in state.traps
            ],
            scratchpad=dict(state.scratchpad),
        )
