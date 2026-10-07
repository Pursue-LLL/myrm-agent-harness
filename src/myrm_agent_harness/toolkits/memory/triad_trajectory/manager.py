"""Manager orchestrating Task Triad Trajectory persistence, replay, and handoff.

[INPUT]
- Internal: ledger.py (TriadStateLedger), injector.py (AntiLoopPromptInjector), types.py
- External: json, pathlib, datetime

[OUTPUT]
- TaskTriadTrajectoryManager: Central coordinator for long-horizon task triad state blackbox.

[POS]
Harness framework layer providing volume persistence and crash recovery for agent tasks.
"""

import json
from pathlib import Path
from typing import Any

from .injector import AntiLoopPromptInjector
from .ledger import TriadStateLedger
from .types import (
    AntiLoopPromptSnapshot,
    TaskTriadBlackboxTrajectory,
    TrajectoryTaskStatus,
    TriadFailedAttempt,
)


class TaskTriadTrajectoryManager:
    """Manages long-horizon task triad state ledgers, persistence, and post-mortem handoffs."""

    def __init__(self, persistence_dir: Path | str | None = None) -> None:
        self.persistence_dir = Path(persistence_dir) if persistence_dir else None
        if self.persistence_dir:
            self.persistence_dir.mkdir(parents=True, exist_ok=True)
        self._ledgers: dict[str, TriadStateLedger] = {}

    def get_or_create_ledger(
        self,
        task_id: str,
        session_id: str,
        initial_goal: str,
    ) -> TriadStateLedger:
        """Get active ledger or instantiate new tracking ledger for the task."""
        if task_id in self._ledgers:
            return self._ledgers[task_id]

        # Check if saved file exists on disk
        if self.persistence_dir:
            file_path = self.persistence_dir / f"task_blackbox_{task_id}.json"
            if file_path.exists():
                try:
                    data = json.loads(file_path.read_text(encoding="utf-8"))
                    trajectory = TaskTriadBlackboxTrajectory.model_validate(data)
                    return self.import_trajectory(trajectory)
                except Exception:
                    pass

        ledger = TriadStateLedger(task_id=task_id, session_id=session_id, initial_goal=initial_goal)
        self._ledgers[task_id] = ledger
        return ledger

    def get_ledger(self, task_id: str) -> TriadStateLedger | None:
        """Retrieve existing ledger by task ID if available."""
        return self._ledgers.get(task_id)

    def generate_anti_loop_snapshot(
        self,
        task_id: str,
        step_hint: str = "",
        max_tokens: int = 150,
    ) -> AntiLoopPromptSnapshot | None:
        """Generate high-density anti-loop pre-prompt snapshot for the given task."""
        ledger = self.get_ledger(task_id)
        if not ledger:
            return None
        return AntiLoopPromptInjector.build_snapshot(ledger, step_hint=step_hint, max_tokens=max_tokens)

    def check_action_prohibited(
        self,
        task_id: str,
        action_text: str,
    ) -> tuple[bool, TriadFailedAttempt | None]:
        """Check if action triggers known dead-end path in the task ledger."""
        ledger = self.get_ledger(task_id)
        if not ledger:
            return False, None
        return ledger.check_action_prohibited(action_text)

    def export_trajectory(
        self,
        task_id: str,
        target_path: Path | str | None = None,
    ) -> TaskTriadBlackboxTrajectory:
        """Export full trajectory and persist to storage volume."""
        ledger = self._ledgers.get(task_id)
        if not ledger:
            msg = f"Task {task_id} has no registered triad ledger"
            raise KeyError(msg)

        trajectory = ledger.get_trajectory()

        path_to_write = Path(target_path) if target_path else None
        if not path_to_write and self.persistence_dir:
            path_to_write = self.persistence_dir / f"task_blackbox_{task_id}.json"

        if path_to_write:
            path_to_write.parent.mkdir(parents=True, exist_ok=True)
            path_to_write.write_text(trajectory.model_dump_json(indent=2), encoding="utf-8")

        return trajectory

    def import_trajectory(
        self,
        trajectory: TaskTriadBlackboxTrajectory | dict[str, Any],
    ) -> TriadStateLedger:
        """Restore or handoff full triad trajectory from snapshot payload."""
        if isinstance(trajectory, dict):
            traj_obj = TaskTriadBlackboxTrajectory.model_validate(trajectory)
        else:
            traj_obj = trajectory

        ledger = TriadStateLedger(
            task_id=traj_obj.task_id,
            session_id=traj_obj.session_id,
            initial_goal=traj_obj.initial_goal,
        )
        ledger.status = traj_obj.status
        ledger.version = traj_obj.version
        ledger.created_at = traj_obj.created_at
        ledger.updated_at = traj_obj.updated_at

        for ms in traj_obj.milestones:
            ledger._milestones.append(ms)

        for fa in traj_obj.failed_attempts:
            ledger._failed_attempts.append(fa)

        for us in traj_obj.user_steerings:
            ledger._user_steerings.append(us)

        self._ledgers[traj_obj.task_id] = ledger
        return ledger

    def mark_task_status(self, task_id: str, status: TrajectoryTaskStatus) -> None:
        """Update lifecycle status of task trajectory."""
        ledger = self.get_ledger(task_id)
        if ledger:
            ledger.set_status(status)
            if self.persistence_dir:
                self.export_trajectory(task_id)
