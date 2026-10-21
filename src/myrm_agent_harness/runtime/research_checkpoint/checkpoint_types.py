"""Strongly typed data contracts for long-horizon research checkpoints and draft persistence.

[OUTPUT]
- ResearchStatus: Lifecycle progression state of a long-horizon research task.
- ResearchChapterDraft: Atomically materialized research chapter draft.
- ResearchCheckpoint: Structured execution state snapshot for resumption.
- ResumptionPlan: Actionable plan instructing the agent loop where and how to resume.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- ResearchStatus
- ResearchChapterDraft
- ResearchCheckpoint
- ResumptionPlan

[POS]
Strongly typed data contracts for long-horizon research checkpoints and draft persistence.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ResearchStatus(StrEnum):
    """Execution status of a long-horizon research job."""

    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class ResearchChapterDraft:
    """Atomically saved intermediate research chapter or sub-stage draft."""

    chapter_index: int
    title: str
    content_markdown: str
    sources_cited: tuple[str, ...] = field(default_factory=tuple)
    token_estimate: int = 0
    duration_ms: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """Convert chapter draft to serializable dictionary."""
        return {
            "chapter_index": self.chapter_index,
            "title": self.title,
            "content_markdown": self.content_markdown,
            "sources_cited": list(self.sources_cited),
            "token_estimate": self.token_estimate,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ResearchChapterDraft:
        """Hydrate chapter draft from dictionary."""
        return cls(
            chapter_index=int(str(data.get("chapter_index", 0))),
            title=str(data.get("title", "")),
            content_markdown=str(data.get("content_markdown", "")),
            sources_cited=tuple(str(s) for s in (data.get("sources_cited") or ())),
            token_estimate=int(str(data.get("token_estimate", 0))),
            duration_ms=float(str(data.get("duration_ms", 0.0))),
            created_at=float(str(data.get("created_at", time.time()))),
        )


@dataclass(frozen=True)
class ResearchCheckpoint:
    """Persistent state vector tracking completed chapters and resources expended."""

    checkpoint_id: str
    task_id: str
    session_id: str
    current_status: ResearchStatus
    completed_chapters: tuple[int, ...] = field(default_factory=tuple)
    pending_chapters: tuple[int, ...] = field(default_factory=tuple)
    total_tokens_consumed: int = 0
    total_duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    @property
    def is_finished(self) -> bool:
        """Return True if all planned chapters are marked completed."""
        return len(self.pending_chapters) == 0 and len(self.completed_chapters) > 0


@dataclass(frozen=True)
class ResumptionPlan:
    """Synthesized instruction guiding the agent loop to resume without redundant work."""

    task_id: str
    checkpoint_id: str
    can_resume: bool
    next_chapter_index: int | None
    completed_chapters_count: int
    pending_chapters_count: int
    context_injection_prompt: str
