# [INPUT]: CrashCause, HeritageHydrationResult, HeritageSafetyFilterGate, HeritageTabooLesson, InstantHeritageHydrator, Path, ReincarnationCircuitBreaker, ReincarnationEvent, Sequence, UnfinishedGoal, WorkingHabitShortcut
# [OUTPUT]: ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite, ReincarnationProtocolSuite
# [POS]: agent/workspace_rules/reincarnation/reincarnation_protocol_suite.py

"""Comprehensive facade suite for reincarnation namespace and agent heritage inheritance.

[INPUT]
- CrashCause, HeritageHydrationResult, HeritageTabooLesson, ReincarnationEvent, Sequence, UnfinishedGoal, WorkingHabitShortcut: Models.
- HeritageSafetyFilterGate, InstantHeritageHydrator, ReincarnationCircuitBreaker: Engines.
- Path: Filesystem paths.

[OUTPUT]
- ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite: Main facade for Item 315.
- ReincarnationProtocolSuite: Convenient alias.

[POS]
Top-level facade coordinating catastrophic crash circuit breaking, heritage safety filtering, and instant hydration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .heritage_safety_filter_gate import HeritageSafetyFilterGate
from .instant_heritage_hydrator import InstantHeritageHydrator
from .reincarnation_circuit_breaker import ReincarnationCircuitBreaker
from .reincarnation_types import (
    CrashCause,
    HeritageHydrationResult,
    HeritageTabooLesson,
    ReincarnationEvent,
    UnfinishedGoal,
    WorkingHabitShortcut,
)


class ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite:
    """Unified entry point managing agent reincarnation lifecycles and cross-model wisdom transfer."""

    def __init__(self) -> None:
        self._safety_gate = HeritageSafetyFilterGate()
        self._circuit_breaker = ReincarnationCircuitBreaker(self._safety_gate)
        self._hydrator = InstantHeritageHydrator()

    def trigger_emergency_reincarnation(
        self,
        workspace_dir: Path,
        generation: int,
        predecessor_model: str,
        successor_model: str,
        cause: CrashCause = CrashCause.CONTEXT_OVERFLOW,
        cumulative_turns: int = 0,
        taboo_lessons: Sequence[HeritageTabooLesson] = (),
        working_habits: Sequence[WorkingHabitShortcut] = (),
        unfinished_goals: Sequence[UnfinishedGoal] = (),
    ) -> ReincarnationEvent:
        """Execute crash-induced rebirth and persist bounded REINCARNATION.md contract."""
        return self._circuit_breaker.trigger_reincarnation_circuit(
            workspace_dir=workspace_dir,
            generation=generation,
            predecessor_model=predecessor_model,
            successor_model=successor_model,
            cause=cause,
            cumulative_turns=cumulative_turns,
            taboo_lessons=taboo_lessons,
            working_habits=working_habits,
            unfinished_goals=unfinished_goals,
        )

    def hydrate_workspace_heritage(
        self,
        workspace_dir: Path,
        auto_archive: bool = True,
    ) -> HeritageHydrationResult:
        """Inject inherited wisdom into first-turn context and auto-archive file to prevent perpetual token tax."""
        return self._hydrator.hydrate_heritage(
            workspace_dir=workspace_dir,
            auto_archive=auto_archive,
        )

    def inspect_archive_pedigree(self, workspace_dir: Path) -> Sequence[Path]:
        """List all historical generation archives stored in the workspace."""
        archive_dir = workspace_dir / InstantHeritageHydrator.ARCHIVE_DIRNAME
        if not archive_dir.is_dir():
            return ()
        return tuple(sorted(archive_dir.glob("reincarnation_gen_*.md")))


ReincarnationProtocolSuite = ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite
