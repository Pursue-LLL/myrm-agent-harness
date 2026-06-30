"""Planner Schema Definitions

Defines structured planning schemas for task planning sub-agent.
Supports 3-Strike Protocol for error recovery and Scratchpad pattern for context management.

[INPUT]
- (none)

[OUTPUT]
- ErrorRecord: Error record - A key signal of TRUE agentic behavior
- PlanStep: Plan step
- Plan: Structured plan (Scratchpad pattern)
- PlannerInput: Planner tool input

[POS]
Planner Schema Definitions
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ErrorRecord(BaseModel):
    """Error record - A key signal of TRUE agentic behavior

    Reference: Manus founder Pete: "Error recovery is one of the clearest
    signals of TRUE agentic behavior."

    Design principles:
    - Don't hide errors, record them explicitly
    - Track solutions and success rates
    - Let agents learn from failures
    - Support 3-Strike Protocol (avoid infinite retries)
    """

    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(), description="Error occurrence time (ISO 8601 format)"
    )
    step_id: str | None = Field(default=None, description="Step ID where error occurred")
    error_type: str = Field(description="Error type (e.g., FileNotFoundError, APIError)")
    description: str = Field(description="Error description (agent's observation)")
    context: str | None = Field(default=None, description="Error context (e.g., tool call parameters)")
    resolution: str | None = Field(default=None, description="Solution (how to bypass or fix)")
    resolution_success: bool | None = Field(default=None, description="Whether the solution was successful")
    retry_count: int = Field(default=0, description="Number of retries")
    impact: Literal["low", "medium", "high", "critical"] = Field(default="medium", description="Impact level")

    # 3-Strike Protocol support
    attempt_history: list[str] = Field(
        default_factory=list, description="Attempt history to avoid repeating the same failed approach"
    )
    escalated_to_user: bool = Field(
        default=False, description="Whether escalated to user (auto-escalate after 3 failures)"
    )


class PlanStep(BaseModel):
    """Plan step"""

    step_id: str = Field(description="Step ID, e.g., step_1, step_2")
    description: str = Field(description="Step description, concise and clear")
    expected_output: str = Field(
        description="Specific, verifiable expected output. Must describe observable results "
        "(avoid vague terms like 'works correctly' or 'completed successfully')"
    )
    status: Literal["pending", "in_progress", "completed", "skipped", "failed"] = Field(
        default="pending", description="Step status"
    )
    dependencies: list[str] = Field(default_factory=list, description="List of step IDs that must be completed first")
    allow_failure: bool = Field(
        default=False,
        description="Non-critical step: when True, failure sets status to 'skipped' "
        "instead of 'failed', allowing downstream steps to proceed.",
    )
    risk_level: Literal["low", "medium", "high"] | None = Field(
        default=None,
        description="Self-assessed risk. high=hard to undo/touches external systems/destructive; "
        "medium=non-trivial but reversible; low=safe local work. Omit if uncertain.",
    )


class DecisionRecord(BaseModel):
    """Architectural decision record

    Tracks key decisions made during the plan execution.
    """

    id: str | None = Field(default=None, description="Unique identifier for the decision (e.g., 'DEC-001')")
    topic: str | None = Field(default=None, description="The topic or component this decision applies to")
    decision: str = Field(description="The actual decision made")
    rationale: str = Field(description="The reasoning behind the decision")
    status: Literal["active", "superseded", "deprecated"] = Field(
        default="active", description="Status of the decision"
    )
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat(), description="When the decision was made")


class Plan(BaseModel):
    """Structured plan (Scratchpad pattern)

    Planner sub-agent output format ensuring structured, trackable plans.
    Implements the Scratchpad pattern from Anthropic Context Engineering:
    - Structured note file recording task progress
    - Key findings and pending issues
    - Persistent across calls, loaded on demand
    """

    goal: str = Field(description="Final goal, one-sentence description")
    reasoning: str = Field(description="Planning rationale, why this approach")
    steps: list[PlanStep] = Field(description="Execution steps in order")
    current_step_id: str | None = Field(default=None, description="Current step ID to execute")
    notes: str | None = Field(default=None, description="Additional notes from planner, e.g., risk warnings")
    # Scratchpad extension fields
    key_findings: list[str] = Field(default_factory=list, description="Key findings discovered during execution")
    decisions: list[DecisionRecord] = Field(
        default_factory=list, description="Architectural decisions made during execution"
    )
    pending_issues: list[str] = Field(default_factory=list, description="Pending issues to be resolved later")

    # Error tracking (Manus 3.0 core feature)
    errors_encountered: list[ErrorRecord] = Field(
        default_factory=list, description="Error log - learn from failures, avoid repeating mistakes"
    )

    def add_error(
        self,
        error_type: str,
        description: str,
        step_id: str | None = None,
        context: str | None = None,
        impact: Literal["low", "medium", "high", "critical"] = "medium",
    ) -> None:
        """Record an error

        Args:
            error_type: Error type (e.g., FileNotFoundError)
            description: Error description
            step_id: Step ID where error occurred (defaults to current step)
            context: Error context
            impact: Impact level
        """
        error = ErrorRecord(
            step_id=step_id or self.current_step_id,
            error_type=error_type,
            description=description,
            context=context,
            impact=impact,
        )
        self.errors_encountered.append(error)

    def get_recent_errors(self, limit: int = 5) -> list[ErrorRecord]:
        """Get recent errors

        Args:
            limit: Return last N errors

        Returns:
            Recent errors (reverse chronological order)
        """
        return sorted(self.errors_encountered, key=lambda e: e.timestamp, reverse=True)[:limit]

    def should_escalate_error(self, error: ErrorRecord) -> bool:
        """Check if error should be escalated to user (3-Strike Protocol)

        Escalation conditions:
        - retry_count >= 3
        - Not yet escalated to user

        Args:
            error: Error record

        Returns:
            True if should escalate
        """
        return error.retry_count >= 3 and not error.escalated_to_user

    def get_unique_attempt_methods(self, error: ErrorRecord) -> set[str]:
        """Get unique attempted methods

        Used to check if repeating the same failed approach.

        Args:
            error: Error record

        Returns:
            Set of attempted methods
        """
        return set(error.attempt_history)

    def add_error_attempt(
        self,
        step_id: str,
        error_type: str,
        description: str,
        attempted_method: str,
        context: str | None = None,
        impact: Literal["low", "medium", "high", "critical"] = "medium",
    ) -> ErrorRecord:
        """Record error attempt (3-Strike Protocol)

        If retry of same error, increment retry_count and add to attempt_history.
        If new error, create new ErrorRecord.

        Args:
            step_id: Step ID
            error_type: Error type
            description: Error description
            attempted_method: Method attempted
            context: Error context
            impact: Impact level

        Returns:
            Error record object
        """
        # Find existing error with same step_id and error_type
        existing_error = None
        for err in self.errors_encountered:
            if err.step_id == step_id and err.error_type == error_type:
                existing_error = err
                break

        if existing_error:
            # Update existing error
            existing_error.retry_count += 1
            existing_error.attempt_history.append(attempted_method)
            existing_error.description = description
            existing_error.timestamp = datetime.now().isoformat()

            # Check if escalation needed
            if self.should_escalate_error(existing_error):
                existing_error.escalated_to_user = True

            return existing_error
        else:
            # Create new error record
            new_error = ErrorRecord(
                step_id=step_id,
                error_type=error_type,
                description=description,
                context=context,
                impact=impact,
                retry_count=1,
                attempt_history=[attempted_method],
            )
            self.errors_encountered.append(new_error)
            return new_error

    def get_current_step(self) -> PlanStep | None:
        """Get current step"""
        if not self.current_step_id:
            return None
        for step in self.steps:
            if step.step_id == self.current_step_id:
                return step
        return None

    def get_ready_steps(self) -> list[PlanStep]:
        """Get all pending steps whose dependencies are resolved.

        A dependency is resolved when its status is 'completed' or 'skipped'
        (non-critical steps that failed are marked 'skipped').
        """
        ready_steps = []
        _resolved = ("completed", "skipped")
        for step in self.steps:
            if step.status == "pending":
                deps_done = all(self._get_step_status(dep_id) in _resolved for dep_id in step.dependencies)
                if deps_done:
                    ready_steps.append(step)
        return ready_steps

    def get_next_step(self) -> PlanStep | None:
        """Get next pending step whose dependencies are resolved"""
        _resolved = ("completed", "skipped")
        for step in self.steps:
            if step.status == "pending":
                deps_done = all(self._get_step_status(dep_id) in _resolved for dep_id in step.dependencies)
                if deps_done:
                    return step
        return None

    def _get_step_status(self, step_id: str) -> str | None:
        """Get step status"""
        for step in self.steps:
            if step.step_id == step_id:
                return step.status
        return None

    def mark_step_completed(self, step_id: str) -> bool:
        """Mark step as completed"""
        for step in self.steps:
            if step.step_id == step_id:
                step.status = "completed"
                # Auto-update current_step_id to next step
                next_step = self.get_next_step()
                self.current_step_id = next_step.step_id if next_step else None
                return True
        return False

    def add_step(self, step: PlanStep) -> None:
        """Add a new step to the plan dynamically"""
        # Ensure step_id is unique
        existing_ids = {s.step_id for s in self.steps}
        base_id = step.step_id
        counter = 1
        while step.step_id in existing_ids:
            step.step_id = f"{base_id}_{counter}"
            counter += 1
        self.steps.append(step)

    def to_summary(self) -> str:
        """Generate compact summary (<100 tokens)

        For middleware auto-injection, providing lightweight task awareness.

        Returns:
            Ultra-short summary: "Phase X/Y - description (N remaining)"
        """
        current_step = self.get_current_step()
        total = len(self.steps)
        completed = sum(1 for s in self.steps if s.status == "completed")

        return (
            f"Phase {completed + 1}/{total} - "
            f"{current_step.description if current_step else 'Planning'} "
            f"({total - completed} remaining)"
        )

    def to_line_format(self) -> str:
        """Convert plan to Line-based format for grep/head/sed operations

        Design principle (from Manus field survival rules):
        - Prefer plain text/code over Markdown
        - Each line contains complete semantics, independently parseable
        - Allow model to efficiently use grep, head, or sed for line-by-line slicing
        """
        lines = [
            "PLAN",
            f"GOAL: {self.goal}",
            f"REASONING: {self.reasoning}",
            "---",
        ]

        status_markers = {
            "pending": "[ ]",
            "in_progress": "[>]",
            "completed": "[x]",
            "skipped": "[-]",
            "failed": "[!]",
        }

        for step in self.steps:
            marker = status_markers.get(step.status, "[ ]")
            current = " <CURRENT>" if step.step_id == self.current_step_id else ""
            deps = f" (deps: {','.join(step.dependencies)})" if step.dependencies else ""
            risk_tag = f" [RISK:{step.risk_level.upper()}]" if step.risk_level and step.risk_level != "low" else ""
            lines.append(f"STEP {step.step_id} {marker}: {step.description}{current}{deps}{risk_tag}")
            lines.append(f" OUTPUT: {step.expected_output}")

        lines.append("---")

        # Add error records (show last 5 only)
        if self.errors_encountered:
            lines.append("ERRORS:")
            for err in self.get_recent_errors(limit=5):
                resolution_str = f" → {err.resolution}" if err.resolution else ""
                lines.append(f" [{err.timestamp[:19]}] {err.error_type}: {err.description}{resolution_str}")
            lines.append("---")

        if self.key_findings:
            for finding in self.key_findings:
                lines.append(f"FINDING: {finding}")

        if self.decisions:
            lines.append("DECISIONS:")
            for dec in self.decisions:
                status_str = f" [{dec.status.upper()}]" if dec.status != "active" else ""
                lines.append(f" {dec.id}{status_str}: {dec.topic} -> {dec.decision}")
                lines.append(f" Rationale: {dec.rationale}")
            lines.append("---")

        if self.pending_issues:
            for issue in self.pending_issues:
                lines.append(f"ISSUE: {issue}")

        if self.notes:
            lines.append(f"NOTE: {self.notes}")

        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Convert plan to comprehensive Markdown view

        Design principle:
        - Single file contains all user-needed information
        - Avoid information scatter, reduce cognitive load
        - Maintain clear section structure

        Includes:
        1. Goal and progress
        2. Phase list
        3. Key findings (if any)
        4. Pending issues (if any)
        5. Error records (if any)
        6. Decision notes
        """
        completed = sum(1 for s in self.steps if s.status == "completed")
        total = len(self.steps)
        progress_pct = int(completed / total * 100) if total > 0 else 0

        lines = [
            f"# Task Plan: {self.goal[:60]}...",
            "",
            "##  Goal",
            self.goal,
            "",
            "##  Progress",
            f"**Current Phase:** {completed + 1}/{total}",
            f"**Completed:** {completed}/{total} steps ({progress_pct}%)",
            "",
            "##  Phases",
            "",
        ]

        status_emoji = {
            "pending": "⬜",
            "in_progress": "",
            "completed": "",
            "skipped": "",
            "failed": "❌",
        }

        status_text = {
            "pending": "pending",
            "in_progress": "in_progress",
            "completed": "complete",
            "skipped": "skipped",
            "failed": "failed",
        }

        for i, step in enumerate(self.steps, 1):
            emoji = status_emoji.get(step.status, "⬜")
            current_marker = "  **CURRENT**" if step.step_id == self.current_step_id else ""
            deps_str = f" (depends on: {', '.join(step.dependencies)})" if step.dependencies else ""

            lines.append(f"### Phase {i}: {step.description}")
            lines.append(f"- {emoji} **Status:** {status_text.get(step.status, 'pending')}{current_marker}")
            lines.append(f"- **Expected Output:** {step.expected_output}")
            if step.risk_level and step.risk_level != "low":
                lines.append(f"- **Risk:** {step.risk_level}")
            if deps_str:
                lines.append(f"- **Dependencies:** {deps_str}")
            lines.append("")

        # Key findings
        if self.key_findings:
            lines.append("##  Key Findings")
            lines.append("")
            for idx, finding in enumerate(self.key_findings, 1):
                lines.append(f"{idx}. {finding}")
            lines.append("")

        # Decisions
        if self.decisions:
            lines.append("##  Architectural Decisions")
            lines.append("")
            for dec in self.decisions:
                status_icon = ""
                lines.append(f"### {status_icon} {dec.id}: {dec.topic}")
                lines.append(f"- **Decision:** {dec.decision}")
                lines.append(f"- **Rationale:** {dec.rationale}")
                lines.append(f"- **Status:** {dec.status}")
                lines.append("")

        # Pending issues
        if self.pending_issues:
            lines.append("##  Pending Issues")
            lines.append("")
            for issue in self.pending_issues:
                lines.append(f"- [ ] {issue}")
            lines.append("")

        # Error records
        if self.errors_encountered:
            lines.append("##  Errors Encountered")
            lines.append("")
            lines.append("| Error | Attempt | Resolution | Status |")
            lines.append("|-------|---------|------------|--------|")

            for err in self.get_recent_errors(limit=10):
                resolution_str = err.resolution or "Pending"
                status_icon = ""
                lines.append(f"| {err.error_type} | {err.retry_count + 1} | {resolution_str} | {status_icon} |")
            lines.append("")

        # Decision notes
        if self.notes:
            lines.append("##  Notes & Decisions")
            lines.append("")
            lines.append(self.notes)
            lines.append("")

        return "\n".join(lines)


class PlannerInput(BaseModel):
    """Planner tool input"""

    action: Literal["create", "update", "get"] = Field(
        description="Action type: create=new plan, update=modify plan, get=retrieve plan"
    )
    task_description: str | None = Field(default=None, description="Task description (required for create)")
    completed_step_id: str | None = Field(default=None, description="Completed step ID (for update)")
    feedback: str | None = Field(default=None, description="Execution feedback (for update), e.g., issues encountered")
