"""Strongly typed contracts for Lossless Context Pivot and Scratchpad Reset Suite.

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- PivotTriggerKind: Classification of events triggering a clean context reset.
- HandoffScratchpad: Structured workbench notes model capturing phase findings and next steps.
- ArchivedContextSnapshot: Lineage metadata record of archived pre-pivot conversation history.
- ContextPivotResult: Outcome metrics and cleansed message bundle after context pivot.
- ContextPivotConfig: Tunable configuration for context pivot operations.

[POS]
Defines data structures powering zero-compaction memory wipes, handoff scratchpad continuation,
and infinite-horizon agent task execution.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class PivotTriggerKind(str, enum.Enum):
    """Trigger source leading to a clean context pivot."""

    AGENT_AUTONOMOUS = "agent_autonomous"
    BUDGET_THRESHOLD = "budget_threshold"
    USER_MANUAL = "user_manual"


@dataclass(slots=True)
class HandoffScratchpad:
    """Structured handoff notes capturing accumulated achievements and next phase directives."""

    phase_title: str
    completed_goals: list[str] = field(default_factory=list)
    architectural_decisions: list[str] = field(default_factory=list)
    active_file_paths: list[str] = field(default_factory=list)
    next_step_objectives: list[str] = field(default_factory=list)
    raw_notes_markdown: str = ""
    created_at: float = field(default_factory=time.time)

    def format_xml(self) -> str:
        """Formats scratchpad into a compact XML injection block for system prompt augmentation."""
        parts: list[str] = [f'<handoff-scratchpad phase="{self.phase_title}">']

        if self.completed_goals:
            goals_text = "\n".join(f"- {g}" for g in self.completed_goals)
            parts.append(f"<completed-goals>\n{goals_text}\n</completed-goals>")

        if self.architectural_decisions:
            decisions_text = "\n".join(f"- {d}" for d in self.architectural_decisions)
            parts.append(f"<architectural-decisions>\n{decisions_text}\n</architectural-decisions>")

        if self.active_file_paths:
            files_text = "\n".join(f"- {f}" for f in self.active_file_paths)
            parts.append(f"<active-files>\n{files_text}\n</active-files>")

        if self.next_step_objectives:
            next_text = "\n".join(f"- {n}" for n in self.next_step_objectives)
            parts.append(f"<next-step-objectives>\n{next_text}\n</next-step-objectives>")

        if self.raw_notes_markdown.strip():
            parts.append(f"<additional-notes>\n{self.raw_notes_markdown.strip()}\n</additional-notes>")

        parts.append("</handoff-scratchpad>")
        return "\n\n".join(parts)

    def to_dict(self) -> dict[str, object]:
        """Serializes scratchpad to dictionary."""
        return {
            "phase_title": self.phase_title,
            "completed_goals": list(self.completed_goals),
            "architectural_decisions": list(self.architectural_decisions),
            "active_file_paths": list(self.active_file_paths),
            "next_step_objectives": list(self.next_step_objectives),
            "raw_notes_markdown": self.raw_notes_markdown,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class ArchivedContextSnapshot:
    """Historical archive metadata representing a shelved context generation."""

    snapshot_id: str
    session_id: str
    phase_title: str
    message_count: int
    char_count: int
    archived_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class ContextPivotConfig:
    """Configuration governing context reset and prompt generation."""

    trigger_kind: PivotTriggerKind = PivotTriggerKind.AGENT_AUTONOMOUS
    inject_continuation_user_prompt: bool = True
    continuation_prompt_template: str = (
        "Please proceed directly with the next objectives defined in the handoff scratchpad: '{phase}'."
    )


@dataclass(slots=True)
class ContextPivotResult:
    """Comprehensive outcome of a lossless clean context pivot."""

    session_id: str
    snapshot_id: str
    trigger_kind: PivotTriggerKind
    reclaimed_tokens_estimate: int
    prior_message_count: int
    clean_messages: list[dict[str, object]]
    scratchpad: HandoffScratchpad
    pivot_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """Serializes pivot result to dictionary."""
        return {
            "session_id": self.session_id,
            "snapshot_id": self.snapshot_id,
            "trigger_kind": self.trigger_kind.value,
            "reclaimed_tokens_estimate": self.reclaimed_tokens_estimate,
            "prior_message_count": self.prior_message_count,
            "clean_message_count": len(self.clean_messages),
            "scratchpad": self.scratchpad.to_dict(),
            "pivot_duration_ms": self.pivot_duration_ms,
        }
