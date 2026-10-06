"""Human Rejection Reason Capture & Anti-Regression Guard (Pi Harness v2 Item 30).

Implements semantic human rejection capture and avoidance-directed intent guard:
1. 1-Click Semantic Rejection Reason Capture:
   Captures fine-grained user rejection categories (style regression, missed edge cases, wrong target,
   breaking contract, performance issues) whenever humans revert, undo, or discard changes.
2. Causal Intent Delta Chain Persistence:
   Binds human rollback actions and semantic explanations directly to the artifact revision history,
   transforming a silent undo into explicit learning telemetry.
3. Negative Constraint & Avoidance Injection:
   Automatically generates explicit avoidance directives (Negative Constraints) and formats them into
   structured context blocks (<avoidance_constraints>) to forcefully steer models away from repeating mistakes.
4. Anti-Regression Pre-Flight Validation:
   Checks planned candidate edits or rationale against recent active rejection constraints to preemptively
   abort repetitive failed attempts before polluting files.

[INPUT]
- session_id: str
- artifact_id: str
- category: RejectionCategory
- semantic_reason: str
- user_note: str

[OUTPUT]
- RejectionCategory
- HumanRejectionEvent
- AvoidanceConstraint
- HumanRejectionGuard

[POS]
Harness runtime context layer. Closes the HITL feedback loop and eliminates repeated agent blunders.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import ClassVar


class RejectionCategory(StrEnum):
    """Semantic category of human rejection or rollback."""

    STYLE_REGRESSION = "style_regression"
    MISSED_EDGE_CASE = "missed_edge_case"
    WRONG_TARGET = "wrong_target"
    PERFORMANCE_ISSUE = "performance_issue"
    BREAKING_CONTRACT = "breaking_contract"
    CUSTOM_FEEDBACK = "custom_feedback"


@dataclass(slots=True, frozen=True)
class HumanRejectionEvent:
    """Detailed causal telemetry of why a user rejected or rolled back an artifact."""

    event_id: str
    session_id: str
    target_artifact_id: str
    rejected_version: int
    category: RejectionCategory
    semantic_reason: str
    user_note: str = ""
    rejected_diff_snippet: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass(slots=True, frozen=True)
class AvoidanceConstraint:
    """An active negative constraint distilled from past human rejections."""

    constraint_id: str
    category: RejectionCategory
    directive: str
    target_artifact_id: str
    rejected_version: int


class HumanRejectionGuard:
    """Captures human rejections, distills negative constraints, and enforces anti-regression."""

    _CATEGORY_DIRECTIVES: ClassVar[dict[RejectionCategory, str]] = {
        RejectionCategory.STYLE_REGRESSION: "DO NOT alter or regress existing UI layout, typography, or CSS styling.",
        RejectionCategory.MISSED_EDGE_CASE: "MUST explicitly handle boundary conditions, null/empty states, and timeouts.",
        RejectionCategory.WRONG_TARGET: "DO NOT edit unrelated modules or out-of-scope files; restrict edits strictly to target.",
        RejectionCategory.PERFORMANCE_ISSUE: "DO NOT introduce O(N^2) loops, blocking I/O, or redundant allocations.",
        RejectionCategory.BREAKING_CONTRACT: "DO NOT break existing function signatures, public API contracts, or protocols.",
        RejectionCategory.CUSTOM_FEEDBACK: "Strictly adhere to user-specified correction instructions.",
    }

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._rejections: list[HumanRejectionEvent] = []

    def record_rejection(
        self,
        target_artifact_id: str,
        rejected_version: int,
        category: RejectionCategory,
        semantic_reason: str,
        *,
        user_note: str = "",
        rejected_diff_snippet: str = "",
    ) -> HumanRejectionEvent:
        """Record human rejection event with category and explanation."""
        salt = f"{self.session_id}:{target_artifact_id}:{rejected_version}:{datetime.now().isoformat()}"
        event_id = f"rej-{hashlib.sha256(salt.encode()).hexdigest()[:12]}"

        event = HumanRejectionEvent(
            event_id=event_id,
            session_id=self.session_id,
            target_artifact_id=target_artifact_id,
            rejected_version=rejected_version,
            category=category,
            semantic_reason=semantic_reason.strip(),
            user_note=user_note.strip(),
            rejected_diff_snippet=rejected_diff_snippet.strip(),
        )
        self._rejections.append(event)
        return event

    def get_recent_rejections(self, limit: int = 10) -> list[HumanRejectionEvent]:
        """Return recorded rejection events in chronological order."""
        return list(self._rejections[-limit:])

    def distill_avoidance_constraints(self, limit: int = 5) -> list[AvoidanceConstraint]:
        """Convert recent rejections into actionable avoidance constraints."""
        constraints: list[AvoidanceConstraint] = []
        recent = self.get_recent_rejections(limit)

        for event in recent:
            base_directive = self._CATEGORY_DIRECTIVES.get(event.category, "Avoid previous rejected pattern.")
            detail = f" [Reason: {event.semantic_reason}]" if event.semantic_reason else ""
            note = f" (User note: '{event.user_note}')" if event.user_note else ""
            full_directive = f"{base_directive}{detail}{note}"

            constraints.append(
                AvoidanceConstraint(
                    constraint_id=f"ac-{event.event_id}",
                    category=event.category,
                    directive=full_directive,
                    target_artifact_id=event.target_artifact_id,
                    rejected_version=event.rejected_version,
                )
            )
        return constraints

    def format_avoidance_prompt_block(self, limit: int = 5) -> str:
        """Format active negative constraints into a model-readable context block."""
        constraints = self.distill_avoidance_constraints(limit)
        if not constraints:
            return ""

        lines: list[str] = [
            "<!-- HUMAN REJECTION ANTI-REGRESSION CONSTRAINTS -->",
            "The user previously REJECTED or ROLLED BACK the following attempted solutions in this session.",
            "You MUST strictly adhere to these negative constraints and avoid repeating these mistakes:",
        ]

        for idx, ac in enumerate(constraints, start=1):
            lines.append(
                f"{idx}. Artifact '{ac.target_artifact_id}' (rejected v{ac.rejected_version}, category: {ac.category.value}):\n"
                f"   => {ac.directive}"
            )

        lines.append("<!-- END ANTI-REGRESSION CONSTRAINTS -->")
        return "\n".join(lines)

    def validate_plan_against_constraints(self, proposed_rationale: str) -> tuple[bool, str]:
        """Pre-flight check: evaluate whether proposed plan risks repeating rejected blunders."""
        lower_plan = proposed_rationale.lower()
        for event in self._rejections:
            # Check if plan specifically mentions repeating the rejected rationale verbatim
            if event.user_note and event.user_note.lower() in lower_plan:
                return (
                    False,
                    f"Plan conflicts with prior user feedback on v{event.rejected_version}: '{event.user_note}'",
                )
        return True, ""
