"""Thread-safe controller governing the lifecycle of Goal-Driven Autonomous Orchestration Loops.

[INPUT]
- Session identifiers, goals, step actions, and AutonomousLoopConfig parameters.

[OUTPUT]
- AutonomousLoopController managing multi-step autonomous pacing, human approvals,
  watchdog caps, and mode toggling.

[POS]
- Harness coordination core engine for autonomous versus supervised loop pacing.
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from myrm_agent_harness.agent.coordination.autonomous_loop.types import (
    AutonomousLoopConfig,
    AutonomousLoopState,
    AutonomousLoopStep,
    OrchestrationMode,
    StepStatus,
)

logger = logging.getLogger(__name__)


class AutonomousLoopController:
    """Thread-safe controller for multi-step autonomous agent execution loops."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._states: dict[str, AutonomousLoopState] = {}
        self._configs: dict[str, AutonomousLoopConfig] = {}

    def start_loop(
        self,
        session_id: str,
        goal_id: str,
        mode: OrchestrationMode = OrchestrationMode.AUTONOMOUS,
        config: AutonomousLoopConfig | None = None,
    ) -> AutonomousLoopState:
        """Initialize and activate an autonomous orchestration loop for a session and goal."""
        if not session_id.strip():
            msg = "session_id cannot be blank"
            raise ValueError(msg)
        if not goal_id.strip():
            msg = "goal_id cannot be blank"
            raise ValueError(msg)

        cfg = config or AutonomousLoopConfig()
        now = datetime.now(tz=UTC)
        normalized_sid = session_id.strip()

        with self._lock:
            self._configs[normalized_sid] = cfg
            initial_state = AutonomousLoopState(
                session_id=normalized_sid,
                goal_id=goal_id.strip(),
                mode=mode,
                current_step=0,
                max_steps=cfg.max_autonomous_steps,
                is_active=(mode == OrchestrationMode.AUTONOMOUS),
                history=[],
                pause_reason="" if mode == OrchestrationMode.AUTONOMOUS else "Supervised mode waiting for manual step",
                started_at=now,
                last_advanced_at=now,
            )
            self._states[normalized_sid] = initial_state

        logger.info(
            "Started autonomous loop for session %s (goal=%s, mode=%s, max_steps=%d)",
            normalized_sid,
            goal_id,
            mode.value,
            cfg.max_autonomous_steps,
        )
        return initial_state

    def advance_step(
        self,
        session_id: str,
        action_type: str,
        description: str,
        requires_approval: bool = False,
        is_error: bool = False,
        metadata: dict[str, str | int | float | bool] | None = None,
    ) -> AutonomousLoopState:
        """Advance the autonomous orchestration loop by one step with safety watchdog checks."""
        normalized_sid = session_id.strip()
        now = datetime.now(tz=UTC)

        with self._lock:
            state = self._states.get(normalized_sid)
            if state is None:
                msg = f"No active autonomous loop found for session '{normalized_sid}'"
                raise KeyError(msg)

            if state.mode == OrchestrationMode.COMPLETED:
                return state

            cfg = self._configs.get(normalized_sid, AutonomousLoopConfig())
            meta = dict(metadata or {})
            next_step_index = state.current_step + 1

            # Check 1: Step budget exhaustion check
            if state.current_step >= state.max_steps:
                paused_state = AutonomousLoopState(
                    session_id=state.session_id,
                    goal_id=state.goal_id,
                    mode=OrchestrationMode.PAUSED,
                    current_step=state.current_step,
                    max_steps=state.max_steps,
                    is_active=False,
                    history=list(state.history),
                    pause_reason="Max autonomous steps limit reached",
                    started_at=state.started_at,
                    last_advanced_at=now,
                )
                self._states[normalized_sid] = paused_state
                return paused_state

            # Check 2: Action requires human approval gate
            if requires_approval and cfg.pause_on_approval:
                step_record = AutonomousLoopStep(
                    step_index=next_step_index,
                    action_type=action_type,
                    description=description,
                    status=StepStatus.PAUSED,
                    timestamp=now,
                    metadata=meta,
                )
                updated_history = [*state.history, step_record]
                paused_state = AutonomousLoopState(
                    session_id=state.session_id,
                    goal_id=state.goal_id,
                    mode=OrchestrationMode.PAUSED,
                    current_step=next_step_index,
                    max_steps=state.max_steps,
                    is_active=False,
                    history=updated_history,
                    pause_reason="Action requires human approval",
                    started_at=state.started_at,
                    last_advanced_at=now,
                )
                self._states[normalized_sid] = paused_state
                return paused_state

            # Check 3: Execution error trigger
            if is_error and cfg.pause_on_error:
                step_record = AutonomousLoopStep(
                    step_index=next_step_index,
                    action_type=action_type,
                    description=description,
                    status=StepStatus.FAILED,
                    timestamp=now,
                    metadata=meta,
                )
                updated_history = [*state.history, step_record]
                paused_state = AutonomousLoopState(
                    session_id=state.session_id,
                    goal_id=state.goal_id,
                    mode=OrchestrationMode.PAUSED,
                    current_step=next_step_index,
                    max_steps=state.max_steps,
                    is_active=False,
                    history=updated_history,
                    pause_reason="Step encountered execution error",
                    started_at=state.started_at,
                    last_advanced_at=now,
                )
                self._states[normalized_sid] = paused_state
                return paused_state

            # Normal autonomous progression
            step_record = AutonomousLoopStep(
                step_index=next_step_index,
                action_type=action_type,
                description=description,
                status=StepStatus.SUCCESS,
                timestamp=now,
                metadata=meta,
            )
            updated_history = [*state.history, step_record]

            # If reaching max_steps after this step, transition to PAUSED
            reached_ceiling = next_step_index >= state.max_steps
            new_mode = OrchestrationMode.PAUSED if reached_ceiling else state.mode
            new_active = (not reached_ceiling) and (state.mode == OrchestrationMode.AUTONOMOUS)
            pause_reason = "Max autonomous steps limit reached" if reached_ceiling else ""

            advanced_state = AutonomousLoopState(
                session_id=state.session_id,
                goal_id=state.goal_id,
                mode=new_mode,
                current_step=next_step_index,
                max_steps=state.max_steps,
                is_active=new_active,
                history=updated_history,
                pause_reason=pause_reason,
                started_at=state.started_at,
                last_advanced_at=now,
            )
            self._states[normalized_sid] = advanced_state
            return advanced_state

    def set_mode(
        self,
        session_id: str,
        mode: OrchestrationMode,
        reason: str = "",
    ) -> AutonomousLoopState:
        """Switch orchestration mode (e.g. from Autonomous to Supervised or Paused)."""
        normalized_sid = session_id.strip()
        now = datetime.now(tz=UTC)

        with self._lock:
            state = self._states.get(normalized_sid)
            if state is None:
                msg = f"No active autonomous loop found for session '{normalized_sid}'"
                raise KeyError(msg)

            new_active = (mode == OrchestrationMode.AUTONOMOUS)
            updated = AutonomousLoopState(
                session_id=state.session_id,
                goal_id=state.goal_id,
                mode=mode,
                current_step=state.current_step,
                max_steps=state.max_steps,
                is_active=new_active,
                history=list(state.history),
                pause_reason=reason if mode == OrchestrationMode.PAUSED else "",
                started_at=state.started_at,
                last_advanced_at=now,
            )
            self._states[normalized_sid] = updated
            logger.info("Session %s orchestration mode changed to %s", normalized_sid, mode.value)
            return updated

    def complete_loop(self, session_id: str, summary: str = "") -> AutonomousLoopState:
        """Mark loop as successfully completed."""
        normalized_sid = session_id.strip()
        now = datetime.now(tz=UTC)

        with self._lock:
            state = self._states.get(normalized_sid)
            if state is None:
                msg = f"No active autonomous loop found for session '{normalized_sid}'"
                raise KeyError(msg)

            completed = AutonomousLoopState(
                session_id=state.session_id,
                goal_id=state.goal_id,
                mode=OrchestrationMode.COMPLETED,
                current_step=state.current_step,
                max_steps=state.max_steps,
                is_active=False,
                history=list(state.history),
                pause_reason=summary or "Goal successfully achieved",
                started_at=state.started_at,
                last_advanced_at=now,
            )
            self._states[normalized_sid] = completed
            return completed

    def get_state(self, session_id: str) -> AutonomousLoopState | None:
        """Get the current loop state for a session."""
        with self._lock:
            return self._states.get(session_id.strip())

    def list_active_loops(self) -> list[AutonomousLoopState]:
        """List all registered autonomous loops."""
        with self._lock:
            return list(self._states.values())

    def reset_loop(self, session_id: str) -> bool:
        """Remove autonomous loop state for a session."""
        normalized_sid = session_id.strip()
        with self._lock:
            self._configs.pop(normalized_sid, None)
            return self._states.pop(normalized_sid, None) is not None

    def clear(self) -> None:
        """Purge all autonomous loops."""
        with self._lock:
            self._states.clear()
            self._configs.clear()
