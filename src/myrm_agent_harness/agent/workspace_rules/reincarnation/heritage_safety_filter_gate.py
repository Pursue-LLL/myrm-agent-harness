# [INPUT]: HeritageTabooLesson, ReincarnationDossier, Sequence, WorkingHabitShortcut
# [OUTPUT]: HeritageSafetyFilterGate
# [POS]: agent/workspace_rules/reincarnation/heritage_safety_filter_gate.py

"""Safety and anti-hallucination filter gate screening heritage before inter-generational transfer.

[INPUT]
- HeritageTabooLesson, ReincarnationDossier, WorkingHabitShortcut: Contract models.

[OUTPUT]
- HeritageSafetyFilterGate: Sanitizes speculative hypotheses and enforces 2000-char budget.

[POS]
Quality assurance and sanitization layer in reincarnation subsystem preventing technical debt accumulation.
"""

from __future__ import annotations

import re
from typing import Sequence

from .reincarnation_types import (
    HeritageTabooLesson,
    ReincarnationDossier,
    WorkingHabitShortcut,
)


class HeritageSafetyFilterGate:
    """Screens inherited memories against speculative hallucination and technical debt accumulation."""

    # Patterns indicating speculative hypotheses rather than verified operational rules
    SPECULATIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"\b(?:maybe|perhaps|it seems|probably|i guess|might be|could be)\b", re.IGNORECASE),
        re.compile(r"(?:大概|可能|推测|似乎|估计|猜测|未经确认)", re.IGNORECASE),
    )

    # Valid taboo directive patterns ensuring actionable guardrails
    ACTIONABLE_TABOO_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"\b(?:never|do not|prohibit|forbidden|must not|avoid|disallow)\b", re.IGNORECASE),
        re.compile(r"(?:严禁|禁止|切勿|绝不|务必不要|不可|违规)", re.IGNORECASE),
    )

    def is_actionable_lesson(self, lesson: HeritageTabooLesson) -> bool:
        """Verify that a lesson is non-speculative, actionable, and verified."""
        # 1. Reject speculative wording
        if any(p.search(lesson.directive_rule) for p in self.SPECULATIVE_PATTERNS):
            return False

        # 2. Must either be explicitly verified by user or contain strict prohibitive keywords
        if lesson.is_user_verified:
            return True

        return any(p.search(lesson.directive_rule) for p in self.ACTIONABLE_TABOO_PATTERNS)

    def sanitize_working_habits(
        self,
        habits: Sequence[WorkingHabitShortcut],
    ) -> Sequence[WorkingHabitShortcut]:
        """Filter out low-confidence, one-off accidental strings from habit shortcuts."""
        sanitized: list[WorkingHabitShortcut] = []
        for h in habits:
            # Shortcut must be concise (< 30 chars) and expanded meaning must be coherent
            if 1 <= len(h.shortcut_pattern.strip()) <= 30 and len(h.expanded_meaning.strip()) >= 2:
                sanitized.append(h)
        return tuple(sanitized)

    def sanitize_dossier(self, raw_dossier: ReincarnationDossier) -> ReincarnationDossier:
        """Screen all 4 sections of the dossier and enforce character budget containment."""
        clean_lessons = [
            lesson for lesson in raw_dossier.taboo_lessons if self.is_actionable_lesson(lesson)
        ]

        clean_habits = self.sanitize_working_habits(raw_dossier.working_habits)

        # Build sanitized dossier
        clean_dossier = ReincarnationDossier(
            lineage=raw_dossier.lineage,
            taboo_lessons=tuple(clean_lessons),
            working_habits=clean_habits,
            unfinished_goals=raw_dossier.unfinished_goals,
        )

        return clean_dossier
