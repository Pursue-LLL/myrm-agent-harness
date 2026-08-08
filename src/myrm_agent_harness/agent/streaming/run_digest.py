"""Run digest DTO and reducer for live agent run observation.

Pure data shaping from progress-step dicts (no I/O, no business coupling).

[INPUT]
- progress step dicts from stream collector (tool_name, step_key, status, …)

[OUTPUT]
- RunDigest: serializable snapshot for UI Run Observer / Advisor Tier-0

[POS]
Harness L2 streaming — reusable by any integrator observing tool-step events.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class RunDigestPhase(StrEnum):
    """High-level run phase for UI chips."""

    IDLE = "idle"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RunDigestStep:
    """One summarized tool step for the run digest."""

    index: int
    tool_name: str
    step_key: str
    status: str | None = None


@dataclass(frozen=True, slots=True)
class RunDigest:
    """Live or terminal snapshot of a chat's agent run."""

    chat_id: str
    phase: RunDigestPhase
    step_count: int
    current_tool: str | None
    current_step_key: str | None
    pending_approval_count: int
    elapsed_seconds: int
    headline: str
    recent_steps: tuple[RunDigestStep, ...] = field(default=())
    updated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "chat_id": self.chat_id,
            "phase": self.phase.value,
            "step_count": self.step_count,
            "current_tool": self.current_tool,
            "current_step_key": self.current_step_key,
            "pending_approval_count": self.pending_approval_count,
            "elapsed_seconds": self.elapsed_seconds,
            "headline": self.headline,
            "recent_steps": [
                {
                    "index": step.index,
                    "tool_name": step.tool_name,
                    "step_key": step.step_key,
                    "status": step.status,
                }
                for step in self.recent_steps
            ],
            "updated_at": self.updated_at,
        }


def _tool_label(step: Mapping[str, object]) -> str:
    tool_name = step.get("tool_name")
    if isinstance(tool_name, str) and tool_name.strip():
        return tool_name.strip()
    step_key = step.get("step_key")
    if isinstance(step_key, str) and step_key.strip():
        return step_key.strip()
    return "tool"


def _step_status(step: Mapping[str, object]) -> str | None:
    status = step.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return None


def build_run_digest(
    *,
    chat_id: str,
    progress_steps: list[dict[str, object]],
    phase: RunDigestPhase,
    pending_approval_count: int = 0,
    elapsed_seconds: int = 0,
    max_recent: int = 5,
) -> RunDigest:
    """Build a RunDigest from collector progress steps."""
    step_count = len(progress_steps)
    current_tool: str | None = None
    current_step_key: str | None = None
    if progress_steps:
        last = progress_steps[-1]
        current_tool = _tool_label(last)
        raw_key = last.get("step_key")
        if isinstance(raw_key, str) and raw_key.strip():
            current_step_key = raw_key.strip()

    recent_slice = progress_steps[-max_recent:] if progress_steps else []
    recent_steps = tuple(
        RunDigestStep(
            index=step_count - len(recent_slice) + offset + 1,
            tool_name=_tool_label(step),
            step_key=str(step.get("step_key") or ""),
            status=_step_status(step),
        )
        for offset, step in enumerate(recent_slice)
    )

    if phase == RunDigestPhase.WAITING_APPROVAL:
        headline = f"Waiting for your approval ({pending_approval_count})"
    elif phase == RunDigestPhase.RUNNING and current_tool:
        headline = f"Step {step_count}: {current_tool}"
    elif phase == RunDigestPhase.COMPLETED:
        headline = f"Finished ({step_count} steps)"
    elif phase == RunDigestPhase.ERROR:
        headline = "Run failed"
    elif phase == RunDigestPhase.CANCELLED:
        headline = "Run cancelled"
    else:
        headline = "Ready"

    return RunDigest(
        chat_id=chat_id,
        phase=phase,
        step_count=step_count,
        current_tool=current_tool,
        current_step_key=current_step_key,
        pending_approval_count=pending_approval_count,
        elapsed_seconds=max(0, elapsed_seconds),
        headline=headline,
        recent_steps=recent_steps,
    )


__all__ = [
    "RunDigest",
    "RunDigestPhase",
    "RunDigestStep",
    "build_run_digest",
]
