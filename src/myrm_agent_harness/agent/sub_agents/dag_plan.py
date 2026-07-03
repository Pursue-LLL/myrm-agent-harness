"""DAG plan schemas for sub-agent orchestration (not main-agent progress).

[INPUT]
- pydantic::BaseModel, Field (POS: validation)

[OUTPUT]
- PlanStep, Plan: sub-agent DAG plan models with dependency resolution

[POS]
Structured plan DTOs for sub-agent orchestrator (separate from todo_write progress).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    step_id: str
    description: str
    expected_output: str = ""
    status: str = "pending"
    dependencies: list[str] = Field(default_factory=list)
    risk_level: str = "low"
    allow_failure: bool = False
    agent_type: str | None = None


class Plan(BaseModel):
    goal: str
    reasoning: str = ""
    steps: list[PlanStep] = Field(default_factory=list)
    errors_encountered: list[dict[str, str]] = Field(default_factory=list)

    def get_ready_steps(self) -> list[PlanStep]:
        completed = {s.step_id for s in self.steps if s.status in ("completed", "skipped")}
        ready: list[PlanStep] = []
        for step in self.steps:
            if step.status not in ("pending", "in_progress"):
                continue
            if all(dep in completed for dep in step.dependencies):
                ready.append(step)
        return ready

    def mark_step_completed(self, step_id: str) -> None:
        for step in self.steps:
            if step.step_id == step_id:
                step.status = "completed"
                return

    def add_error(self, error_type: str, message: str, *, step_id: str | None = None) -> None:
        self.errors_encountered.append(
            {
                "error_type": error_type,
                "message": message,
                "step_id": step_id or "",
            }
        )
