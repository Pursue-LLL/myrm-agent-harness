# [INPUT]: None
# [OUTPUT]: CrashCause, HeritageHydrationResult, HeritageTabooLesson, ReincarnationDossier, ReincarnationEvent, SoulLineageRecord, UnfinishedGoal, WorkingHabitShortcut
# [POS]: agent/workspace_rules/reincarnation/reincarnation_types.py

"""Domain models and contracts for reincarnation namespace and agent heritage inheritance suite.

[INPUT]
- None (Self-contained domain models).

[OUTPUT]
- CrashCause: Enum for triggers of session rebirth (context overflow, manual switch, deadlock).
- SoulLineageRecord: Generation number, predecessor/successor models, and cumulative pedigree.
- HeritageTabooLesson: Hard-learned lessons, user rebukes, and inviolable guardrail rules.
- WorkingHabitShortcut: User-specific shortcuts, shorthand slang, and preferred filesystem paths.
- UnfinishedGoal: Pending long-horizon objectives inherited across generations.
- ReincarnationDossier: Aggregated 4-section heritage package strictly bounded to 2000 chars.
- ReincarnationEvent: Metadata receipt describing the reincarnation occurrence.
- HeritageHydrationResult: Prompt injection block and post-hydration archive outcome.

[POS]
Domain contract layer for Item 315 ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class CrashCause(str, Enum):
    """The fundamental trigger precipitating reincarnation."""

    CONTEXT_OVERFLOW = "context_overflow"         # Irreversible token exhaustion / context snowball
    DEADLOCK_TIMEOUT = "deadlock_timeout"         # Task deadlock or cyclic loop termination
    MANUAL_MODEL_SWITCH = "manual_model_switch"   # User switched foundation model mid-workflow
    FATAL_CORRUPTION = "fatal_corruption"         # Unrecoverable session state corruption


@dataclass(frozen=True)
class SoulLineageRecord:
    """Ancestral pedigree tracing generational evolution and host models."""

    generation: int
    predecessor_model: str
    successor_model: str
    birth_timestamp: str
    cumulative_turns: int = 0
    persona_core_name: str = "Myrmidon"


@dataclass(frozen=True)
class HeritageTabooLesson:
    """A verified painful mistake, user admonition, or strict operational boundary."""

    lesson_id: str
    trigger_context: str
    directive_rule: str
    severity: str = "critical"            # "critical", "warning", "info"
    is_user_verified: bool = True


@dataclass(frozen=True)
class WorkingHabitShortcut:
    """User-specific idiosyncratic shorthand, abbreviation, or workflow shortcut."""

    shortcut_pattern: str
    expanded_meaning: str
    frequency: int = 1


@dataclass(frozen=True)
class UnfinishedGoal:
    """High-priority objective inherited from the previous generation."""

    goal_id: str
    description: str
    progress_ratio: float = 0.0
    blockers: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReincarnationDossier:
    """Standardized 4-section heritage payload conforming to the REINCARNATION.md contract."""

    lineage: SoulLineageRecord
    taboo_lessons: Sequence[HeritageTabooLesson]
    working_habits: Sequence[WorkingHabitShortcut]
    unfinished_goals: Sequence[UnfinishedGoal]

    MAX_CHAR_BUDGET: int = 2000

    def render_markdown(self) -> str:
        """Render the 4 canonical sections into a bounded REINCARNATION.md markdown document."""
        sections: list[str] = [
            f"# 📜 [REINCARNATION.md: Generation {self.lineage.generation}]",
            f"> Predecessor: `{self.lineage.predecessor_model}` ➔ Successor: `{self.lineage.successor_model}` | Born: {self.lineage.birth_timestamp}\n",
        ]

        # Section 1: Soul Lineage
        sections.append("## 🧬 Soul Lineage")
        sections.append(
            f"- Generation: #{self.lineage.generation} ({self.lineage.persona_core_name})\n"
            f"- Cumulative Turns Preserved: {self.lineage.cumulative_turns}"
        )

        # Section 2: Hard Lessons & Taboos
        sections.append("\n## ⚠️ Hard Lessons & Taboos")
        if self.taboo_lessons:
            for item in self.taboo_lessons:
                verified_tag = " [VERIFIED]" if item.is_user_verified else ""
                sections.append(f"- [{item.severity.upper()}]{verified_tag} {item.directive_rule} (Context: {item.trigger_context})")
        else:
            sections.append("- (No previous taboos recorded)")

        # Section 3: Working Habits & Short-Circuits
        sections.append("\n## ⚡ Working Habits & Short-Circuits")
        if self.working_habits:
            for habit in self.working_habits:
                sections.append(f"- Shorthand `{habit.shortcut_pattern}` ➔ {habit.expanded_meaning} (Observed: {habit.frequency}x)")
        else:
            sections.append("- (Standard operational conventions apply)")

        # Section 4: Unfinished Goals
        sections.append("\n## 🎯 Unfinished Goals")
        if self.unfinished_goals:
            for goal in self.unfinished_goals:
                blocker_str = f" | Blockers: {', '.join(goal.blockers)}" if goal.blockers else ""
                sections.append(f"- [{int(goal.progress_ratio * 100)}%] {goal.description}{blocker_str}")
        else:
            sections.append("- (All previous objectives accomplished)")

        rendered = "\n".join(sections).strip()
        if len(rendered) > self.MAX_CHAR_BUDGET:
            return rendered[: self.MAX_CHAR_BUDGET - 32] + "\n\n... [HERITAGE_BUDGET_CONTAINED]"
        return rendered


@dataclass(frozen=True)
class ReincarnationEvent:
    """Event log describing a reincarnation occurrence."""

    event_id: str
    cause: CrashCause
    generation: int
    dossier: ReincarnationDossier
    reincarnated_at: str


@dataclass(frozen=True)
class HeritageHydrationResult:
    """Outcome of hydrating reincarnation heritage into new session context."""

    has_heritage: bool
    generation: int
    injected_prompt_block: str
    archived_file_path: str
    is_archived: bool
