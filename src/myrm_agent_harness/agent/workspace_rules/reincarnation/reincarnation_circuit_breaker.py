# [INPUT]: CrashCause, HeritageSafetyFilterGate, HeritageTabooLesson, Path, ReincarnationDossier, ReincarnationEvent, Sequence, SoulLineageRecord, UnfinishedGoal, WorkingHabitShortcut
# [OUTPUT]: ReincarnationCircuitBreaker
# [POS]: agent/workspace_rules/reincarnation/reincarnation_circuit_breaker.py

"""Reincarnation circuit breaker triggering graceful death and distilling REINCARNATION.md upon crash.

[INPUT]
- CrashCause, HeritageSafetyFilterGate, HeritageTabooLesson, ReincarnationDossier, ReincarnationEvent, SoulLineageRecord, UnfinishedGoal, WorkingHabitShortcut: Models.
- Path: Filesystem paths for saving REINCARNATION.md.

[OUTPUT]
- ReincarnationCircuitBreaker: Intercepts catastrophic context snowball/crashes and distills clean heritage.

[POS]
Circuit breaker and distillation layer in reincarnation subsystem transforming crashes into generational wisdom.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Sequence
import uuid

from .heritage_safety_filter_gate import HeritageSafetyFilterGate
from .reincarnation_types import (
    CrashCause,
    HeritageTabooLesson,
    ReincarnationDossier,
    ReincarnationEvent,
    SoulLineageRecord,
    UnfinishedGoal,
    WorkingHabitShortcut,
)

logger = logging.getLogger(__name__)


class ReincarnationCircuitBreaker:
    """Detects catastrophic session degradation and crystallizes durable cross-model heritage."""

    REINCARNATION_FILENAME: str = "REINCARNATION.md"

    def __init__(self, safety_gate: HeritageSafetyFilterGate | None = None) -> None:
        self._safety_gate = safety_gate or HeritageSafetyFilterGate()

    def create_heritage_dossier(
        self,
        generation: int,
        predecessor_model: str,
        successor_model: str,
        cumulative_turns: int,
        taboo_lessons: Sequence[HeritageTabooLesson],
        working_habits: Sequence[WorkingHabitShortcut],
        unfinished_goals: Sequence[UnfinishedGoal],
    ) -> ReincarnationDossier:
        """Assemble raw components, sanitize with safety gate, and return clean bounded dossier."""
        now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        lineage = SoulLineageRecord(
            generation=generation,
            predecessor_model=predecessor_model,
            successor_model=successor_model,
            birth_timestamp=now_iso,
            cumulative_turns=cumulative_turns,
        )

        raw_dossier = ReincarnationDossier(
            lineage=lineage,
            taboo_lessons=taboo_lessons,
            working_habits=working_habits,
            unfinished_goals=unfinished_goals,
        )

        return self._safety_gate.sanitize_dossier(raw_dossier)

    def trigger_reincarnation_circuit(
        self,
        workspace_dir: Path,
        generation: int,
        predecessor_model: str,
        successor_model: str,
        cause: CrashCause,
        cumulative_turns: int,
        taboo_lessons: Sequence[HeritageTabooLesson],
        working_habits: Sequence[WorkingHabitShortcut] = (),
        unfinished_goals: Sequence[UnfinishedGoal] = (),
    ) -> ReincarnationEvent:
        """Crystallize heritage dossier and safely persist REINCARNATION.md to workspace root."""
        dossier = self.create_heritage_dossier(
            generation=generation,
            predecessor_model=predecessor_model,
            successor_model=successor_model,
            cumulative_turns=cumulative_turns,
            taboo_lessons=taboo_lessons,
            working_habits=working_habits,
            unfinished_goals=unfinished_goals,
        )

        md_content = dossier.render_markdown()
        target_path = workspace_dir / self.REINCARNATION_FILENAME

        try:
            target_path.write_text(md_content, encoding="utf-8")
            logger.info("Successfully persisted reincarnation contract to: %s", target_path)
        except OSError as exc:
            logger.error("Failed writing reincarnation file %s: %s", target_path, exc)

        event = ReincarnationEvent(
            event_id=f"reincarnation-{uuid.uuid4().hex[:8]}",
            cause=cause,
            generation=generation,
            dossier=dossier,
            reincarnated_at=dossier.lineage.birth_timestamp,
        )

        return event
