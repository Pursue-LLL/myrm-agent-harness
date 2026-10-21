"""12-way massive parallel dogfooding runner and HuggingFace trajectory exporter.

Supports:
- Up to 12 parallel worker execution coordination
- Checkpoint resume (--resume) skipping completed jobs
- Tool load balancing distribution strategy
- HuggingFace compatible JSONL trajectory export

[INPUT]
- json
- time
- queue_manager
- types

[OUTPUT]
- MassiveParallelBatchRunner

[POS]
12-way massive parallel dogfooding runner and HuggingFace trajectory exporter.
"""

import json
import time
from .queue_manager import PersistentKanbanQueueManager
from .types import (
    BatchRunnerConfig,
    KanbanJobStatus,
    TrajectoryRecord,
)


class MassiveParallelBatchRunner:
    """Orchestrates 12-way parallel worker dogfooding and trajectory exporting."""

    def __init__(
        self,
        queue_manager: PersistentKanbanQueueManager,
        config: BatchRunnerConfig | None = None,
    ) -> None:
        self.queue_manager = queue_manager
        self.config = config or BatchRunnerConfig()
        self.trajectories: list[TrajectoryRecord] = []
        self.active_workers: dict[str, str] = {}  # worker_id -> job_id

    def get_eligible_jobs(self) -> list[str]:
        """Get jobs eligible for parallel scheduling, honoring resume checkpoint."""
        eligible: list[str] = []
        for job in self.queue_manager.kanban_list():
            if self.config.resume_checkpoint and job.status == KanbanJobStatus.DONE:
                continue
            if job.status == KanbanJobStatus.READY:
                eligible.append(job.job_id)
        return eligible

    def dispatch_parallel_wave(self) -> dict[str, int]:
        """Dispatch up to max_parallel workers concurrently across ready jobs."""
        eligible_job_ids = self.get_eligible_jobs()
        available_slots = self.config.max_parallel - len(self.active_workers)
        dispatched_count = 0

        for i, jid in enumerate(eligible_job_ids[:available_slots]):
            if self.config.distribution_strategy == "tool_load_balanced":
                worker_id = f"worker-slot-lb-{(len(self.active_workers) + i) % self.config.max_parallel}"
            else:
                worker_id = f"worker-slot-rr-{(len(self.active_workers) + i) % self.config.max_parallel}"

            try:
                self.queue_manager.kanban_claim_or_run(jid, assignee=worker_id)
                self.active_workers[worker_id] = jid
                dispatched_count += 1
            except ValueError:
                continue

        running_jobs = self.queue_manager.kanban_list(status=KanbanJobStatus.RUNNING)
        completed_jobs = self.queue_manager.kanban_list(status=KanbanJobStatus.DONE)

        return {
            "dispatched": dispatched_count,
            "running": len(running_jobs),
            "completed": len(completed_jobs),
            "active_workers": len(self.active_workers),
        }

    def record_job_execution(
        self,
        job_id: str,
        success: bool = True,
        output_summary: str = "Batch execution successful",
        tool_calls: list[dict[str, str]] | None = None,
        turns_taken: int = 1,
    ) -> TrajectoryRecord:
        """Record execution outcome, release worker slot, and save trajectory."""
        job = self.queue_manager.kanban_show(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        # Free worker slot
        worker_slot_to_free = None
        for wid, jid in self.active_workers.items():
            if jid == job_id:
                worker_slot_to_free = wid
                break
        if worker_slot_to_free:
            del self.active_workers[worker_slot_to_free]

        calls = list(tool_calls or [])
        stats: dict[str, int] = {}
        for call in calls:
            tool_name = call.get("tool", "unknown_tool")
            stats[tool_name] = stats.get(tool_name, 0) + 1

        if success:
            self.queue_manager.kanban_complete(
                job_id=job_id,
                summary=output_summary,
                metadata={"turns": str(turns_taken), "tool_count": str(len(calls))},
            )
        else:
            self.queue_manager.kanban_block(
                job_id=job_id,
                reason=f"Failed execution: {output_summary}",
            )

        trajectory = TrajectoryRecord(
            task_id=job_id,
            prompt=job.goal,
            tool_calls=calls,
            tool_usage_stats=stats,
            final_response=output_summary,
            turns_taken=turns_taken,
            success=success,
            timestamp=time.time(),
        )
        self.trajectories.append(trajectory)
        return trajectory

    def get_checkpoint_status(self) -> dict[str, int | bool]:
        """Return aggregate statistics and resume checkpoint state."""
        all_jobs = self.queue_manager.kanban_list()
        done_count = sum(1 for j in all_jobs if j.status == KanbanJobStatus.DONE)
        ready_count = sum(1 for j in all_jobs if j.status == KanbanJobStatus.READY)
        running_count = sum(1 for j in all_jobs if j.status == KanbanJobStatus.RUNNING)
        blocked_count = sum(1 for j in all_jobs if j.status == KanbanJobStatus.BLOCKED)

        return {
            "total_jobs": len(all_jobs),
            "done_jobs": done_count,
            "ready_jobs": ready_count,
            "running_jobs": running_count,
            "blocked_jobs": blocked_count,
            "resume_available": done_count > 0 and (ready_count + running_count) > 0,
            "trajectories_collected": len(self.trajectories),
        }

    def export_trajectories_jsonl(self, output_path: str | None = None) -> str:
        """Export collected trajectories into HuggingFace dataset compatible JSONL."""
        lines: list[str] = []
        for t in self.trajectories:
            record_dict = {
                "task_id": t.task_id,
                "prompt": t.prompt,
                "tool_calls": t.tool_calls,
                "tool_usage_stats": t.tool_usage_stats,
                "final_response": t.final_response,
                "turns_taken": t.turns_taken,
                "success": t.success,
                "timestamp": t.timestamp,
            }
            lines.append(json.dumps(record_dict, ensure_ascii=False))

        content = "\n".join(lines)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)

        return content
