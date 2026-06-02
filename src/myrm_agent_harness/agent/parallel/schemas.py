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


class ParallelTaskResults(BaseModel):
    """Structured resume payload for swarm fission and batch delegate."""

    success: bool = Field(default=False)
    status: str = Field(default="failed")
    total_count: int = Field(default=0, ge=0)
    completed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    failure_reasons: list[str] = Field(default_factory=list)
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
                        result=(
                            str(entry.get("result"))
                            if entry.get("result") is not None
                            else None
                        ),
                        error=(
                            str(entry.get("error"))
                            if entry.get("error") is not None
                            else None
                        ),
                        task_id=(
                            str(entry.get("task_id"))
                            if entry.get("task_id") is not None
                            else None
                        ),
                    )
                )
        return cls(
            success=bool(payload.get("success")),
            status=str(payload.get("status") or "failed"),
            total_count=int(payload.get("total_count") or len(items)),
            completed_count=int(payload.get("completed_count") or 0),
            failed_count=int(payload.get("failed_count") or 0),
            failure_reasons=[
                str(reason)
                for reason in (
                    payload.get("failure_reasons")
                    if isinstance(payload.get("failure_reasons"), list)
                    else []
                )
            ],
            all_success=bool(payload.get("all_success")),
            partial_success=bool(payload.get("partial_success")),
            results=items,
        )

    def to_resume_dict(self) -> dict[str, object]:
        return self.model_dump()
