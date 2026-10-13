"""Skill usage statistics and lifecycle state collector.

Tracks skill usage patterns and lifecycle state for the curator / forgetting
mechanism.  Statistics are stored in {skill_dir}/.stats.json for lightweight
persistence.

[INPUT]
- backends.skills.types::SkillUsageStats (POS: Skill system core data types.)
- backends.skills.types::SkillLifecycleStatus (POS: Skill system core data types.)
- infra.atomic_write::atomic_write (POS: Crash-consistent file write.)

[OUTPUT]
- SkillStatsCollector: Collects and persists skill usage statistics and
  lifecycle state (lifecycle_status, pinned).

[POS]
Skill usage statistics and lifecycle state collector.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.backends.skills.types import SkillLifecycleStatus, SkillUsageStats
from myrm_agent_harness.infra.atomic_write import atomic_write

logger = logging.getLogger(__name__)

_STATS_FILENAME = ".stats.json"
_CORRUPT_SUFFIX = ".corrupt"


class SkillStatsCollector:
    """Collects and persists skill usage statistics and lifecycle state.

    Design:
    - The ledger on disk is the only state: every change reads it, modifies it and writes it back at once, so
      nothing is cached or left to flush, and a ledger changed elsewhere is never overwritten from stale memory
    - Per-skill stats stored in {skill_dir}/.stats.json, written atomically so a crash never leaves a torn file
    - A skill's first observation creates its ledger, which anchors ``created_at`` for the forgetting policy
    - A ledger that cannot be parsed is set aside as ``.stats.json.corrupt``; one that cannot be read is never
      replaced by a blank one
    - No lock: two writers changing one ledger at the same moment can lose an update; callers run on one event
      loop and never await between the read and the write
    - No database dependency (aligns with framework design principles)
    - Lifecycle state (lifecycle_status, pinned) co-located with usage data
    """

    # ── Usage recording ─────────────────────────────────────────────

    def record_use(self, skill_path: Path, *, success: bool | None) -> None:
        """Record one run that used the skill.

        ``success`` is the observed outcome of the run's tool calls, or ``None`` when no outcome was
        observable (the skill was only loaded, or several loaded skills made the owner ambiguous).
        A use always counts; only an observed outcome moves the success/failure counters.

        If the skill is currently ``stale``, it is auto-recovered to
        ``active`` (inspired by Hermes' stale-reactivation design).

        Args:
            skill_path: Absolute path to skill directory
            success: Observed outcome of the run, None when unobservable
        """
        stats = self._load_stats(skill_path)
        stats.call_count += 1
        if success is True:
            stats.success_count += 1
        elif success is False:
            stats.failure_count += 1
        now = datetime.now(UTC)
        stats.last_used_at = now
        stats.append_usage(timestamp=now.isoformat(), success=success)

        if stats.lifecycle_status == SkillLifecycleStatus.STALE:
            stats.lifecycle_status = SkillLifecycleStatus.ACTIVE
            logger.info("Skill %s auto-recovered from stale to active on usage", skill_path.name)
        self._write_stats(skill_path, stats)

    # ── Lifecycle management ────────────────────────────────────────

    def update_lifecycle_status(
        self,
        skill_path: Path,
        status: SkillLifecycleStatus,
    ) -> None:
        """Set the lifecycle status for a skill.

        Args:
            skill_path: Absolute path to skill directory
            status: Target lifecycle status
        """
        stats = self._load_stats(skill_path)
        stats.lifecycle_status = status
        self._write_stats(skill_path, stats)

    def set_pinned(self, skill_path: Path, *, pinned: bool) -> None:
        """Pin or unpin a skill.

        Args:
            skill_path: Absolute path to skill directory
            pinned: True to pin (exempt from curator), False to unpin
        """
        stats = self._load_stats(skill_path)
        stats.pinned = pinned
        self._write_stats(skill_path, stats)

    def reset_usage(self, skill_path: Path) -> None:
        """Discard the verdict on past runs.

        Clears the run counters and history so the success rate starts a fresh window
        (e.g. after the skill was fixed). Lifecycle state, pin, provenance and ``last_used_at`` are
        kept: resetting must neither revive an archived skill nor make an idle one look unused.

        Args:
            skill_path: Absolute path to skill directory
        """
        stats = self._load_stats(skill_path)
        stats.call_count = 0
        stats.success_count = 0
        stats.failure_count = 0
        stats.usage_history.clear()
        self._write_stats(skill_path, stats)

    def archive_merged(self, skill_path: Path, merged_into: str) -> None:
        """Archive a skill that a consolidation folded into ``merged_into``.

        Args:
            skill_path: Absolute path to the absorbed skill directory
            merged_into: Name of the skill that absorbed it
        """
        stats = self._load_stats(skill_path)
        stats.lifecycle_status = SkillLifecycleStatus.ARCHIVED
        stats.merged_into = merged_into
        self._write_stats(skill_path, stats)

    def inherit_usage(self, skill_path: Path, sources: Iterable[SkillUsageStats]) -> None:
        """Fold the sources' run counters into the skill.

        Used when a merge or umbrella skill absorbs the skills it replaces; ``last_used_at`` keeps the latest.

        Args:
            skill_path: Absolute path to the skill directory that absorbs the usage
            sources: Usage stats of the skills being absorbed
        """
        stats = self._load_stats(skill_path)
        for source in sources:
            stats.call_count += source.call_count
            stats.success_count += source.success_count
            stats.failure_count += source.failure_count
            if source.last_used_at and (stats.last_used_at is None or source.last_used_at > stats.last_used_at):
                stats.last_used_at = source.last_used_at
        self._write_stats(skill_path, stats)

    # ── Reading ─────────────────────────────────────────────────────

    def get_stats(self, skill_path: Path) -> SkillUsageStats:
        """Get the skill's current statistics, read fresh from disk.

        The first observation of a skill creates its ledger (see the class design notes).
        Treat the result as read-only: changes to the returned object are not saved. Change stats through the
        collector's methods. A ledger that cannot be read right now yields an unsaved blank view instead of
        failing the caller.
        """
        try:
            return self._load_stats(skill_path)
        except OSError as e:
            logger.warning("Failed to read stats for skill %s: %s", skill_path.name, e)
            return SkillUsageStats(created_at=datetime.now(UTC))

    # ── Internal helpers ────────────────────────────────────────────

    def _load_stats(self, skill_path: Path) -> SkillUsageStats:
        """Load existing stats from disk. Sets created_at on first encounter.

        Raises:
            OSError: The ledger exists but cannot be read; the caller must not replace it with a blank one.
        """
        stats_file = skill_path / _STATS_FILENAME

        try:
            data = json.loads(stats_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._new_stats(skill_path)
        except ValueError:  # JSONDecodeError and UnicodeDecodeError
            data = None

        if not isinstance(data, dict):
            self._set_aside_corrupt(stats_file)
            return self._new_stats(skill_path)

        stats = SkillUsageStats.from_dict(data)
        if stats.created_at is None:
            stats.created_at = datetime.now(UTC)
        return stats

    def _new_stats(self, skill_path: Path) -> SkillUsageStats:
        stats = SkillUsageStats(created_at=datetime.now(UTC))
        self._write_stats(skill_path, stats)
        return stats

    @staticmethod
    def _set_aside_corrupt(stats_file: Path) -> None:
        """Keep an unparseable ledger next to the new one so it can still be inspected."""
        aside = stats_file.with_name(stats_file.name + _CORRUPT_SUFFIX)
        logger.warning(
            "Stats file %s is unreadable; keeping it as %s and starting a new ledger", stats_file, aside.name
        )
        with contextlib.suppress(OSError):
            os.replace(stats_file, aside)

    def _write_stats(self, skill_path: Path, stats: SkillUsageStats) -> None:
        """Atomically write stats for a single skill; a skill directory that is gone is left gone."""
        if not skill_path.is_dir():
            logger.debug("Skill directory %s no longer exists; stats not written", skill_path)
            return
        try:
            atomic_write(skill_path / _STATS_FILENAME, json.dumps(stats.to_dict(), indent=2))
        except Exception as e:
            logger.warning(
                "Failed to write stats for skill %s: %s",
                skill_path.name,
                e,
            )
