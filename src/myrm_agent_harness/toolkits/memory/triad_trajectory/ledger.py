"""Ledger implementation maintaining the Triad State Trajectory of a task.

[INPUT]
- Internal: types.py (TriadMilestone, TriadFailedAttempt, TriadUserSteering, TaskTriadBlackboxTrajectory)
- External: re, uuid, datetime

[OUTPUT]
- TriadStateLedger: Authoritative state machine maintaining the three core pillars of task memory.

[POS]
In-memory and persisted state ledger preventing loop traps and steering loss.
"""

import re
import uuid
from datetime import UTC, datetime

from .types import (
    TaskTriadBlackboxTrajectory,
    TrajectoryTaskStatus,
    TriadFailedAttempt,
    TriadMilestone,
    TriadUserSteering,
)


class TriadStateLedger:
    """Authoritative ledger tracking completed milestones, failed attempts, and in-flight user steerings."""

    def __init__(self, task_id: str, session_id: str, initial_goal: str) -> None:
        self.task_id = task_id
        self.session_id = session_id
        self.initial_goal = initial_goal
        self.status = TrajectoryTaskStatus.RUNNING
        self._milestones: list[TriadMilestone] = []
        self._failed_attempts: list[TriadFailedAttempt] = []
        self._user_steerings: list[TriadUserSteering] = []
        self.version = 1
        self.created_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)

    def record_milestone(
        self,
        step_index: int,
        title: str,
        verified_output_summary: str,
        description: str = "",
        artifacts: list[str] | None = None,
    ) -> TriadMilestone:
        """Record a verified completed milestone to prevent duplicate effort."""
        milestone = TriadMilestone(
            milestone_id=f"ms_{uuid.uuid4().hex[:8]}",
            step_index=step_index,
            title=title.strip(),
            description=description.strip(),
            verified_output_summary=verified_output_summary.strip(),
            artifacts_produced=artifacts or [],
            timestamp=datetime.now(UTC),
        )
        self._milestones.append(milestone)
        self._bump_version()
        return milestone

    def record_failed_attempt(
        self,
        step_index: int,
        action_attempted: str,
        error_type: str,
        error_summary: str,
        dead_end_pattern: str,
        prohibited_rule: str,
        lessons_learned: str = "",
    ) -> TriadFailedAttempt:
        """Record a failed action and establish an explicit anti-loop prohibition rule."""
        attempt = TriadFailedAttempt(
            attempt_id=f"fa_{uuid.uuid4().hex[:8]}",
            step_index=step_index,
            action_attempted=action_attempted.strip(),
            error_type=error_type.strip(),
            error_summary=error_summary.strip(),
            dead_end_pattern=dead_end_pattern.strip(),
            prohibited_rule=prohibited_rule.strip(),
            lessons_learned=lessons_learned.strip(),
            timestamp=datetime.now(UTC),
        )
        self._failed_attempts.append(attempt)
        self._bump_version()
        return attempt

    def record_user_steering(
        self,
        turn_index: int,
        instruction_raw: str,
        distilled_constraint: str,
        scope: str = "global",
    ) -> TriadUserSteering:
        """Capture dynamic steering instruction introduced mid-flight by the user."""
        steering = TriadUserSteering(
            steering_id=f"st_{uuid.uuid4().hex[:8]}",
            turn_index=turn_index,
            instruction_raw=instruction_raw.strip(),
            distilled_constraint=distilled_constraint.strip(),
            scope=scope.strip(),
            is_active=True,
            timestamp=datetime.now(UTC),
        )
        self._user_steerings.append(steering)
        self._bump_version()
        return steering

    def deactivate_steering(self, steering_id: str) -> bool:
        """Mark an in-flight steering as deactivated if superseded by a newer command."""
        for steering in self._user_steerings:
            if steering.steering_id == steering_id and steering.is_active:
                steering.is_active = False
                self._bump_version()
                return True
        return False

    def check_action_prohibited(self, action_text: str) -> tuple[bool, TriadFailedAttempt | None]:
        """Verify whether an intended action triggers any recorded dead-end failure pattern."""
        if not action_text:
            return False, None

        normalized_action = action_text.strip().lower()

        for attempt in reversed(self._failed_attempts):
            pattern = attempt.dead_end_pattern.strip().lower()
            if not pattern:
                continue

            # Check literal substring match
            if pattern in normalized_action:
                return True, attempt

            # Check regular expression match if valid regex
            try:
                if re.search(pattern, normalized_action, re.IGNORECASE):
                    return True, attempt
            except re.error:
                # If regex compilation fails, fallback to tokenized inclusion
                pass

            # Check exact command match
            if attempt.action_attempted.strip().lower() in normalized_action:
                return True, attempt

        return False, None

    def get_trajectory(self) -> TaskTriadBlackboxTrajectory:
        """Retrieve full snapshot of the triad trajectory."""
        return TaskTriadBlackboxTrajectory(
            task_id=self.task_id,
            session_id=self.session_id,
            initial_goal=self.initial_goal,
            status=self.status,
            milestones=list(self._milestones),
            failed_attempts=list(self._failed_attempts),
            user_steerings=list(self._user_steerings),
            version=self.version,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    def set_status(self, status: TrajectoryTaskStatus) -> None:
        """Update overall trajectory lifecycle status."""
        self.status = status
        self._bump_version()

    @property
    def milestones(self) -> list[TriadMilestone]:
        return list(self._milestones)

    @property
    def failed_attempts(self) -> list[TriadFailedAttempt]:
        return list(self._failed_attempts)

    @property
    def active_steerings(self) -> list[TriadUserSteering]:
        return [s for s in self._user_steerings if s.is_active]

    def _bump_version(self) -> None:
        self.version += 1
        self.updated_at = datetime.now(UTC)
