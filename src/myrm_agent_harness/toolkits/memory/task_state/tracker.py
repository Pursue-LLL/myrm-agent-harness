"""Structured Task State Machine Tracker preserving task goals, steps, and todos."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from .models import (
    StructuredTaskState,
    TaskStepItem,
    TaskStepStatus,
    TaskTodoItem,
)


class StructuredTaskStateTracker:
    """Manages the lifecycle of high-privilege task states across long-running multi-turn workflows."""

    def __init__(self) -> None:
        """Initialize in-memory registry of session task states."""
        self._states: dict[str, StructuredTaskState] = {}

    @property
    def total_active_sessions(self) -> int:
        """Return count of actively tracked sessions."""
        return len(self._states)

    def initialize_task(
        self,
        session_id: str,
        goal: str,
        initial_todos: Sequence[str] | None = None,
        task_id: str | None = None,
    ) -> StructuredTaskState:
        """Create or reset structured task state for a session.

        Args:
            session_id: Target session identifier.
            goal: Primary objective of the multi-turn workflow.
            initial_todos: Optional initial list of requirement descriptions.
            task_id: Optional explicit task ID.

        Returns:
            Newly initialized StructuredTaskState instance.
        """
        now = datetime.now(UTC)
        tid = task_id or f"task-{uuid.uuid4().hex[:10]}"
        todos = [
            TaskTodoItem(
                todo_id=f"todo-{idx + 1}",
                description=desc,
                is_resolved=False,
            )
            for idx, desc in enumerate(initial_todos or [])
        ]

        state = StructuredTaskState(
            task_id=tid,
            session_id=session_id,
            current_goal=goal,
            current_phase="planning",
            completed_steps=[],
            active_steps=[],
            todos=todos,
            blockers=[],
            version=1,
            updated_at=now,
        )
        self._states[session_id] = state
        return state

    def get_state(self, session_id: str) -> StructuredTaskState | None:
        """Retrieve state for a given session."""
        return self._states.get(session_id)

    def advance_phase(self, session_id: str, new_phase: str) -> None:
        """Transition task workflow to a new operational phase."""
        state = self._get_or_raise(session_id)
        state.current_phase = new_phase
        self._touch_state(state)

    def start_step(self, session_id: str, step_id: str, title: str) -> None:
        """Record the initiation of an active step."""
        state = self._get_or_raise(session_id)
        step = TaskStepItem(
            step_id=step_id,
            title=title,
            status=TaskStepStatus.IN_PROGRESS,
            started_at=datetime.now(UTC),
        )
        state.active_steps.append(step)
        self._touch_state(state)

    def complete_step(
        self,
        session_id: str,
        step_id: str,
        output_summary: str,
    ) -> None:
        """Mark an in-progress step as completed and archive into completed_steps."""
        state = self._get_or_raise(session_id)
        target_step: TaskStepItem | None = None

        for idx, s in enumerate(state.active_steps):
            if s.step_id == step_id:
                target_step = state.active_steps.pop(idx)
                break

        now = datetime.now(UTC)
        if target_step is None:
            target_step = TaskStepItem(step_id=step_id, title=step_id, started_at=now)

        target_step.status = TaskStepStatus.COMPLETED
        target_step.output_summary = output_summary
        target_step.completed_at = now
        state.completed_steps.append(target_step)
        self._touch_state(state)

    def add_todo(
        self,
        session_id: str,
        description: str,
        priority: str = "normal",
    ) -> str:
        """Append a new todo commitment to the task state."""
        state = self._get_or_raise(session_id)
        todo_id = f"todo-{len(state.todos) + 1}"
        todo = TaskTodoItem(
            todo_id=todo_id,
            description=description,
            is_resolved=False,
            priority=priority,
        )
        state.todos.append(todo)
        self._touch_state(state)
        return todo_id

    def resolve_todo(
        self,
        session_id: str,
        todo_id: str,
        resolution_note: str | None = None,
    ) -> None:
        """Mark an open todo item as resolved."""
        state = self._get_or_raise(session_id)
        for t in state.todos:
            if t.todo_id == todo_id:
                t.is_resolved = True
                t.resolution_note = resolution_note
                self._touch_state(state)
                return
        raise KeyError(f"Todo '{todo_id}' not found in session '{session_id}'.")

    def add_blocker(self, session_id: str, blocker: str) -> None:
        """Register a blocker impeding workflow progress."""
        state = self._get_or_raise(session_id)
        if blocker not in state.blockers:
            state.blockers.append(blocker)
            self._touch_state(state)

    def remove_blocker(self, session_id: str, blocker: str) -> None:
        """Clear a resolved blocker."""
        state = self._get_or_raise(session_id)
        if blocker in state.blockers:
            state.blockers.remove(blocker)
            self._touch_state(state)

    def render_compaction_anchor(self, session_id: str) -> str:
        """Render authoritative Markdown prompt block guaranteed immune to compaction loss.

        Args:
            session_id: Target session identifier.

        Returns:
            Deterministic Markdown text block.
        """
        state = self._get_or_raise(session_id)
        lines: list[str] = [
            "### [ACTIVE TASK STATE ANCHOR - PRESERVED & DO NOT COMPACT]",
            f"- **Current Goal**: {state.current_goal}",
            f"- **Phase**: `{state.current_phase}` (State Version: v{state.version})",
        ]

        # Completed steps
        if state.completed_steps:
            lines.append(f"- **Completed Steps** ({len(state.completed_steps)}):")
            for idx, s in enumerate(state.completed_steps, 1):
                summary = f" -> {s.output_summary}" if s.output_summary else ""
                lines.append(f"  {idx}. [x] {s.title}{summary}")
        else:
            lines.append("- **Completed Steps**: None yet.")

        # Active / In-progress steps
        if state.active_steps:
            lines.append("- **In-Progress Steps**:")
            for s in state.active_steps:
                lines.append(f"  - [>] {s.title} (ID: {s.step_id})")

        # Todos checklist
        if state.todos:
            resolved_count = sum(1 for t in state.todos if t.is_resolved)
            lines.append(f"- **Task Checklist** ({resolved_count}/{len(state.todos)} resolved):")
            for t in state.todos:
                mark = "x" if t.is_resolved else " "
                note = f" (Note: {t.resolution_note})" if t.resolution_note else ""
                lines.append(f"  - [{mark}] [{t.priority.upper()}] {t.description}{note}")

        # Blockers
        if state.blockers:
            lines.append(f"- **Active Blockers** ({len(state.blockers)}):")
            for b in state.blockers:
                lines.append(f"  - [!] {b}")

        return "\n".join(lines)

    def _touch_state(self, state: StructuredTaskState) -> None:
        state.version += 1
        state.updated_at = datetime.now(UTC)

    def _get_or_raise(self, session_id: str) -> StructuredTaskState:
        state = self._states.get(session_id)
        if not state:
            raise KeyError(f"No structured task state found for session '{session_id}'.")
        return state
