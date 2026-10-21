"""Parallel task execution schemas for batch delegate and swarm fission."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ParallelTaskResultItem(BaseModel):
    task_index: int = Field(default=0, ge=0)
    agent_type: str = Field(default="general")
    success: bool = Field(default=False)
    result: str | None = None
    error: str | None = None
    task_id: str | None = None


class MissingTaskEntry(BaseModel):
    """Structured breakdown entry for a failed or dropped sub-agent task."""

    task_index: int = Field(default=0, ge=0)
    agent_type: str = Field(default="general")
    task_id: str | None = None
    error: str = Field(default="unknown_failure")


class ParallelTaskResults(BaseModel):
    """Structured resume payload for swarm fission and batch delegate."""

    success: bool = Field(default=False)
    status: str = Field(default="failed")
    total_count: int = Field(default=0, ge=0)
    completed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    completeness_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    failure_reasons: list[str] = Field(default_factory=list)
    missing_tasks: list[MissingTaskEntry] = Field(default_factory=list)
    completeness_warning: str | None = None
    gate_passed: bool = Field(default=True)
    all_success: bool = Field(default=False)
    partial_success: bool = Field(default=False)
    results: list[ParallelTaskResultItem] = Field(default_factory=list)

    @classmethod
    def from_batch_dict(cls, payload: dict[str, object]) -> ParallelTaskResults:
        raw_results = payload.get("results")
        items: list[ParallelTaskResultItem] = []
        if isinstance(raw_results, list):
            for index, entry in enumerate(raw_results):
                if not isinstance(entry, dict):
                    continue
                items.append(
                    ParallelTaskResultItem(
                        task_index=int(entry.get("task_index", index)),
                        agent_type=str(entry.get("agent_type") or "general"),
                        success=bool(entry.get("success")),
                        result=(str(entry.get("result")) if entry.get("result") is not None else None),
                        error=(str(entry.get("error")) if entry.get("error") is not None else None),
                        task_id=(str(entry.get("task_id")) if entry.get("task_id") is not None else None),
                    )
                )

        total_count = int(payload.get("total_count") or len(items))
        completed_count = int(payload.get("completed_count") or sum(1 for it in items if it.success))
        failed_count = int(payload.get("failed_count") or (total_count - completed_count))

        # Parse or derive missing_tasks
        raw_missing = payload.get("missing_tasks")
        missing_entries: list[MissingTaskEntry] = []
        if isinstance(raw_missing, list):
            for m in raw_missing:
                if isinstance(m, dict):
                    missing_entries.append(
                        MissingTaskEntry(
                            task_index=int(m.get("task_index", 0)),
                            agent_type=str(m.get("agent_type") or "general"),
                            task_id=(str(m.get("task_id")) if m.get("task_id") is not None else None),
                            error=str(m.get("error") or "unknown_failure"),
                        )
                    )
        elif failed_count > 0:
            for item in items:
                if not item.success:
                    missing_entries.append(
                        MissingTaskEntry(
                            task_index=item.task_index,
                            agent_type=item.agent_type,
                            task_id=item.task_id,
                            error=item.error or "unknown_failure",
                        )
                    )

        # Completeness ratio
        if "completeness_ratio" in payload and isinstance(payload["completeness_ratio"], (int, float)):
            ratio = float(payload["completeness_ratio"])
        else:
            ratio = round(completed_count / total_count, 4) if total_count > 0 else 0.0

        ratio = max(0.0, min(1.0, ratio))

        warning = payload.get("completeness_warning")
        if warning is not None:
            warning = str(warning)

        gate_passed = bool(payload.get("gate_passed", True))

        return cls(
            success=bool(payload.get("success")),
            status=str(payload.get("status") or "failed"),
            total_count=total_count,
            completed_count=completed_count,
            failed_count=failed_count,
            completeness_ratio=ratio,
            failure_reasons=[
                str(reason)
                for reason in (
                    payload.get("failure_reasons") if isinstance(payload.get("failure_reasons"), list) else []
                )
            ],
            missing_tasks=missing_entries,
            completeness_warning=warning,
            gate_passed=gate_passed,
            all_success=bool(payload.get("all_success")),
            partial_success=bool(payload.get("partial_success")),
            results=items,
        )

    def to_resume_dict(self) -> dict[str, object]:
        return self.model_dump()
