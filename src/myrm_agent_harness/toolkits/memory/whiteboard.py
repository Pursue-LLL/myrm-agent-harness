"""Task Whiteboard for structured working-memory management.

[INPUT]
- myrm_agent_harness.toolkits.memory.consolidation::WorkingMemorySnapshot, ConsolidationSubtask, ConsolidationTrap (POS: 认知中枢终态提炼服务与工作快照)

[OUTPUT]
- TaskWhiteboard: Working memory controller with token budget enforcement, smooth sliding eviction, and prompt block rendering
- TaskStep: Dataclass representing a discrete execution unit with lifecycle status
- StepStatus: Enum for task step progress state (PENDING, IN_PROGRESS, COMPLETED, FAILED)
- WhiteboardFlushResult: Summary of stale eviction operations

[POS]
Task whiteboard component for working-memory management. Tracks active goals, execution steps, temporary variables, and failure traps with prefix-cacheable prompt rendering and token-budget eviction.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from myrm_agent_harness.toolkits.memory.consolidation import (
    ConsolidationSubtask,
    ConsolidationTrap,
    WorkingMemorySnapshot,
)

__all__ = [
    "StepStatus",
    "TaskStep",
    "TaskWhiteboard",
    "WhiteboardFlushResult",
]


class StepStatus(StrEnum):
    """Execution status of a discrete task step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class TaskStep:
    """Discrete execution step within the active task lifecycle."""

    id: str
    title: str
    status: StepStatus = StepStatus.PENDING
    detail: str = ""
    created_turn: int = 0
    completed_turn: int | None = None


@dataclass(slots=True)
class WhiteboardFlushResult:
    """Summary of eviction metrics during stale memory sliding."""

    evicted_step_count: int
    evicted_variable_count: int
    tokens_before: int
    tokens_after: int


class TaskWhiteboard:
    """Token-budgeted working memory whiteboard for active task execution.

    Maintains goals, step progress, context variables, and encountered failure traps.
    Ensures bounded token growth via smooth sliding eviction rather than abrupt truncations.
    Renders as an XML prompt block suited for User message insertion, avoiding System
    Prompt mutations to preserve Prefix Cache efficiency.
    """

    def __init__(
        self,
        *,
        goal: str = "",
        token_budget: int = 500,
        active_turn: int = 0,
    ) -> None:
        self._goal = goal
        self._token_budget = token_budget
        self._active_turn = active_turn
        self._steps: list[TaskStep] = []
        self._context_variables: dict[str, str] = {}
        self._traps: list[ConsolidationTrap] = []

    @property
    def goal(self) -> str:
        return self._goal

    @goal.setter
    def goal(self, value: str) -> None:
        self._goal = value.strip()

    @property
    def active_turn(self) -> int:
        return self._active_turn

    @active_turn.setter
    def active_turn(self, turn: int) -> None:
        self._active_turn = turn

    @property
    def token_budget(self) -> int:
        return self._token_budget

    @property
    def steps(self) -> Sequence[TaskStep]:
        return tuple(self._steps)

    @property
    def context_variables(self) -> dict[str, str]:
        return dict(self._context_variables)

    @property
    def traps(self) -> Sequence[ConsolidationTrap]:
        return tuple(self._traps)

    def add_step(self, title: str, *, detail: str = "") -> TaskStep:
        """Append a new pending step to the whiteboard plan."""
        step = TaskStep(
            id=str(uuid.uuid4())[:8],
            title=title.strip(),
            status=StepStatus.PENDING,
            detail=detail.strip(),
            created_turn=self._active_turn,
        )
        self._steps.append(step)
        return step

    def start_step(self, step_id: str) -> bool:
        """Mark a specific step as in_progress."""
        for step in self._steps:
            if step.id == step_id:
                step.status = StepStatus.IN_PROGRESS
                return True
        return False

    def complete_step(self, step_id: str, *, detail: str | None = None) -> bool:
        """Mark a specific step as completed, optionally updating its outcome detail."""
        for step in self._steps:
            if step.id == step_id:
                step.status = StepStatus.COMPLETED
                step.completed_turn = self._active_turn
                if detail is not None:
                    step.detail = detail.strip()
                return True
        return False

    def fail_step(self, step_id: str, *, reason: str = "") -> bool:
        """Mark a specific step as failed with an explanatory reason."""
        for step in self._steps:
            if step.id == step_id:
                step.status = StepStatus.FAILED
                step.completed_turn = self._active_turn
                if reason:
                    step.detail = reason.strip()
                return True
        return False

    def set_variable(self, key: str, value: str) -> None:
        """Assign or update a context variable in the scratchpad."""
        self._context_variables[key] = value

    def get_variable(self, key: str, default: str | None = None) -> str | None:
        """Retrieve a context variable value."""
        return self._context_variables.get(key, default)

    def delete_variable(self, key: str) -> bool:
        """Remove a context variable from the scratchpad."""
        return self._context_variables.pop(key, None) is not None

    def record_trap(
        self,
        fingerprint: str,
        avoidance_rule: str,
        *,
        tool_name: str | None = None,
        resolved: bool = False,
    ) -> None:
        """Register a neutral failure site trap to prevent repetitive error loops."""
        self._traps.append(
            ConsolidationTrap(
                fingerprint=fingerprint,
                avoidance_rule=avoidance_rule,
                tool_name=tool_name,
                occurred_turn=self._active_turn,
                resolved=resolved,
            )
        )

    def estimate_tokens(self) -> int:
        """Estimate token footprint of the whiteboard state.

        Uses standard character-to-token ratio (approx 3.2 chars/token across multilingual contexts)
        to avoid heavy tokenizer runtime dependencies while guaranteeing deterministic boundaries.
        """
        raw = self.render_prompt_block()
        return max(1, math.ceil(len(raw) / 3.2))

    def render_prompt_block(self) -> str:
        """Render the whiteboard as an XML structured block suitable for context injection."""
        lines: list[str] = ["<task_whiteboard>"]

        if self._goal:
            lines.append(f"  <goal>{self._goal}</goal>")

        if self._steps:
            lines.append("  <steps>")
            for s in self._steps:
                flag = {
                    StepStatus.PENDING: "[ ]",
                    StepStatus.IN_PROGRESS: "[>]",
                    StepStatus.COMPLETED: "[x]",
                    StepStatus.FAILED: "[!]",
                }.get(s.status, "[ ]")
                detail_suffix = f" - {s.detail}" if s.detail else ""
                lines.append(f"    {flag} ({s.id}) {s.title}{detail_suffix}")
            lines.append("  </steps>")

        if self._context_variables:
            lines.append("  <context_variables>")
            for k, v in self._context_variables.items():
                lines.append(f"    {k}: {v}")
            lines.append("  </context_variables>")

        if self._traps:
            active_traps = [t for t in self._traps if not t.resolved]
            if active_traps:
                lines.append("  <failure_traps>")
                for t in active_traps:
                    tool_desc = f" [{t.tool_name}]" if t.tool_name else ""
                    lines.append(f"    - Avoid{tool_desc}: {t.avoidance_rule}")
                lines.append("  </failure_traps>")

        lines.append("</task_whiteboard>")
        return "\n".join(lines)

    def flush_stale(self, flush_ratio: float = 0.5) -> WhiteboardFlushResult:
        """Evict completed steps and stale context variables when exceeding budget.

        Prioritizes evicting oldest completed tasks, preserving the primary goal,
        in-progress steps, and pending obligations. Never cuts active steps.
        """
        before = self.estimate_tokens()
        if before <= self._token_budget:
            return WhiteboardFlushResult(
                evicted_step_count=0,
                evicted_variable_count=0,
                tokens_before=before,
                tokens_after=before,
            )

        # 1. Identify completed steps candidates for eviction
        completed_steps = [s for s in self._steps if s.status == StepStatus.COMPLETED]
        num_steps_to_evict = max(1, math.ceil(len(completed_steps) * flush_ratio)) if completed_steps else 0
        evicted_step_ids = {s.id for s in completed_steps[:num_steps_to_evict]}

        self._steps = [s for s in self._steps if s.id not in evicted_step_ids]

        # 2. If still exceeding budget, evict oldest context variables
        evicted_var_count = 0
        current_tokens = self.estimate_tokens()
        if current_tokens > self._token_budget and self._context_variables:
            keys = list(self._context_variables.keys())
            num_vars_to_evict = max(1, math.ceil(len(keys) * flush_ratio))
            for k in keys[:num_vars_to_evict]:
                del self._context_variables[k]
                evicted_var_count += 1

        after = self.estimate_tokens()
        return WhiteboardFlushResult(
            evicted_step_count=len(evicted_step_ids),
            evicted_variable_count=evicted_var_count,
            tokens_before=before,
            tokens_after=after,
        )

    def to_working_memory_snapshot(self, status: str = "completed") -> WorkingMemorySnapshot:
        """Convert current whiteboard into a neutral WorkingMemorySnapshot for consolidation."""
        subtasks = [
            ConsolidationSubtask(
                title=s.title,
                completed=(s.status == StepStatus.COMPLETED),
            )
            for s in self._steps
        ]
        return WorkingMemorySnapshot(
            goal=self._goal,
            active_turn=self._active_turn,
            status=status,
            subtasks=subtasks,
            traps=list(self._traps),
            scratchpad=dict(self._context_variables),
        )
