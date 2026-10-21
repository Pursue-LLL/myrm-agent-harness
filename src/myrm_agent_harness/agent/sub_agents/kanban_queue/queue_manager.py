"""Persistent Kanban Job Queue Manager.

Implements 5-state lifecycle, 9 orchestrator/worker tools, 4h heartbeat deadlock reclamation,
Swarm 4-stage shared blackboard, auto-triage specification, fan-out decomposition,
and Git Worktree isolation path allocation.

[INPUT]
- json
- time
- uuid
- types

[OUTPUT]
- PersistentKanbanQueueManager

[POS]
Persistent Kanban Job Queue Manager.
"""

import json
import time
import uuid
from .types import (
    BlackboardEntry,
    JobPriority,
    KanbanComment,
    KanbanJob,
    KanbanJobStatus,
    SwarmTopologyStage,
)


class PersistentKanbanQueueManager:
    """Manager for persistent kanban job queue and swarm coordination."""

    def __init__(self, stale_timeout_seconds: float = 14400.0) -> None:
        self.stale_timeout_seconds = stale_timeout_seconds
        self._jobs: dict[str, KanbanJob] = {}
        self._blackboard: list[BlackboardEntry] = []
        self._auto_decompose_enabled: bool = True

    # --- Tool 1: kanban_create ---
    def kanban_create(
        self,
        title: str,
        goal: str,
        approach: str = "",
        acceptance_criteria: list[str] | None = None,
        priority: JobPriority = JobPriority.NORMAL,
        stage: SwarmTopologyStage = SwarmTopologyStage.PARALLEL_SPECIALIST,
        assignee: str | None = None,
        dependencies: list[str] | None = None,
        skills: list[str] | None = None,
        goal_mode: bool = False,
        goal_max_turns: int = 15,
        job_id: str | None = None,
    ) -> KanbanJob:
        """Create a new job and determine its initial lifecycle status."""
        jid = job_id or f"job-{uuid.uuid4().hex[:8]}"
        deps = list(dependencies or [])
        criteria = list(acceptance_criteria or [])
        skill_list = list(skills or [])

        # If all dependencies are already DONE, start in READY, else TODO
        all_deps_done = all(
            self._jobs.get(dep_id) is not None
            and self._jobs[dep_id].status == KanbanJobStatus.DONE
            for dep_id in deps
        )
        initial_status = KanbanJobStatus.READY if (not deps or all_deps_done) else KanbanJobStatus.TODO

        job = KanbanJob(
            job_id=jid,
            title=title,
            goal=goal,
            approach=approach,
            acceptance_criteria=criteria,
            status=initial_status,
            priority=priority,
            stage=stage,
            assignee=assignee,
            dependencies=deps,
            skills=skill_list,
            worktree_path=f".worktrees/job-{jid}",
            goal_mode=goal_mode,
            goal_max_turns=goal_max_turns,
            created_at=time.time(),
            updated_at=time.time(),
            last_heartbeat_timestamp=time.time(),
        )
        self._jobs[jid] = job
        return job

    # --- Tool 2: kanban_show ---
    def kanban_show(self, job_id: str) -> KanbanJob | None:
        """Retrieve a specific job by ID."""
        return self._jobs.get(job_id)

    # --- Tool 3: kanban_list ---
    def kanban_list(
        self,
        status: KanbanJobStatus | None = None,
        stage: SwarmTopologyStage | None = None,
        assignee: str | None = None,
    ) -> list[KanbanJob]:
        """List and filter jobs."""
        results: list[KanbanJob] = []
        for job in self._jobs.values():
            if status is not None and job.status != status:
                continue
            if stage is not None and job.stage != stage:
                continue
            if assignee is not None and job.assignee != assignee:
                continue
            results.append(job)
        return results

    # --- Tool 4: kanban_claim_or_run ---
    def kanban_claim_or_run(self, job_id: str, assignee: str) -> KanbanJob:
        """Worker claims a READY job and begins RUNNING."""
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        if job.status not in (KanbanJobStatus.READY, KanbanJobStatus.TODO):
            raise ValueError(f"Job {job_id} cannot be claimed in status {job.status.value}")

        job.status = KanbanJobStatus.RUNNING
        job.assignee = assignee
        job.last_heartbeat_timestamp = time.time()
        job.updated_at = time.time()
        return job

    # --- Tool 5: kanban_complete ---
    def kanban_complete(
        self,
        job_id: str,
        summary: str,
        metadata: dict[str, str] | None = None,
    ) -> KanbanJob:
        """Worker completes a job, triggering downstream dependency unblocking."""
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job.status = KanbanJobStatus.DONE
        job.result_summary = summary
        job.result_metadata = dict(metadata or {})
        job.updated_at = time.time()

        # Check and advance dependent jobs from TODO to READY
        for candidate in self._jobs.values():
            if candidate.status == KanbanJobStatus.TODO and job_id in candidate.dependencies:
                all_done = all(
                    self._jobs.get(dep) is not None and self._jobs[dep].status == KanbanJobStatus.DONE
                    for dep in candidate.dependencies
                )
                if all_done:
                    candidate.status = KanbanJobStatus.READY
                    candidate.updated_at = time.time()

        return job

    # --- Tool 6: kanban_block ---
    def kanban_block(self, job_id: str, reason: str) -> KanbanJob:
        """Mark a job as blocked due to missing dependency or human intervention."""
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job.status = KanbanJobStatus.BLOCKED
        job.blocked_reason = reason
        job.updated_at = time.time()
        return job

    # --- Tool 7: kanban_unblock ---
    def kanban_unblock(self, job_id: str) -> KanbanJob:
        """Unblock a job, re-evaluating dependency completion."""
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job.blocked_reason = None
        all_deps_done = all(
            self._jobs.get(dep) is not None and self._jobs[dep].status == KanbanJobStatus.DONE
            for dep in job.dependencies
        )
        job.status = KanbanJobStatus.READY if all_deps_done else KanbanJobStatus.TODO
        job.updated_at = time.time()
        return job

    # --- Tool 8: kanban_heartbeat ---
    def kanban_heartbeat(self, job_id: str) -> bool:
        """Worker records heartbeat timestamp."""
        job = self._jobs.get(job_id)
        if not job:
            return False
        job.last_heartbeat_timestamp = time.time()
        job.updated_at = time.time()
        return True

    # --- Tool 9: kanban_comment & Swarm Blackboard ---
    def kanban_comment(self, job_id: str, author: str, content: str) -> KanbanComment:
        """Add a comment. If formatted as [swarm:blackboard], syncs to Swarm shared blackboard."""
        job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        is_bb = content.startswith("[swarm:blackboard]")
        comment = KanbanComment(author=author, content=content, is_blackboard=is_bb)
        job.comments.append(comment)

        if is_bb:
            raw_json = content[len("[swarm:blackboard]") :].strip()
            try:
                payload = json.loads(raw_json)
                if isinstance(payload, dict):
                    str_payload = {str(k): str(v) for k, v in payload.items()}
                else:
                    str_payload = {"raw": str(payload)}
            except Exception:
                str_payload = {"raw_text": raw_json}

            entry = BlackboardEntry(
                entry_id=f"bb-{uuid.uuid4().hex[:8]}",
                job_id=job_id,
                stage=job.stage,
                author=author,
                payload=str_payload,
            )
            self._blackboard.append(entry)

        return comment

    # --- Tool 10: kanban_link ---
    def kanban_link(self, from_job_id: str, to_job_id: str) -> bool:
        """Add dependency: to_job_id depends on from_job_id (acyclic check)."""
        if from_job_id not in self._jobs or to_job_id not in self._jobs:
            return False
        if from_job_id == to_job_id:
            return False

        # Cycle detection via DFS
        def causes_cycle(curr: str, target: str, visited: set[str]) -> bool:
            if curr == target:
                return True
            visited.add(curr)
            curr_job = self._jobs.get(curr)
            if not curr_job:
                return False
            for dep in curr_job.dependencies:
                if dep not in visited and causes_cycle(dep, target, visited):
                    return True
            return False

        if causes_cycle(from_job_id, to_job_id, set()):
            return False

        target_job = self._jobs[to_job_id]
        if from_job_id not in target_job.dependencies:
            target_job.dependencies.append(from_job_id)
            # Re-evaluate status if target was READY but dependency is not DONE
            from_job = self._jobs[from_job_id]
            if from_job.status != KanbanJobStatus.DONE and target_job.status == KanbanJobStatus.READY:
                target_job.status = KanbanJobStatus.TODO
            target_job.updated_at = time.time()
        return True

    # --- 4-Hour Stale Worker Deadlock Reclamation ---
    def reclaim_stale_workers(self, now: float | None = None) -> list[str]:
        """Scan running workers, reclaiming those with expired heartbeats back to READY."""
        curr_time = now if now is not None else time.time()
        reclaimed: list[str] = []

        for job in self._jobs.values():
            if job.status == KanbanJobStatus.RUNNING:
                elapsed = curr_time - job.last_heartbeat_timestamp
                if elapsed > self.stale_timeout_seconds:
                    job.failure_count += 1
                    if job.failure_count >= 3:
                        job.status = KanbanJobStatus.BLOCKED
                        job.blocked_reason = f"Reclaimed {job.failure_count} times due to stale heartbeat"
                    else:
                        job.status = KanbanJobStatus.READY
                        job.assignee = None
                    job.updated_at = curr_time
                    reclaimed.append(job.job_id)

        return reclaimed

    # --- Blackboard retrieval ---
    def get_blackboard_entries(
        self, stage: SwarmTopologyStage | None = None
    ) -> list[BlackboardEntry]:
        """Fetch shared blackboard entries, optionally filtered by stage."""
        if stage is None:
            return list(self._blackboard)
        return [e for e in self._blackboard if e.stage == stage]

    # --- Auto-Triage & Fan-out Decompose ---
    def kanban_specify(self, raw_prompt: str) -> dict[str, str | list[str]]:
        """Turn rough user inspiration into title, goal, approach, and criteria."""
        trimmed = raw_prompt.strip()
        first_line = trimmed.split("\n")[0] if trimmed else "Ad-hoc Subagent Task"
        title = first_line[:60]
        goal = f"Achieve expected outcome: {trimmed}"
        approach = "Analyze constraints -> Execute in isolated worktree -> Validate against acceptance criteria"
        criteria = [
            "All unit and regression tests pass with exit code 0",
            "No lint warnings or type violations present",
            "Artifacts verified in git worktree without merge conflicts",
        ]
        return {
            "title": title,
            "goal": goal,
            "approach": approach,
            "acceptance_criteria": criteria,
        }

    def kanban_decompose(
        self, parent_job_id: str, subtask_specs: list[dict[str, str]]
    ) -> list[KanbanJob]:
        """Fan-out decompose complex task into subtasks linked to parent."""
        if not self._auto_decompose_enabled:
            raise RuntimeError("Hot circuit breaker active: auto_decompose is disabled")

        parent = self._jobs.get(parent_job_id)
        if not parent:
            raise ValueError(f"Parent job {parent_job_id} not found")

        created: list[KanbanJob] = []
        for i, spec in enumerate(subtask_specs):
            sub_id = f"{parent_job_id}-sub-{i+1}"
            job = self.kanban_create(
                title=spec.get("title", f"Subtask {i+1} for {parent.title}"),
                goal=spec.get("goal", parent.goal),
                approach=spec.get("approach", parent.approach),
                priority=parent.priority,
                stage=SwarmTopologyStage.PARALLEL_SPECIALIST,
                assignee=spec.get("assignee"),
                dependencies=[parent_job_id],
                skills=parent.skills,
                goal_mode=parent.goal_mode,
                job_id=sub_id,
            )
            created.append(job)

        return created

    # --- Hot safety circuit breaker ---
    def set_auto_decompose_enabled(self, enabled: bool) -> None:
        """Hot-toggle auto_decompose safety circuit breaker."""
        self._auto_decompose_enabled = enabled

    def is_auto_decompose_enabled(self) -> bool:
        """Check if auto_decompose circuit breaker is currently enabled."""
        return self._auto_decompose_enabled
