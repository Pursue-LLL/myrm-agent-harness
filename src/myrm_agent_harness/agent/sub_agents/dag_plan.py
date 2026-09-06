"""DAG plan schemas for sub-agent orchestration (not main-agent progress).

[INPUT]
- pydantic::BaseModel, Field (POS: validation)

[OUTPUT]
- PlanStep, Plan: sub-agent DAG plan models with dependency resolution
- GraphPatch, GraphPatchResult: declarative graph mutation DTOs for mid-run graph compiler gate

[POS]
Structured plan DTOs for sub-agent orchestrator with OCC and deterministic Kahn DAG patch compiler gate.
"""

from __future__ import annotations

from collections import deque

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
    readonly: bool = False
    requires_verification: bool = False
    verifier_prompt: str | None = None


class GraphPatch(BaseModel):
    base_revision: int
    add_steps: list[PlanStep] = Field(default_factory=list)
    remove_steps: list[str] = Field(default_factory=list)
    modify_dependencies: dict[str, list[str]] = Field(default_factory=dict)


class GraphPatchResult(BaseModel):
    success: bool
    new_revision: int
    error: str | None = None
    affected_steps: list[str] = Field(default_factory=list)
    topology_preserving: bool = False


class Plan(BaseModel):
    goal: str
    reasoning: str = ""
    steps: list[PlanStep] = Field(default_factory=list)
    errors_encountered: list[dict[str, str]] = Field(default_factory=list)
    revision: int = 1

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

    def apply_graph_patch(self, patch: GraphPatch) -> GraphPatchResult:
        """Atomically validate and apply a GraphPatch to the active plan.

        Enforces:
        1. OCC: patch.base_revision == self.revision
        2. Immutability: completed, in_progress, and skipped steps cannot be removed or have dependencies altered
        3. Dependency completeness: all dependencies must exist in remaining + added steps
        4. Kahn's algorithm: topological sorting verification ensuring no cycles
        5. Topology-preserving hook detection: frontier-only additions bypass full reordering
        """
        if patch.base_revision != self.revision:
            return GraphPatchResult(
                success=False,
                new_revision=self.revision,
                error=f"Revision conflict: base_revision {patch.base_revision} != current revision {self.revision}",
            )

        immutable_statuses = {"completed", "in_progress", "skipped"}
        existing_by_id = {s.step_id: s for s in self.steps}

        for s_id in patch.remove_steps:
            target = existing_by_id.get(s_id)
            if target is not None and target.status in immutable_statuses:
                return GraphPatchResult(
                    success=False,
                    new_revision=self.revision,
                    error=f"Cannot remove step '{s_id}' with immutable status '{target.status}'",
                )

        for s_id in patch.modify_dependencies:
            target = existing_by_id.get(s_id)
            if target is not None and target.status in immutable_statuses:
                return GraphPatchResult(
                    success=False,
                    new_revision=self.revision,
                    error=f"Cannot modify dependencies of step '{s_id}' with immutable status '{target.status}'",
                )

        candidate_steps: dict[str, PlanStep] = {
            s.step_id: s.model_copy(deep=True) for s in self.steps
        }

        for s_id in patch.remove_steps:
            candidate_steps.pop(s_id, None)

        for new_step in patch.add_steps:
            if new_step.step_id in candidate_steps:
                return GraphPatchResult(
                    success=False,
                    new_revision=self.revision,
                    error=f"Cannot add step '{new_step.step_id}': ID already exists in candidate plan",
                )
            candidate_steps[new_step.step_id] = new_step.model_copy(deep=True)

        for s_id, new_deps in patch.modify_dependencies.items():
            if s_id not in candidate_steps:
                return GraphPatchResult(
                    success=False,
                    new_revision=self.revision,
                    error=f"Cannot modify dependencies for non-existent step '{s_id}'",
                )
            candidate_steps[s_id].dependencies = list(new_deps)

        all_candidate_ids = set(candidate_steps.keys())
        for step in candidate_steps.values():
            for dep in step.dependencies:
                if dep not in all_candidate_ids:
                    return GraphPatchResult(
                        success=False,
                        new_revision=self.revision,
                        error=f"Dangling dependency: step '{step.step_id}' depends on non-existent step '{dep}'",
                    )

        in_degree: dict[str, int] = {s_id: 0 for s_id in all_candidate_ids}
        adj: dict[str, list[str]] = {s_id: [] for s_id in all_candidate_ids}
        for s_id, step in candidate_steps.items():
            for dep in step.dependencies:
                adj[dep].append(s_id)
                in_degree[s_id] += 1

        queue: deque[str] = deque([s_id for s_id, deg in in_degree.items() if deg == 0])
        visited_count = 0
        while queue:
            curr = queue.popleft()
            visited_count += 1
            for nxt in adj[curr]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        if visited_count != len(all_candidate_ids):
            return GraphPatchResult(
                success=False,
                new_revision=self.revision,
                error="Cycle detected in DAG topology after patch",
            )

        is_topology_preserving = (
            len(patch.remove_steps) == 0
            and len(patch.modify_dependencies) == 0
            and all(
                all(dep in existing_by_id for dep in s.dependencies)
                for s in patch.add_steps
            )
        )

        self.steps = list(candidate_steps.values())
        self.revision += 1
        affected = (
            [s.step_id for s in patch.add_steps]
            + patch.remove_steps
            + list(patch.modify_dependencies.keys())
        )

        return GraphPatchResult(
            success=True,
            new_revision=self.revision,
            affected_steps=affected,
            topology_preserving=is_topology_preserving,
        )
