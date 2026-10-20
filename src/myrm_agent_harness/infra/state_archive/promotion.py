"""Journaled, crash-recoverable promotion of a staged tree into a live root.

[INPUT]
- infra.atomic_write::atomic_write (POS: crash-safe journal writes)

[OUTPUT]
- PromotionPlan: Live/staging/aside roots plus the top-level names to swap.
- PromotionPhase / PromotionJournal: Persisted progress marker.
- promote: Move live entries aside, move staged entries in, commit the journal.
- recover_interrupted: Roll back a promotion that a crash left half-applied.
- rollback: Undo the swap described by a journal (used by promote on failure and by recovery).

[POS]
Final step of ``infra/state_archive`` imports and restore points. It must run before any
process opens the affected files. All moves are ``os.replace`` on a single volume; progress is
recovered by inspecting the filesystem against the journal's ``live_present`` snapshot, so a
crash between any two moves is repairable without per-step bookkeeping.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from myrm_agent_harness.infra.atomic_write import atomic_write

logger = logging.getLogger(__name__)


class PromotionPhase(StrEnum):
    """Lifecycle of one promotion."""

    PROMOTING = "promoting"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"


@dataclass(frozen=True, slots=True)
class PromotionPlan:
    """What to swap. ``entries`` are top-level names relative to every root."""

    live_root: Path
    staging_root: Path
    aside_root: Path
    journal_path: Path
    entries: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PromotionJournal:
    """Persisted promotion state."""

    phase: PromotionPhase
    live_root: str
    staging_root: str
    aside_root: str
    entries: tuple[str, ...]
    live_present: tuple[str, ...]
    started_at: float
    finished_at: float | None = None
    error: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "phase": self.phase.value,
                "live_root": self.live_root,
                "staging_root": self.staging_root,
                "aside_root": self.aside_root,
                "entries": list(self.entries),
                "live_present": list(self.live_present),
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "error": self.error,
            }
        )

    @classmethod
    def load(cls, path: Path) -> PromotionJournal | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                phase=PromotionPhase(data["phase"]),
                live_root=str(data["live_root"]),
                staging_root=str(data["staging_root"]),
                aside_root=str(data["aside_root"]),
                entries=tuple(str(e) for e in data["entries"]),
                live_present=tuple(str(e) for e in data["live_present"]),
                started_at=float(data["started_at"]),
                finished_at=None if data.get("finished_at") is None else float(data["finished_at"]),
                error=data.get("error"),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def with_phase(self, phase: PromotionPhase, error: str | None = None) -> PromotionJournal:
        return PromotionJournal(
            phase=phase,
            live_root=self.live_root,
            staging_root=self.staging_root,
            aside_root=self.aside_root,
            entries=self.entries,
            live_present=self.live_present,
            started_at=self.started_at,
            finished_at=time.time(),
            error=error,
        )


def promote(plan: PromotionPlan) -> PromotionJournal:
    """Swap ``plan.entries`` from staging into live, keeping the previous live entries aside.

    Returns the final journal (``COMMITTED`` or ``ROLLED_BACK``). Never raises for filesystem
    failures: a failed swap is rolled back and reported through the journal's ``error``.
    """
    _validate_entries(plan.entries)
    live_present = tuple(name for name in plan.entries if _exists(plan.live_root / name))
    journal = PromotionJournal(
        phase=PromotionPhase.PROMOTING,
        live_root=str(plan.live_root),
        staging_root=str(plan.staging_root),
        aside_root=str(plan.aside_root),
        entries=plan.entries,
        live_present=live_present,
        started_at=time.time(),
    )
    _save(plan.journal_path, journal)
    try:
        for name in plan.entries:
            _swap_entry(plan, name, name in live_present)
    except OSError as exc:
        logger.error("[StateArchive] Promotion failed, rolling back: %s", exc)
        try:
            rollback(journal)
        except OSError as rollback_exc:
            # The on-disk journal stays PROMOTING so the next boot retries the rollback.
            logger.critical("[StateArchive] Rollback incomplete: %s", rollback_exc)
            return journal.with_phase(PromotionPhase.PROMOTING, f"rollback incomplete: {rollback_exc}")
        return _finish(plan.journal_path, journal, PromotionPhase.ROLLED_BACK, str(exc))
    return _finish(plan.journal_path, journal, PromotionPhase.COMMITTED)


def recover_interrupted(journal_path: Path) -> PromotionJournal | None:
    """If a previous promotion died mid-way, roll it back and return the updated journal."""
    journal = PromotionJournal.load(journal_path)
    if journal is None or journal.phase is not PromotionPhase.PROMOTING:
        return None
    logger.warning("[StateArchive] Recovering interrupted promotion started at %s", journal.started_at)
    rollback(journal)
    return _finish(journal_path, journal, PromotionPhase.ROLLED_BACK, "interrupted")


def rollback(journal: PromotionJournal) -> None:
    """Restore the live root to its pre-promotion state by inspecting the filesystem."""
    live, staging, aside = Path(journal.live_root), Path(journal.staging_root), Path(journal.aside_root)
    live_present = set(journal.live_present)
    for name in reversed(journal.entries):
        live_path, staging_path, aside_path = live / name, staging / name, aside / name
        if name in live_present:
            if not _exists(aside_path):
                continue  # original never moved aside: live still holds it
            if _exists(live_path):
                _move(live_path, staging_path)
            _move(aside_path, live_path)
        elif _exists(live_path) and not _exists(staging_path):
            _move(live_path, staging_path)  # entry did not exist before; hand the promoted copy back


def _swap_entry(plan: PromotionPlan, name: str, was_live: bool) -> None:
    live_path, staging_path, aside_path = plan.live_root / name, plan.staging_root / name, plan.aside_root / name
    if was_live:
        _move(live_path, aside_path)
    if _exists(staging_path):
        _move(staging_path, live_path)


def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)


def _exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _validate_entries(entries: tuple[str, ...]) -> None:
    for name in entries:
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            raise ValueError(f"promotion entries must be top-level names, got {name!r}")


def _save(path: Path, journal: PromotionJournal) -> None:
    atomic_write(path, journal.to_json())


def _finish(path: Path, journal: PromotionJournal, phase: PromotionPhase, error: str | None = None) -> PromotionJournal:
    final = journal.with_phase(phase, error)
    with contextlib.suppress(OSError):
        _save(path, final)
    return final
